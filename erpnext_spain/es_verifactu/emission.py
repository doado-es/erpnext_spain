# doc_events de Sales Invoice — ciclo de EMISIÓN, lotes 4b/4c (spec 04 §4-6).
#
# before_submit (4b): RENOMBRE QUIRÚRGICO del borrador a la serie fiscal.
#   Corre DESPUÉS del before_submit del controlador (solo add_remarks) y
#   ANTES de db_update: el resto del submit (GL, on_submit) ya ve el
#   nombre fiscal final.
#
#   - Early-exit barato: compañía sin VeriFactu → una lectura indexada y
#     fuera; el submit prosigue intocado (sin campos es_, sin renombre).
#   - Credencial (empresa, VeriFactu) habilitada: exigida con remedio.
#   - Snapshot del modo operativo POR FACTURA (congelado al emitir, spec
#     04 §2.3): la anulación se gatea por él, no por el modo actual.
#   - posting_date = hoy (recomendación «mantener» de la AEAT: sin
#     retrodatación).
#   - GUARD de renombre: SOLO si el nombre actual es un borrador NUESTRO
#     (empieza por «BORRADOR-» o por el prefijo del patrón de borradores
#     de la compañía). Los nombres explícitos de imports/migraciones (y
#     las facturas amended, cuyo nombre fija _set_amended_name) quedan
#     INTACTOS — el defecto v1 renombraba incondicionalmente.
#   - Serie fiscal: mapeo tipo→serie de la compañía; make_autoname consume
#     el contador tabSeries exactamente UNA vez, DENTRO de la transacción
#     del submit: si el submit falla y la petición se revierte, el número
#     se libera solo (nada de huecos).
#   - rename_doc con rebuild_search=False (el default encola un rebuild de
#     búsqueda global POR submit) y show_alert=False (msgprint).
#   - FIX de children OBLIGATORIO: rename_doc actualiza las filas hijas en
#     DB, pero el doc EN MEMORIA conserva parent=nombre-borrador; sin el
#     fix, update_children() de _save reescribiría el parent VIEJO y las
#     huérfanaría bajo el nombre de borrador (defecto v1).
#
#   CERROJO (4c, spec 04 §12): desde este lote el cerrojo de cadena se
#   sostiene con la API MANUAL (acquire aquí → release en el finally de
#   on_submit): la sección crítica cubre renombre + creación del registro
#   del libro en UNA sola toma. Si algo revienta dentro de before_submit,
#   el except libera ANTES de re-lanzar (nada de cerrojos huérfanos); el
#   lock viaja en doc.flags (misma instancia de Document durante todo el
#   submit).
#
# on_submit (4c, spec 04 §5): creación del RegistroAlta encadenado BAJO el
#   cerrojo + denormalización del estado de la factura + cola de remisión
#   Inmediata (enqueue_after_commit: JAMÁS antes del commit del submit).
#   Mantiene el seam de test de rollback (frappe.flags.es_test_fail_submit)
#   como PRIMER efecto del hook.
#
# validate (4c, spec 04 §4.2): compuertas de la factura (lo más barato
#   primero): amendments bloqueados, desglose o causa de exención,
#   coherencia simplificada↔POS, NIFs de emisor y destinatario (última
#   compuerta, spec 14 §2), reglas de rectificativa y tipo requerido.
#
# before_cancel (4c, spec 04 §6): anulación. La compuerta es el SNAPSHOT
#   de modo de la FACTURA (no el modo actual de la compañía — el defecto
#   v1 imposibilitaba anular facturas del período VeriFactu tras
#   desactivar). Exige «Alta Aceptada» (el alta pendiente/errónea se
#   corrige por subsanación) y crea el RegistroAnulación encadenado.

from __future__ import annotations

import json
import re

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from erpnext_spain.aeat.utils import format_aeat_datetime, require_credential
from erpnext_spain.es_verifactu.invoice import DRAFT_PREFIX, is_draft_name
from erpnext_spain.es_verifactu.utils import data_adapter
from erpnext_spain.es_verifactu.utils.locks import acquire_chain_lock, release_chain_lock
from erpnext_spain.nif import validator
from erpnext_spain.utils.gating import is_verifactu_active

VERIFACTU_PURPOSE = "VeriFactu"

VERIFACTU_MODE = "Verifactu"
VERIFACTU_TEST_MODE = "Verifactu en pruebas"

LEDGER_DOCTYPE = "ES Verifactu Billing Record"

# Estado del REGISTRO del libro al nacer (spec 04 §3).
PENDING_SEND_STATE = "PendienteEnvio"

# Estados denormalizados de la FACTURA (spec 04 §3): mapa registro×estado →
# estado de factura, patrón VERIFACTU_INVOICE_STATUS_MAPPER de la referencia
# (label set propio: Alta Aceptada, Alta Con Errores, Anulada, Pendiente
# Envío; las variantes de subsanación las completa el procesador de
# respuestas del lote 5).
INVOICE_STATUS_PENDING_SEND = "Pendiente Envío"
INVOICE_STATUS_ISSUANCE_ACCEPTED = "Alta Aceptada"
INVOICE_STATUS_ISSUANCE_WITH_ERRORS = "Alta Con Errores"
INVOICE_STATUS_CANCELLED = "Anulada"

# Mapa registro×estado del libro → estado de factura: lo consume el
# procesador de respuestas (lote 5); aquí fija la denominación canónica.
INVOICE_STATUS_BY_LEDGER: dict[str, dict[str, str]] = {
	"RegistroAlta": {
		"Correcto": INVOICE_STATUS_ISSUANCE_ACCEPTED,
		"AceptadoConErrores": INVOICE_STATUS_ISSUANCE_WITH_ERRORS,
	},
	"RegistroAnulacion": {"Correcto": INVOICE_STATUS_CANCELLED},
}

# Flag del seam de test de rollback (lote 4b): simula un fallo DESPUÉS del
# renombre y ANTES del registro del libro.
FLAG_TEST_FAIL_SUBMIT = "es_test_fail_submit"

# Remisión Inmediata (spec 04 §8): drenaje del outbox tras el commit.
IMMEDIATE_REMISSION = "Inmediata"
TASK_SEND_PENDING = "erpnext_spain.es_verifactu.tasks.send_pending"

# Flag bajo el que before_submit entrega el cerrojo a on_submit.
FLAG_CHAIN_LOCK = "es_verifactu_chain_lock"


# ---------------------------------------------------------------------------
# before_submit (lote 4b, spec 04 §4)
# ---------------------------------------------------------------------------


def before_submit(doc: Document, method: str | None = None) -> None:
	company = doc.company

	# --- early exit: una lectura indexada ---------------------------------
	if not is_verifactu_active(company):
		return

	# --- certificado de la empresa habilitado, con remedio ----------------
	require_credential(company, "emitir facturas con VeriFactu")

	# --- configuración de la compañía (una lectura) -----------------------
	conf = frappe.db.get_value(
		"Company",
		company,
		["es_verifactu_test_mode", "es_draft_series"],
		as_dict=True,
	)

	# --- cerrojo de cadena (API manual, spec 04 §12): sostiene renombre +
	#     creación del registro (on_submit) en UNA sección crítica. Si este
	#     handler revienta, se libera ANTES de re-lanzar. -------------------
	lock = acquire_chain_lock(company)
	doc.flags[FLAG_CHAIN_LOCK] = lock
	try:
		# --- snapshot del modo operativo, congelado por factura (§2.3) ------
		doc.es_verifactu_mode = (
			VERIFACTU_TEST_MODE if conf.es_verifactu_test_mode == "Pruebas" else VERIFACTU_MODE
		)

		# --- posting_date: mantener (hoy), sin retrodatación ---------------
		doc.posting_date = frappe.utils.today()

		# --- GUARD: solo renombramos NOMBRES DE BORRADOR nuestros -----------
		if not _is_draft(doc.name, conf.es_draft_series):
			return

		series = _fiscal_series(company, doc.get("es_invoice_type"))

		new_name = make_autoname(series)
		frappe.rename_doc(
			doctype="Sales Invoice",
			old=doc.name,
			new=new_name,
			force=True,
			show_alert=False,
			rebuild_search=False,
		)
		# rename_doc devuelve el (posible) nombre validado; doc.name pasa a
		# ser el fiscal y los hijos en MEMORIA se re-padrean al nuevo nombre
		# (en DB rename_doc ya los actualizó).
		doc.name = new_name
		doc.set_parent_in_children()
	except BaseException:
		# before_submit revienta → on_submit jamás correrá: el cerrojo se
		# libera AQUÍ (no puede esperar al finally de on_submit).
		doc.flags[FLAG_CHAIN_LOCK] = None
		release_chain_lock(lock)
		raise


# ---------------------------------------------------------------------------
# identidad SIF (Sistema Informático de Facturación)
# ---------------------------------------------------------------------------

# Campos de ES Settings con la identidad SIF certificada por el productor
# del software (spec 04 §2): JAMÁS hardcode (el defecto documentado de la
# referencia, que llevaba los valores de su productor incrustados).
SIF_FIELDS = (
	"sif_nombre_razon",
	"sif_nif",
	"sif_nombre_sistema_informatico",
	"sif_id_sistema_informatico",
	"sif_version",
)

# Flags L4 del bloque SistemaInformatico: CONSTANTES de la declaración de
# certificación del SIF (parte del alta del sistema ante la AEAT), no
# configurables por site.
FLAG_SIF_SOLO_VERIFACTU = "S"
FLAG_SIF_MULTI_OT = "N"
FLAG_SIF_MULTIPLES_OT = "N"


def get_sif_data(company: str) -> dict:
	"""Bloque SistemaInformatico del RegistroFactura (alta Y anulación).

	Identidad SIF de ES Settings (NombreRazon/NIF del productor, Nombre/
	IdSistemaInformatico/Version del software) + NumeroInstalacion de la
	Company (NOI derivado, spec 04 §2.1) + los tres flags L4 constantes. ES
	Settings incompleto BLOQUEA con remedio: el bloque es obligatorio en el
	WSDL y la AEAT rechazaría el registro entero."""
	sif = frappe._dict({field: frappe.db.get_single_value("ES Settings", field) for field in SIF_FIELDS})
	missing = [campo for campo in SIF_FIELDS if not (getattr(sif, campo, None) or "").strip()]
	if missing:
		frappe.throw(
			f"La identidad SIF de ES Settings está incompleta (campos vacíos:"
			f" {', '.join(missing)}): el bloque SistemaInformatico es obligatorio"
			" en el RegistroFactura de VeriFactu y la AEAT rechazaría el"
			" registro entero. Remedio: complete la identidad SIF en ES Settings"
			" (sección VeriFactu: razón social y NIF del productor, nombre, ID"
			" y versión del sistema informático) y reintente la emisión.",
			frappe.ValidationError,
		)
	# Facets del XSD (SuministroInformacion.xsd, verificado EN VIVO — la AEAT
	# rechazó con código 1100 «Valor o tipo incorrecto del campo» un id de 8
	# caracteres): zeep NO valida maxLength client-side, la compuerta es NUESTRA.
	SIF_LIMITS = {
		"IdSistemaInformatico": (
			sif.sif_id_sistema_informatico.strip(),
			2,
			"el ID del sistema informático es un código de hasta 2 caracteres"
			" (TextMax2Type; en el entorno de pruebas el valor verificado es"
			" «01»)",
		),
		"NombreRazon": (sif.sif_nombre_razon.strip(), 120, None),
		"NombreSistemaInformatico": (sif.sif_nombre_sistema_informatico.strip(), 30, None),
		"Version": (sif.sif_version.strip(), 50, None),
	}
	for campo, (valor, limite, nota) in SIF_LIMITS.items():
		if len(valor) > limite:
			detalle = f" {nota}." if nota else ""
			frappe.throw(
				f"El campo SIF «{campo}» supera el máximo de {limite} caracteres"
				f" del WSDL de la AEAT (valor actual: «{valor}»,"
				f" {len(valor)} caracteres).{detalle} Remedio: corrija el valor en"
				" ES Settings (sección VeriFactu) y reintente la emisión — la"
				" AEAT rechazaría el registro entero (código 1100).",
				frappe.ValidationError,
			)
	return {
		"NombreRazon": sif.sif_nombre_razon.strip(),
		"NIF": sif.sif_nif.strip(),
		"NombreSistemaInformatico": sif.sif_nombre_sistema_informatico.strip(),
		"IdSistemaInformatico": sif.sif_id_sistema_informatico.strip(),
		"Version": sif.sif_version.strip(),
		"NumeroInstalacion": frappe.db.get_value("Company", company, "es_verifactu_noi"),
		"TipoUsoPosibleSoloVerifactu": FLAG_SIF_SOLO_VERIFACTU,
		"TipoUsoPosibleMultiOT": FLAG_SIF_MULTI_OT,
		"IndicadorMultiplesOT": FLAG_SIF_MULTIPLES_OT,
	}


# ---------------------------------------------------------------------------
# on_submit (lote 4c, spec 04 §5): RegistroAlta encadenado
# ---------------------------------------------------------------------------


def on_submit(doc: Document, method: str | None = None) -> None:
	# El cerrojo se recoge PRIMERO (puro bookkeeping: nunca revienta) para que
	# el finally lo libere también si el seam de test revienta.
	lock = doc.flags.pop(FLAG_CHAIN_LOCK, None)
	try:
		# --- seam de test de rollback (lote 4b): PRIMER efecto --------------
		if frappe.flags.get(FLAG_TEST_FAIL_SUBMIT):
			frappe.throw(
				"es_test_fail_submit: fallo simulado DESPUÉS del renombre (seam de"
				" test del lote 4b para verificar que el rollback libera el número"
				" fiscal).",
				frappe.ValidationError,
			)

		company = doc.company

		# --- early exit: una lectura indexada -------------------------------
		if not is_verifactu_active(company):
			return

		# --- RegistroAlta encadenado (DENTRO del cerrojo, spec 04 §5/§12) ---
		_register_issuance(doc)

		# --- estado denormalizado de la factura (spec 04 §3) -----------------
		# db_update() del _save corre ANTES de on_submit (document.py:608-612):
		# una simple asignación de campo aquí NO se persiste. Se fija el valor
		# en el doc (consistencia de la instancia en memoria) y se persiste
		# explícitamente en la MISMA transacción del submit (se revierte si el
		# submit revienta).
		doc.es_verifactu_status = INVOICE_STATUS_PENDING_SEND
		frappe.db.set_value(
			"Sales Invoice",
			doc.name,
			"es_verifactu_status",
			INVOICE_STATUS_PENDING_SEND,
			update_modified=False,
		)

		# --- remisión Inmediata: NUNCA antes del commit del submit ----------
		if frappe.db.get_value("Company", company, "es_verifactu_remission_mode") == IMMEDIATE_REMISSION:
			frappe.enqueue(TASK_SEND_PENDING, enqueue_after_commit=True, company=company)
	finally:
		if lock is not None:
			release_chain_lock(lock)


def _register_issuance(doc: Document, flags: dict | None = None) -> str:
	"""Crea el RegistroAlta (adaptador PURO) y lo persiste en el libro
	encadenado a la última huella de la compañía (spec 04 §5). Los
	`flags` (lote 5b) añaden los flags de subsanación/rechazo previo/
	sin registro previo del REEMISIÓN (reintento/subsanación): el registro
	original JAMÁS se edita.

	Interior COMPLETO (fix del drenaje en vivo, spec 04 §2.2 «exactamente lo
	remitido»): identidad del emisor/destinatario, DescripcionOperacion,
	SistemaInformatico y los flags Subsanacion/RechazoPrevio/
	SinRegistroPrevio viajan en el record_json — la HUELLA no los incluye
	(cadena canónica congelada)."""
	company = doc.company
	last = _last_record(company)
	previous_hash = (last.hash or "") if last else ""
	flags = flags or {}
	conf = frappe.db.get_value("Company", company, ["tax_id", "company_name"], as_dict=True)

	breakdown = data_adapter.get_spain_tax_breakup(doc)
	total_tax, total_amount = data_adapter.invoice_totals(doc, breakdown)
	data = {
		"issuer_nif": conf.tax_id,
		"series_number": doc.name,
		"issue_date": doc.posting_date,
		"invoice_type_code": doc.get("es_invoice_type"),
		"tax_breakdown": breakdown,
		"total_tax": total_tax,
		"total_amount": total_amount,
		"previous_hash": previous_hash,
		"generation_timestamp": format_aeat_datetime(),
		"issuer_name": conf.company_name,
		"operation_description": f"Factura {doc.name} por cantidad {doc.get('base_total')}",
		"correction": "S" if flags else "N",
		"prior_rejection": _issuance_prior_rejection(doc, flags),
		# no_prior_record NO va aquí: campo exclusivo del tipo ANULACIÓN
		"recipient": _recipient(doc),
		"sif_info": get_sif_data(company),
	}
	rectified = _rectified_invoices(doc)
	if rectified:
		data["rectified_invoices"] = rectified

	registro = data_adapter.build_issuance_record(data)
	return _persist_record(doc, "RegistroAlta", registro, previous_hash, last, flags or None)


def _recipient(doc: Document) -> dict | None:
	"""Destinatario del RegistroAlta (IDDestinatario): el cliente de la
	factura con su denominación fiscal y NIF (misma resolución de tax_id
	que la compuerta de NIFs). None sin cliente o en venta POS (tickets
	simplificados «a nombre de contado»): la referencia emite el bloque
	Destinatarios ausente."""
	if doc.get("is_pos") or not doc.get("customer"):
		return None
	tax_id = (doc.get("tax_id") or "").strip() or (
		frappe.db.get_value("Customer", doc.customer, "tax_id") or ""
	).strip()
	return {"NombreRazon": doc.get("customer_name"), "NIF": tax_id or None}


def _issuance_prior_rejection(doc: Document, flags: dict) -> str:
	"""Valor wire de RechazoPrevio del alta (semántica de la referencia):
	'N' sin rechazo previo; en reemisión de un rechazo, 'S' si algún
	registro previo de la factura SÍ está en la AEAT
	(Correcto/AceptadoConErrores) y 'X' si todas las tentativas fueron
	rechazadas."""
	if not flags.get("prior_rejection"):
		return "N"
	in_aeat = bool(
		frappe.db.exists(
			LEDGER_DOCTYPE,
			{
				"sales_invoice": doc.name,
				"status": ("in", ("Correcto", "AceptadoConErrores")),
			},
		)
	)
	return "S" if in_aeat else "X"


def regenerate_issuance(
	invoice: str,
	*,
	correction: bool = False,
	prior_rejection: bool = False,
) -> str:
	"""Reemite el RegistroAlta de una factura YA emitida desde su estado
	ACTUAL (lote 5b, spec 04 §3/§9): reintento automático tras rechazo
	(`prior_rejection`), subsanación automática/manual (`correction`) — el
	dato correcto sale de la factura como si fuera un alta nueva.

	BAJO EL CERROJO de cadena (spec 04 §12, mismo patrón que before_cancel):
	lee la última huella del SIF y encadena el registro NUEVO — el registro
	original queda INTACTO (libro inmutable). Devuelve el docname del
	registro creado. NO toca el estado denormalizado de la factura: cada
	estrategia decide (el reintento la deja como estaba — seguía «Pendiente
	Envío»; la subsanación manual la devuelve a «Pendiente Envío» desde
	rectify()).
	"""
	doc = frappe.get_doc("Sales Invoice", invoice)
	lock = acquire_chain_lock(doc.company)
	try:
		flags = {
			flag: 1
			for flag, activo in (
				("is_correction", correction),
				("prior_rejection", prior_rejection),
			)
			if activo
		}
		return _register_issuance(doc, flags or None)
	finally:
		release_chain_lock(lock)


# ---------------------------------------------------------------------------
# validate (lote 4c, spec 04 §4.2): compuertas de la factura
# ---------------------------------------------------------------------------


def validate(doc: Document, method: str | None = None) -> None:
	company = doc.company

	# --- early exit: una lectura indexada ---------------------------------
	if not is_verifactu_active(company):
		return

	_block_amendment(doc)
	_validate_tax_breakdown(doc)
	_validate_simplified(doc)
	_validate_tax_ids(doc)
	_validate_rectification(doc)
	_require_invoice_type(doc)


def _block_amendment(doc: Document) -> None:
	"""Amend bloqueado (spec 04 §4): el amend rompería la correspondencia
	factura ↔ registro ↔ libro; la corrección en España es SIEMPRE
	rectificativa."""
	if doc.get("amended_from"):
		frappe.throw(
			f"No se permite «amend» de la factura {doc.amended_from}: VeriFactu"
			" exige trazabilidad de la cadena (factura → registro Alta → libro)"
			" y una factura amendada duplicaría la identidad de la original ya"
			" registrada (spec 04 §4). Remedio: ANULE la factura original (su"
			" cancelación genera el RegistroAnulación) y emita una rectificativa"
			" (tipo R1–R5) enlazada con «Devolver contra» o con el trío de"
			" rectificada externa.",
			frappe.ValidationError,
		)


def _validate_tax_breakdown(doc: Document) -> None:
	"""Desglose fiscal o causa de exención (spec 04 §4/§7): el RegistroAlta
	exige DetalleDesglose o la causa L10; una factura sin ninguno de los dos
	rebotaría en la AEAT."""
	try:
		rows = data_adapter.get_spain_tax_breakup(doc)
	except ValueError as exc:
		frappe.throw(
			f"La factura {doc.name} no permite construir el desglose fiscal AEAT:"
			f" {exc} Remedio: use plantillas de impuestos con la convención de"
			" descripción «IVA - 21» (spec 04 §7) o, si la operación es especial,"
			" complete el desglose real en el módulo de impuestos y deje aquí los"
			" escape hatches fiscales.",
			frappe.ValidationError,
		)
		return

	if not rows and not doc.get("es_verifactu_exempt_cause"):
		frappe.throw(
			f"La factura {doc.name} no tiene desglose fiscal (impuestos españoles)"
			" ni causa de exención: el RegistroAlta de VeriFactu exige el"
			" Desglose (DetalleDesglose) o la causa de exención L10 (spec 04"
			" §4/§7). Remedio: añada los impuestos correspondientes a la factura"
			" (plantilla «IVA - 21») o seleccione la causa de exención en la"
			" sección VeriFactu de la factura.",
			frappe.ValidationError,
		)


def _validate_simplified(doc: Document) -> None:
	"""Coherencia simplificada ↔ POS (spec 04 §4): los tipos simplificados
	(F2/R5, flag «is_simplified» del catálogo) solo se emiten por caja
	(is_pos). La referencia no codifica la inversa (POS con tipo ordinario):
	aquí se espeja exactamente eso."""
	invoice_type = doc.get("es_invoice_type")
	if not invoice_type:
		return  # lo reporta _require_invoice_type
	if not frappe.db.get_value("ES Invoice Type", invoice_type, "is_simplified"):
		return
	if not doc.get("is_pos"):
		frappe.throw(
			f"La factura {doc.name} es de tipo simplificado («{invoice_type}»: F2/R5)"
			" pero no es una venta POS: los tickets simplificados solo pueden"
			" emitirse por caja, coherencia tipo↔POS del spec 04 §4. Remedio:"
			" márquela como venta POS (is_pos) con su forma de pago, o cambie el"
			" tipo de factura a F1 (ordinaria).",
			frappe.ValidationError,
		)


def _validate_tax_ids(doc: Document) -> None:
	"""Última compuerta NIF (spec 04 §4.2 + spec 14 §2): emisor SIEMPRE
	presente y válido; destinatario presente y válido cuando es español
	(patrón de NIF o país España — mismo criterio que nif/party.py). Los
	tickets POS van a nombre de «contado»: sin compuerta de destinatario
	(tabla de spec 14 §2, fila no-POS)."""
	issuer_nif = (frappe.db.get_value("Company", doc.company, "tax_id") or "").strip()
	if not issuer_nif:
		frappe.throw(
			f"La compañía emisora {doc.company} no tiene NIF: el RegistroAlta"
			" exige el IDEmisorFactura y la AEAT rechazaría el envío (spec 04"
			" §4.2). Remedio: fije el NIF de la compañía en su ficha (el campo"
			" «Tax ID»)",
			frappe.ValidationError,
		)
	try:
		validator.validate_spanish_tax_id(issuer_nif)
	except validator.InvalidTaxID as exc:
		frappe.throw(
			f"El NIF del emisor ({doc.company}) «{issuer_nif}» no es válido: {exc}"
			" Remedio: corrija el NIF en la ficha de la compañía y reintente.",
			frappe.ValidationError,
		)

	if doc.get("is_pos"):
		return

	customer_nif = (doc.get("tax_id") or "").strip() or (
		frappe.db.get_value("Customer", doc.customer, "tax_id") or ""
	).strip()

	if not (validator.looks_spanish(customer_nif) or _customer_country(doc) == "Spain"):
		return

	if not customer_nif:
		frappe.throw(
			f"El cliente {doc.customer} de la factura {doc.name} es español y no"
			" tiene NIF: el RegistroAlta exige el destinatario y la AEAT"
			" rechazaría el envío (spec 04 §4.2, spec 14 §2). Remedio: fije el"
			" NIF del cliente en su ficha (pestaña «Tax ID») y reintente.",
			frappe.ValidationError,
		)
	try:
		validator.validate_spanish_tax_id(customer_nif)
	except validator.InvalidTaxID as exc:
		frappe.throw(
			f"El NIF del cliente {doc.customer} «{customer_nif}» de la factura"
			f" {doc.name} no es válido: {exc} Remedio: corrija el NIF en la"
			" ficha del cliente (la sugerencia de letra/dígito de control la"
			" da el propio mensaje) y reintente.",
			frappe.ValidationError,
		)


def _customer_country(doc: Document) -> str | None:
	"""País del cliente (patrón de nif/party.py): Customer no lleva columna
	país (verificado en v16) — se resuelve por su dirección principal."""
	from frappe.contacts.doctype.address.address import get_default_address

	address = get_default_address("Customer", doc.customer)
	if not address:
		return None
	return frappe.db.get_value("Address", address, "country")


def _validate_rectification(doc: Document) -> None:
	"""Reglas de rectificativa (spec 04 §6): original aceptada, una sola
	rectificativa pendiente/errónea por original, o trío de rectificada
	externa completo."""
	invoice_type = doc.get("es_invoice_type") or ""
	if not invoice_type.startswith("R"):
		return

	original = doc.get("return_against")
	if original:
		status = frappe.db.get_value("Sales Invoice", original, "es_verifactu_status") or ""
		if status != INVOICE_STATUS_ISSUANCE_ACCEPTED:
			frappe.throw(
				f"La factura rectificativa {doc.name} enlaza a {original}, que está"
				f" en estado VeriFactu «{status or 'sin estado'}»: solo se rectifica"
				" una factura cuyo alta esté en estado"
				f" «{INVOICE_STATUS_ISSUANCE_ACCEPTED}» por la AEAT (spec 04 §6)."
				" Remedio: espere a que la AEAT procese el alta de la original (o"
				" subsánela si fue rechazada) antes de emitir la rectificativa.",
				frappe.ValidationError,
			)

		# Una rectificativa a la vez: otra R* sobre la MISMA original con
		# registro pendiente/erróneo bloquea (las rectificativas enlazan al
		# libro por su PROPIA factura, por eso la búsqueda es en dos pasos).
		others = frappe.get_all(
			"Sales Invoice",
			filters={
				"return_against": original,
				"name": ("!=", doc.name),
				"es_invoice_type": ("like", "R%"),
			},
			pluck="name",
		)
		if others and frappe.db.exists(
			LEDGER_DOCTYPE,
			{
				"sales_invoice": ("in", others),
				"invoice_type": ("like", "R%"),
				"status": ("in", (PENDING_SEND_STATE, "Incorrecto")),
			},
		):
			frappe.throw(
				f"Ya existe otra rectificativa pendiente o errónea sobre {original}:"
				" el libro admite UNA rectificativa en curso por factura original"
				" (spec 04 §6) — una segunda competiría por el mismo hueco antes"
				" de conocer el resultado de la AEAT. Remedio: espere a que la"
				" AEAT acepte la rectificativa en curso (o subsánela si fue"
				" rechazada) y reintente.",
				frappe.ValidationError,
			)
		return

	trio = (
		doc.get("es_external_rectified_nif"),
		doc.get("es_external_rectified_number"),
		doc.get("es_external_rectified_date"),
	)
	if not all(trio):
		frappe.throw(
			f"La factura {doc.name} es rectificativa (tipo «{invoice_type}») pero no"
			" enlaza ninguna factura rectificada: ni «Devolver contra» ni el"
			" trío de rectificada externa están completos (spec 04 §6)."
			" Remedio: enlácela a la original con «Devolver contra», o complete"
			" NIF + número + fecha de la rectificada externa en la sección"
			" VeriFactu de la factura.",
			frappe.ValidationError,
		)


def _require_invoice_type(doc: Document) -> None:
	"""Requerimiento condicional del tipo (Batch 3, spec 04 §2.3): obligatorio
	al validar si la compañía está activa (la emisión lo necesita para la serie
	y el RegistroAlta)."""
	if not doc.get("es_invoice_type"):
		frappe.throw(
			f"{doc.company} emite con VeriFactu pero la factura {doc.name} no"
			" indica tipo de factura: sin él no se puede resolver la serie"
			" fiscal ni el TipoFactura del RegistroAlta (spec 04 §2.3/§4)."
			" Remedio: fije el campo «Tipo de factura» (VeriFactu) en la"
			" sección VeriFactu de la factura.",
			frappe.ValidationError,
		)


# ---------------------------------------------------------------------------
# before_cancel (lote 4c, spec 04 §6): RegistroAnulación encadenado
# ---------------------------------------------------------------------------


def before_cancel(doc: Document, method: str | None = None) -> None:
	# Compuerta = SNAPSHOT de modo de la FACTURA (spec 04 §6): una factura
	# emitida en modo VeriFactu SIEMPRE requiere su RegistroAnulación para
	# cancelarse, aunque la compañía se haya desactivado después (el libro es
	# historia legal). Sin snapshot (o «Sin SIF») no hay nada que hacer.
	mode = doc.get("es_verifactu_mode") or ""
	if mode not in (VERIFACTU_MODE, VERIFACTU_TEST_MODE):
		return

	status = (doc.get("es_verifactu_status") or "").strip()
	if status != INVOICE_STATUS_ISSUANCE_ACCEPTED:
		frappe.throw(
			f"La factura {doc.name} está en estado VeriFactu «{status or 'sin'}»"
			" y solo puede anularse si su alta fue aceptada («Alta Aceptada»):"
			" el alta pendiente/errónea se corrige por SUBSANACIÓN, no"
			" cancelando la factura (spec 04 §6). Remedio: espere a que la AEAT"
			" procese el alta (o subsánela si fue rechazada) y después anule la"
			" factura, que generará su RegistroAnulación.",
			frappe.ValidationError,
		)

	lock = acquire_chain_lock(doc.company)
	try:
		_register_cancellation(doc)
		doc.es_verifactu_status = INVOICE_STATUS_CANCELLED
	finally:
		release_chain_lock(lock)


def _register_cancellation(doc: Document) -> None:
	"""Crea el RegistroAnulación (adaptador PURO) encadenado a la última
	huella de la compañía (spec 04 §5/§6).

	Interior completo de la anulación (fix del drenaje en vivo): flags
	RechazoPrevio/SinRegistroPrevio "N" (solo se anulan altas aceptadas,
	semántica de la referencia) + bloque SistemaInformatico — SIN
	NombreRazonEmisor/Destinatarios/Desglose/montos."""
	company = doc.company
	last = _last_record(company)
	previous_hash = (last.hash or "") if last else ""

	registro = data_adapter.build_cancellation_record(
		{
			"issuer_nif": frappe.db.get_value("Company", company, "tax_id"),
			"series_number": doc.name,
			"issue_date": doc.posting_date,
			"previous_hash": previous_hash,
			"generation_timestamp": format_aeat_datetime(),
			"prior_rejection": "N",
			"no_prior_record": "N",
			"sif_info": get_sif_data(company),
		}
	)
	_persist_record(doc, "RegistroAnulacion", registro, previous_hash, last)


# ---------------------------------------------------------------------------
# helpers del libro
# ---------------------------------------------------------------------------


def _last_record(company: str):
	"""Último registro de la cadena de la empresa (Altas Y anulaciones, spec
	04 §5): cadena_index DESC / creation DESC; solo registros COMPLETOS
	(record_json persistido — guard de transacción en vuelo de la referencia).

	Lectura FOR UPDATE (ORM qb, mismo patrón que naming.py:412): el cerrojo
	de archivo serializa la sección crítica, pero se libera en el finally de
	on_submit ANTES del commit de la petición; sin esta lectura de bloqueo,
	una emisión contigua vería un snapshot sin el registro aún no
	comprometido y ENCADENARÍA SOBRE UNA HUELLA ANTIGUA (horquilla en la
	cadena). El FOR UPDATE espera los row-locks de la emisión en curso y lee
	el estado YA COMPROMETIDO.
	"""
	ledger = frappe.qb.DocType(LEDGER_DOCTYPE)
	rows = (
		frappe.qb.from_(ledger)
		.select(ledger.name, ledger.chain_index, ledger.hash)
		.where((ledger.company == company) & (ledger.record_json.isnotnull()))
		.orderby(ledger.chain_index, order=frappe.qb.desc)
		.orderby(ledger.creation, order=frappe.qb.desc)
		.limit(1)
		.for_update()
		.run(as_dict=True)
	)
	return rows[0] if rows else None


def _persist_record(
	doc: Document,
	record_type: str,
	registro: dict,
	previous_hash: str,
	last,
	flags: dict | None = None,
) -> str:
	"""Persiste el registro en el libro (spec 04 §2.2): record_json es la
	fuente de verdad; nace en PendienteEnvio; chain_index consecutivo
	(base 1, como los tests del libro). Los `flags` (lote 5b) son los
	flags de reemisión (subsanación/rechazo previo/sin registro previo).
	Devuelve el docname del registro creado."""
	record_doc = frappe.get_doc(
		{
			"doctype": LEDGER_DOCTYPE,
			"company": doc.company,
			"sales_invoice": doc.name,
			"record_type": record_type,
			"invoice_type": doc.get("es_invoice_type"),
			"chain_index": (last.chain_index or 0) + 1 if last else 1,
			"record_json": json.dumps(registro, ensure_ascii=False, default=str),
			"hash": registro["Huella"],
			"previous_hash": previous_hash,
			"status": PENDING_SEND_STATE,
			**(flags or {}),
		}
	)
	record_doc.insert(ignore_permissions=True)
	return record_doc.name


def _rectified_invoices(doc: Document) -> list[dict] | None:
	"""FacturasRectificadas del RegistroAlta (spec 04 §6): interna (los datos
	de la original enlazada) o externa (el trío de campos)."""
	invoice_type = doc.get("es_invoice_type") or ""
	if not invoice_type.startswith("R"):
		return None

	if doc.get("return_against"):
		original = frappe.db.get_value(
			"Sales Invoice",
			doc.return_against,
			["name", "posting_date"],
			as_dict=True,
		)
		return [
			{
				"issuer_nif": frappe.db.get_value("Company", doc.company, "tax_id"),
				"series_number": original.name,
				"issue_date": original.posting_date,
			}
		]

	return [
		{
			"issuer_nif": doc.get("es_external_rectified_nif"),
			"series_number": doc.get("es_external_rectified_number"),
			"issue_date": doc.get("es_external_rectified_date"),
		}
	]


# ---------------------------------------------------------------------------
# helpers de naming (lote 4b, spec 04 §4)
# ---------------------------------------------------------------------------


def _is_draft(name: str | None, draft_pattern: str | None) -> bool:
	"""¿El nombre actual es un borrador NUESTRO? Ver invoice.is_draft_name."""
	return is_draft_name(name, draft_pattern)


def _fiscal_series(company: str, invoice_type: str | None) -> str:
	"""Resuelve la serie fiscal por el mapeo tipo→serie de la compañía
	(child table es_invoice_series). Sin mapeo no hay emisión: throw con
	remedio (configure el mapeo en la ficha de la compañía)."""
	if not invoice_type:
		frappe.throw(
			f"{company} emite con VeriFactu pero la factura no indica tipo de"
			" factura: sin él no se puede resolver la serie fiscal (spec 04"
			" §2.3). Remedio: fije el campo «Tipo de factura» (VeriFactu) de la"
			" factura y reintente el submit.",
			frappe.ValidationError,
		)

	series = frappe.db.get_value(
		"ES Invoice Series",
		{"parent": company, "parenttype": "Company", "invoice_type": invoice_type},
		"series",
	)

	if not series:
		frappe.throw(
			f"No hay serie mapeada para el tipo de factura «{invoice_type}» en"
			f" {company}: el renombre a la serie fiscal es el paso que consume"
			" el número legal de la factura (spec 04 §4). Remedio: configure el"
			f" mapeo serie↔tipo para «{invoice_type}» en la ficha de la"
			f" compañía {company} (sección VeriFactu, «Series por tipo de"
			" factura») y reintente el submit.",
			frappe.ValidationError,
		)

	return series
