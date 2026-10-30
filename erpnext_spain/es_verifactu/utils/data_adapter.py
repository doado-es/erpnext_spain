# Adaptador PURO de datos VeriFactu (lote 4a, spec 04 §7): capa sin frappe,
# solo stdlib. Las funciones de huella y construcción de registros son la única
# fuente de verdad del ALGORITMO; el wiring (doc_events, encadenamiento con DB,
# serialización del payload SOAP) llega en el lote siguiente.
#
# FORMATO DE MONTOS (decisión byte-exacta verificada contra la referencia
# `spanish_compliance/verifactu/aeat_lib/aeat_data_adapter.py`, validada en el
# entorno de pruebas de la AEAT): CuotaTotal e ImporteTotal NO se reformatean —
# llegan como float de campo Currency de ERPNext (`invoice_dt.as_dict()`) y la
# huella usa `str()` de ese float. Es decir 1210.0 -> "1210.0", 0.5 -> "0.5",
# 211.05 -> "211.05": PUNTO decimal, sin coma española, sin ceros de relleno
# («%.2f» NO). Los registros guardan el float tal cual (json.dumps lo serializa
# nativamente y zeep lo convierte a xsd:decimal). Este módulo normaliza entradas
# Decimal/str convirtiéndolas al mismo `str(float)`.
#
# Nombres de campo de DetalleDesglose: los EXACTOS de la referencia (verificados
# contra AEAT): BaseImponibleOimporteNoSujeto y CuotaRepercutida — NO
# «BaseImponible»/«Cuota» del lenguaje coloquial del spec.

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

# Código de impuesto AEAT (L7) del DetalleDesglose: hoy solo IVA.
AEAT_TAX_CODES = {"IVA": "01"}

# L8A: régimen general. L9: sujeta y no exenta.
DEFAULT_REGIME_KEY = "01"
CLASSIFICATION_TAXABLE = "S1"

# L12: huella SHA-256. L15: versión del esquema.
HASH_TYPE_SHA256 = "01"
ID_VERSION = "1.0"

# Mapping TipoRectificativa de la referencia (get_rectification_type):
# «Corrections are always communicated by difference» — todo R1..R5 va como
# "I" (por diferencias); jamás "S". La referencia solo codifica R1/R4/R5; R2/R3
# se completan aquí coherente con su docstring y con el catálogo local
# (catalog.py ya trae R1..R5 -> "I" en el doctype ES Invoice Type).
RECTIFICATION_TYPES_BY_DIFFERENCE = frozenset({"R1", "R2", "R3", "R4", "R5"})


def _format_amount(value) -> str:
	"""Monto tal como entra a la cadena de huella: `str()` del float ERPNext.

	str pasa tal cual (asume formato AEAT ya correcto); numéricos (float/Decimal/
	int) se normalizan por `float()` para reproducir el formato de la referencia:
	1210.0 -> "1210.0", 0.5 -> "0.5", Decimal("1210.00") -> "1210.0".
	"""
	if isinstance(value, str):
		return value
	return str(float(value))


# str ISO-8601 de fecha (YYYY-MM-DD): el formato en que frappe entrega los
# Date en memoria (p. ej. doc.posting_date tras una asignación) y en el que
# llegan de la capa frappe-facing. NO colisiona con dd-mm-aaaa (guiones en
# otras posiciones).
ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def _format_date(value) -> str:
	"""Fecha AEAT dd-mm-aaaa. Acepta str ISO-8601 «YYYY-MM-DD» (el formato
	en que frappe entrega los Date: doc.posting_date de un doc en memoria,
	fechas leídas de BD) y la NORMALIZA al formato congelado dd-mm-aaaa —
	el registro y la cadena canónica de la huella viajan SIEMPRE con el
	mismo formato. Una str ya dd-mm-aaaa pasa tal cual; date/datetime se
	formatean. Ver aeat.utils.format_aeat_date para el punto de verdad
	frappe-facing (huso Europe/Madrid) usado por el wiring.
	"""
	if isinstance(value, str):
		if ISO_DATE_PATTERN.fullmatch(value):
			return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%m-%Y")
		return value
	if isinstance(value, datetime):
		return value.date().strftime("%d-%m-%Y")
	if isinstance(value, date):
		return value.strftime("%d-%m-%Y")
	raise TypeError(f"FechaExpedicion no soportada: {value!r}")


def _format_tax_rate(value) -> str:
	"""Tipo impositivo como string de dígitos ("21", "10.5", "100"), igual que
	la referencia (que toma el fragmento "21" del nombre de la plantilla)."""
	return f"{float(str(value).strip()):g}"


def compute_issuance_hash(record: dict) -> str:
	"""SHA-256 (hex MAYÚSCULAS) de la cadena canónica del RegistroAlta (L13).

	`record` lleva los campos AEAT planos y en "Huella" la HUELLA ANTERIOR
	de la cadena ("" para el primer registro del sistema). Cadena canónica:
	IDEmisorFactura={}&NumSerieFactura={}&FechaExpedicionFactura={}&TipoFactura={}
	&CuotaTotal={}&ImporteTotal={}&Huella={}&FechaHoraHusoGenRegistro={}
	"""
	fields = (
		("IDEmisorFactura", record.get("IDEmisorFactura", "")),
		("NumSerieFactura", record.get("NumSerieFactura", "")),
		("FechaExpedicionFactura", record.get("FechaExpedicionFactura", "")),
		("TipoFactura", record.get("TipoFactura", "")),
		("CuotaTotal", _format_amount(record.get("CuotaTotal", ""))),
		("ImporteTotal", _format_amount(record.get("ImporteTotal", ""))),
		("Huella", record.get("Huella", "")),
		("FechaHoraHusoGenRegistro", record.get("FechaHoraHusoGenRegistro", "")),
	)
	canonical = "&".join(f"{field}={value}" for field, value in fields)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def compute_cancellation_hash(record: dict) -> str:
	"""SHA-256 (hex MAYÚSCULAS) de la cadena canónica del RegistroAnulacion (L13).

	En "Huella" la huella anterior ("" para el primer registro). Cadena canónica:
	IDEmisorFacturaAnulada={}&NumSerieFacturaAnulada={}
	&FechaExpedicionFacturaAnulada={}&Huella={}&FechaHoraHusoGenRegistro={}
	"""
	fields = (
		("IDEmisorFacturaAnulada", record.get("IDEmisorFacturaAnulada", "")),
		("NumSerieFacturaAnulada", record.get("NumSerieFacturaAnulada", "")),
		("FechaExpedicionFacturaAnulada", record.get("FechaExpedicionFacturaAnulada", "")),
		("Huella", record.get("Huella", "")),
		("FechaHoraHusoGenRegistro", record.get("FechaHoraHusoGenRegistro", "")),
	)
	canonical = "&".join(f"{field}={value}" for field, value in fields)
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()


def get_rectification_type(invoice_type_code: str) -> str:
	"""R1..R5 -> "I" (rectificación por diferencias); el resto -> "".

	La referencia comunica TODAS las rectificativas por diferencia ("S" jamás
	se emite): «Corrections are always communicated by difference
	(TipoRectificativa 'I')». Tabla exacta de la referencia + catálogo local.
	"""
	if invoice_type_code in RECTIFICATION_TYPES_BY_DIFFERENCE:
		return "I"
	return ""


def build_tax_breakdown(breakup_rows: list[dict]) -> list[dict]:
	"""Agrega filas del contrato (spec 04 §7) a DetalleDesglose AEAT.

	Fila de entrada: {tax_type, tax_rate, taxable_base, tax_amount,
	operation_classification, regime_key, exemption_cause, recipients}.
	Agrega por (tax_type, tax_rate) con Decimal + ROUND_HALF_UP (igual
	que la referencia, que re-quantiza tras cada adición). Sale con los
	nombres EXACTOS del DetalleType del WSDL (SuministroInformacion.xsd):
	Impuesto, ClaveRegimen, CHOICE CalificacionOperacion | OperacionExenta
	(causa de exención L10 como valor del elemento, sin calificación junto),
	TipoImpositivo, BaseImponibleOimporteNoSujeto y CuotaRepercutida.
	`recipients` viaja a nivel de registro, no de desglose: se ignora.
	"""
	if not breakup_rows:
		return []

	CENT = Decimal("0.01")
	groups: dict[tuple[str, str], dict] = {}

	for row in breakup_rows:
		tax_type = row["tax_type"]
		if tax_type not in AEAT_TAX_CODES:
			raise ValueError(f"El impuesto '{tax_type}' no ha sido contemplado aún.")

		rate = _format_tax_rate(row["tax_rate"])
		key = (tax_type, rate)
		group = groups.get(key)
		if group is None:
			group = groups[key] = {
				"Impuesto": AEAT_TAX_CODES[tax_type],
				"TipoImpositivo": rate,
				"BaseImponibleOimporteNoSujeto": Decimal("0"),
				"CuotaRepercutida": Decimal("0"),
				"ClaveRegimen": row.get("regime_key") or DEFAULT_REGIME_KEY,
			}
			# DetalleType del WSDL (SuministroInformacion.xsd, verificado en
			# vivo): CHOICE CalificacionOperacion (S1/S2/N1/N2) | OperacionExenta
			# (simpleType E1–E8) — la causa de exención va como VALOR del
			# elemento OperacionExenta, y la calificación NUNCA viaja junto a
			# ella (el choice excluye ambos). La referencia usaba un
			# CausaExenta plano de un WSDL anterior: contra el actual reventa.
			if row.get("exemption_cause"):
				group["OperacionExenta"] = row["exemption_cause"]
			else:
				group["CalificacionOperacion"] = (
					row.get("operation_classification") or CLASSIFICATION_TAXABLE
				)

		new_base = group["BaseImponibleOimporteNoSujeto"] + Decimal(str(row["taxable_base"]))
		group["BaseImponibleOimporteNoSujeto"] = new_base.quantize(CENT, rounding=ROUND_HALF_UP)
		new_tax_amount = group["CuotaRepercutida"] + Decimal(str(row["tax_amount"]))
		group["CuotaRepercutida"] = new_tax_amount.quantize(CENT, rounding=ROUND_HALF_UP)

	return [
		{
			"Impuesto": group["Impuesto"],
			# Regla 1238 de la AEAT (verificada EN VIVO): si la operación es
			# exenta NO se informa ninguno de TipoImpositivo, CuotaRepercutida,
			# TipoRecargoEquivalencia ni CuotaRecargoEquivalencia — solo la base.
			**(
				{"TipoImpositivo": group["TipoImpositivo"]}
				if "OperacionExenta" not in group
				else {}
			),
			"BaseImponibleOimporteNoSujeto": float(group["BaseImponibleOimporteNoSujeto"]),
			**(
				{"CuotaRepercutida": float(group["CuotaRepercutida"])}
				if "OperacionExenta" not in group
				else {}
			),
			"ClaveRegimen": group["ClaveRegimen"],
			# CHOICE del DetalleType: una u otra, nunca ambas ni ninguna
			**(
				{"CalificacionOperacion": group["CalificacionOperacion"]}
				if "CalificacionOperacion" in group
				else {"OperacionExenta": group["OperacionExenta"]}
			),
		}
		for group in groups.values()
	]


def build_issuance_record(data: dict) -> dict:
	"""Construye el RegistroAlta (campos AEAT, planos) y calcula su Huella.

	`data` (dict plano):
	  issuer_nif, series_number, issue_date (date, str ISO-8601 «YYYY-MM-DD»
	  o str dd-mm-aaaa), invoice_type_code (F1..R5), rectification_type (opt:
	  si falta, se deriva de invoice_type_code), rectified_invoices (opt:
	  [{issuer_nif, series_number, issue_date}]), tax_breakdown (filas del
	  contrato, ver build_tax_breakdown), total_tax, total_amount,
	  previous_hash ("" para el primer record), generation_timestamp (str
	  ISO 8601 +01:00, ver aeat.utils.format_aeat_datetime).

	Interior COMPLETO del WSDL (fix del drenaje en vivo: a la AEAT le faltaba
	Required element NombreRazonEmisor, forma de la referencia
	aeat_data_adapter verificada contra su entorno de pruebas) — opcionales
	todas para retrocompatibilidad con el record_json del formato anterior:
	  issuer_name → NombreRazonEmisor (razón social del emisor)
	  operation_description → DescripcionOperacion (texto libre de la ref.)
	  correction → Subsanacion ("S" reemisión / "N" alta nueva)
	  prior_rejection → RechazoPrevio ("N" / "S" existe en AEAT / "X" no)
	  recipient → Destinatarios {"IDDestinatario": [{NombreRazon, NIF}]};
	    None/ausente = sin destinatario (venta POS) y la clave NO viaja
	  sif_info → SistemaInformatico (dict del SIF tal cual)

	La HUELLA NO incluye ninguna de ellas: la cadena canónica (L13) está
	CONGELADA — añadirlas al record no altera los vectores del lote 4a.
	"""
	rectification_type = data.get("rectification_type") or get_rectification_type(
		data["invoice_type_code"]
	)
	previous_hash = data.get("previous_hash") or ""

	record = {
		"IDEmisorFactura": data["issuer_nif"],
		"NumSerieFactura": data["series_number"],
		"FechaExpedicionFactura": _format_date(data["issue_date"]),
	}
	if data.get("operation_description"):
		record["DescripcionOperacion"] = data["operation_description"]
	record["TipoFactura"] = data["invoice_type_code"]
	if rectification_type:
		record["TipoRectificativa"] = rectification_type
	rectified = data.get("rectified_invoices") or []
	if rectified:
		record["FacturasRectificadas"] = {
			"IDFacturaRectificada": [
				{
					"IDEmisorFactura": rectified_invoice["issuer_nif"],
					"NumSerieFactura": rectified_invoice["series_number"],
					"FechaExpedicionFactura": _format_date(rectified_invoice["issue_date"]),
				}
				for rectified_invoice in rectified
			]
		}
	if data.get("issuer_name"):
		record["NombreRazonEmisor"] = data["issuer_name"]
	if data.get("correction"):
		record["Subsanacion"] = data["correction"]
	if data.get("prior_rejection"):
		record["RechazoPrevio"] = data["prior_rejection"]
	# SinRegistroPrevio NO viaja en el Alta: es campo del tipo ANULACIÓN
	# (RegistroFacturacionBajaType) — el WSDL lo rechaza (verificado en vivo).
	recipient = data.get("recipient")
	if recipient:
		record["Destinatarios"] = {"IDDestinatario": [dict(recipient)]}
	record["Desglose"] = {"DetalleDesglose": build_tax_breakdown(data.get("tax_breakdown") or [])}
	record["CuotaTotal"] = float(data["total_tax"])
	record["ImporteTotal"] = float(data["total_amount"])
	if data.get("sif_info"):
		record["SistemaInformatico"] = data["sif_info"]
	record["Huella"] = previous_hash
	record["FechaHoraHusoGenRegistro"] = data["generation_timestamp"]
	record["TipoHuella"] = HASH_TYPE_SHA256
	record["IDVersion"] = ID_VERSION
	record["PrimerRegistro"] = "N" if previous_hash else "S"

	record["Huella"] = compute_issuance_hash(record)
	return record


def build_cancellation_record(data: dict) -> dict:
	"""Construye el RegistroAnulacion (campos AEAT, planos) y su Huella.

	Mismas claves de entrada que build_issuance_record (solo usa issuer_nif,
	series_number, issue_date, previous_hash, generation_timestamp) más,
	del interior COMPLETO del WSDL (fix del drenaje en vivo): prior_rejection
	→ RechazoPrevio ("N" sin rechazo previo / "S" última tentativa
	rechazada), no_prior_record → SinRegistroPrevio ("N" siempre) y
	sif_info → SistemaInformatico — opcionales por
	retrocompatibilidad. La anulación NO lleva NombreRazonEmisor/
	Destinatarios/Desglose/montos: semántica distinta del alta.
	"""
	previous_hash = data.get("previous_hash") or ""

	record = {
		"IDEmisorFacturaAnulada": data["issuer_nif"],
		"NumSerieFacturaAnulada": data["series_number"],
		"FechaExpedicionFacturaAnulada": _format_date(data["issue_date"]),
	}
	if data.get("prior_rejection"):
		record["RechazoPrevio"] = data["prior_rejection"]
	if data.get("no_prior_record"):
		record["SinRegistroPrevio"] = data["no_prior_record"]
	if data.get("sif_info"):
		record["SistemaInformatico"] = data["sif_info"]
	record["Huella"] = previous_hash
	record["FechaHoraHusoGenRegistro"] = data["generation_timestamp"]
	record["TipoHuella"] = HASH_TYPE_SHA256
	record["IDVersion"] = ID_VERSION
	record["PrimerRegistro"] = "N" if previous_hash else "S"

	record["Huella"] = compute_cancellation_hash(record)
	return record


def get_spain_tax_breakup(invoice) -> list[dict]:
	"""STUB — CONTRATO 07 (reemplazable): heurística de lectura de `invoice.taxes`.

	Produce las filas del contrato de spec 04 §7 (consumidas por
	build_tax_breakdown): {tax_type, tax_rate, taxable_base, tax_amount,
	operation_classification, regime_key, exemption_cause, recipients}.
	Duck-typed: solo toca `.taxes` (+ escape hatches de la factura
	`es_verifactu_exempt_cause` y `es_verifactu_regime_key` si están).
	Parsea descripciones «IVA - 21» (patrón de la referencia, clave del
	itemised breakup = tax.description). El spec 07 es dueño de la
	implementación real (exentas, IRPF, recargos, multi-fila, monedas).
	"""
	rows = []
	for row in invoice.taxes:
		description = getattr(row, "description", None) or ""
		tax_name, _, rate_in_description = description.partition(" - ")
		tax_name = tax_name.strip()
		rate = rate_in_description.strip()
		if not tax_name or not rate:
			raise ValueError(
				f"No se pudo interpretar el impuesto de la descripción '{description}' "
				"(patrón esperado: 'IVA - 21')."
			)
		if tax_name not in AEAT_TAX_CODES:
			raise ValueError(f"El impuesto '{tax_name}' no ha sido contemplado aún.")

		base = float(getattr(row, "net_amount", None) or 0)
		tax_amount = float(getattr(row, "tax_amount", None) or 0)
		if not base and not tax_amount:
			continue

		exemption_cause = getattr(invoice, "es_verifactu_exempt_cause", None) or None
		regime_key = getattr(invoice, "es_verifactu_regime_key", None) or DEFAULT_REGIME_KEY
		rows.append(
			{
				"tax_type": tax_name,
				"tax_rate": rate,
				"taxable_base": base,
				"tax_amount": tax_amount,
				"operation_classification": "S2" if exemption_cause else CLASSIFICATION_TAXABLE,
				"regime_key": regime_key,
				"exemption_cause": exemption_cause,
				"recipients": None,
			}
		)

	# Operación exenta (L10): sin filas de impuesto pero con causa de
	# exención → UNA fila sintética S2 con la base íntegra. El WSDL exige
	# ≥1 DetalleDesglose SIEMPRE (minOccurs=1, verificado en vivo contra
	# SuministroInformacion.xsd) — el TODO de OperacionExenta que la
	# referencia nunca implementó. Spec 07 posee la implementación real.
	if not rows:
		exemption_cause = getattr(invoice, "es_verifactu_exempt_cause", None) or None
		if exemption_cause:
			regime_key = getattr(invoice, "es_verifactu_regime_key", None) or DEFAULT_REGIME_KEY
			base = float(getattr(invoice, "net_total", None) or 0)
			rows.append(
				{
					"tax_type": "IVA",
					"tax_rate": "0",
					"taxable_base": base,
					"tax_amount": 0.0,
					"operation_classification": "S2",
					"regime_key": regime_key,
					"exemption_cause": exemption_cause,
					"recipients": None,
				}
			)
	return rows
