# Tests del naming de emisión VeriFactu — lote 4b (spec 04 §4): mixin de
# borradores, renombre quirúrgico en before_submit, índices de rendimiento.
#
# NOTA de colocación (idéntica a test_company.py): módulo en tests/, el
# framework NO admite IGNORE_TEST_RECORD_DEPENDENCIES aquí (raise
# NotImplementedError fuera de carpeta de doctype). No hace falta: se usa la
# primera compañía REAL del site y masters reales (customer/item/cuenta de
# IVA); el rollback POR CLASE devuelve todo. Las aserciones sobre contadores
# tabSeries son POR DELTA: dentro de una clase los tests comparten
# transacción y el contador acumula.
#
# PRECONDICIÓN de TestPerformanceIndexes: `bench --site es.localhost
# migrate` (after_migrate crea los índices idempotentemente).

from __future__ import annotations

import glob
import os
from typing import ClassVar

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, cint, nowdate

from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.utils import absolute_site_path
from erpnext_spain.es_verifactu import emission
from erpnext_spain.es_verifactu.utils import locks
from erpnext_spain.tests.fixtures import TEST_CUSTOMER, TEST_ITEM

P12_PATTERN = "es_test_emision_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"  # DNI con letra de control correcta
ACTIVATION_DATE = "2026-01-01"

DRAFT_SERIES = "BORRADOR-.#####"
SERIES_F1 = "SIF1-.####."

# Prefijo del contador tabSeries del naming_series estándar «ACC-SINV-.YYYY.-»
# en 2026 (YYYY → %y = 26): jamás debe consumirse con el mixin activo.
NAMING_SERIES_PREFIX = "ACC-SINV-26-"

DRAFT_FALLBACK_REGEX = r"^BORRADOR-\d{10}-[0-9a-f]{8}$"

# Masters reales del site (verificados): cliente, artículo de venta y
# cuenta de IVA (tipo Tax) de la compañía de pruebas.
CUSTOMER = TEST_CUSTOMER
ITEM = TEST_ITEM


def _delete_test_p12s() -> None:
	for path in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(path)


class TestEmisionNaming(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.p12 = generate_p12(password=PASSWORD.encode())[0]
		_delete_test_p12s()  # restos de corridas abortadas
		cls.addClassCleanup(_delete_test_p12s)
		cls.addClassCleanup(clean_pem, cls.company)
		cls.tax_account = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Tax", "is_group": 0}, "name"
		)

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test arranca con la compañía en
		# estado prístino (reset por db.set_value, sin hooks — véase
		# test_company.py para el porqué del NOI).
		frappe.db.set_value(
			"Company",
			self.company,
			{
				"es_verifactu_enabled": 0,
				"es_verifactu_activation_date": None,
				"es_draft_series": None,
				"es_verifactu_noi": None,
				"tax_id": None,
			},
		)
		frappe.db.delete("ES Invoice Series", {"parent": self.company})
		frappe.db.delete("ES Verifactu Notification Role", {"parent": self.company})
		for credential in frappe.get_all(
			"ES AEAT Credential", filters={"company": self.company}, pluck="name"
		):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)

	# --- helpers -----------------------------------------------------------

	def _activate(
		self,
		series: str = SERIES_F1,
		invoice_type: str = "F1",
		draft: str = DRAFT_SERIES,
		test_mode: str = "Pruebas",
		with_series: bool = True,
	):
		"""Deja la compañía ACTIVA (compuerta completa: NIF, credencial,
		fecha, serie de borradores) y devuelve el doc Company guardado."""
		# Credencial previa de la empresa fuera: el nombre del credential es
		# la compañía (una por empresa) y una segunda
		# activación en el MISMO test colisionaría.
		for credential in frappe.get_all(
			"ES AEAT Credential",
			filters={"company": self.company},
			pluck="name",
		):
			frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)
		doc = frappe.get_doc("Company", self.company)
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		doc.es_verifactu_activation_date = ACTIVATION_DATE
		doc.es_verifactu_test_mode = test_mode
		doc.es_draft_series = draft
		# Filas previas fuera (get_doc carga las children ya persistidas en
		# la transacción de la clase: re-append las duplicaría).
		doc.set("es_invoice_series", [])
		if with_series:
			doc.append("es_invoice_series", {"series": series, "invoice_type": invoice_type})
		url = write_private_p12(f"es_test_emision_{frappe.generate_hash(length=8)}.p12", self.p12)
		frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": self.company,
				"cert_file": url,
				"cert_password": PASSWORD,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		doc.save(ignore_permissions=True)
		return doc

	def _current_series(self, prefix: str) -> int:
		"""Contador tabSeries de un prefijo. OJO: get_value sobre Series
		NECESITA order_by explícito — tabSeries es una tabla desnuda (sin
		creation) y el ORDER BY por defecto rompe (igual que en
		naming.py:131/138)."""
		return cint(frappe.db.get_value("Series", prefix, "current", order_by="name"))

	def _draft_invoice(self, posting_date=None, set_name=None, n_items=1, with_taxes=True):
		"""Factura mínima de la compañía de pruebas (masters reales del
		site); el naming lo resuelve el mixin. set_posting_time=1 para que
		el posting_date explícito sobreviva al validate del core (si no,
		erpnext lo fuerza a hoy)."""
		return frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": CUSTOMER,
				"naming_series": "ACC-SINV-.YYYY.-",
				"currency": "EUR",
				"posting_date": posting_date or "2026-08-31",
				"set_posting_time": 1,
				"due_date": add_days(nowdate(), 30),
				"items": [{"item_code": ITEM, "qty": 1, "rate": 100} for _ in range(n_items)],
				**(
					{
						"taxes": [
							{
								"charge_type": "On Net Total",
								"account_head": self.tax_account,
								"rate": 21,
								# Patrón de descripción del contrato 07 (spec 04 §7):
								# el desglose del lote 4c lo parsea.
								"description": "IVA - 21",
							}
						]
					}
					if with_taxes
					else {}
				),
			}
		).insert(ignore_permissions=True, set_name=set_name)

	# --- naming de borradores (mixin, spec 04 §4) --------------------------

	def test_draft_sequential_own_pattern(self):
		"""Compañía CON serie de borradores: nombre según el patrón, contador
		SECUENCIAL propio — la serie fiscal del naming_series jamás se toca."""
		frappe.db.set_value(
			"Company",
			self.company,
			{"es_verifactu_enabled": 1, "es_draft_series": DRAFT_SERIES, "tax_id": VALID_NIF},
		)
		fiscal_before = self._current_series(NAMING_SERIES_PREFIX)

		a = self._draft_invoice()
		b = self._draft_invoice()

		self.assertRegex(a.name, r"^BORRADOR-\d{5}$")
		self.assertRegex(b.name, r"^BORRADOR-\d{5}$")
		self.assertEqual(int(b.name.rsplit("-", 1)[1]), int(a.name.rsplit("-", 1)[1]) + 1)

		# el contador fiscal del naming_series está INTACTO:
		fiscal_after = self._current_series(NAMING_SERIES_PREFIX)
		self.assertEqual(fiscal_after, fiscal_before)

	def test_draft_fallback_shape(self):
		"""Sin patrón configurado (ni siquiera activada): fallback
		«BORRADOR-{epoch}-{hash}» — estable, ordenable, sin dependencias.
		El fallback aplica TAMBIÉN con VeriFactu activo si el patrón falta
		(defensa: la compuerta normalmente lo exige)."""
		# NIF de emisor: la compuerta de validate del 4c lo exige en borrador
		# cuando la compañía está activa (última barrera, spec 04 §4.2).
		frappe.db.set_value(
			"Company",
			self.company,
			{"es_verifactu_enabled": 1, "es_draft_series": None, "tax_id": VALID_NIF},
		)
		a = self._draft_invoice()
		self.assertRegex(a.name, DRAFT_FALLBACK_REGEX)

	def test_inactive_company_uses_naming_series(self):
		"""H1 (spec 01 §8): sin numeración al emitir, el borrador NO lleva nombre
		temporal; Frappe aplica la naming_series como en ERPNext estándar."""
		a = self._draft_invoice()
		self.assertTrue(a.name.startswith("ACC-SINV-"), a.name)
		self.assertFalse(emission._is_draft(a.name, None))

	def test_draft_released_when_verifactu_deactivated(self):
		"""Un borrador con nombre temporal que se valida después de desactivar
		VeriFactu recibe el número de su naming_series (no se queda con el
		nombre temporal)."""
		frappe.db.set_value(
			"Company", self.company, {"es_verifactu_enabled": 1, "es_draft_series": None, "tax_id": VALID_NIF}
		)
		a = self._draft_invoice()
		self.assertRegex(a.name, DRAFT_FALLBACK_REGEX)
		frappe.db.set_value("Company", self.company, "es_verifactu_enabled", 0)
		a.reload()
		a.submit()
		self.assertTrue(a.name.startswith("ACC-SINV-"), a.name)
		self.assertTrue(frappe.db.exists("Sales Invoice", a.name))
		self.assertTrue(frappe.get_all("GL Entry", filters={"voucher_no": a.name}, pluck="name"))

	def test_no_class_extension_hooks(self):
		"""H2 (spec 01 §8): ninguna extensión ni sustitución de clases (R2)."""
		self.assertFalse(frappe.get_hooks("extend_doctype_class", app_name="erpnext_spain"))
		self.assertFalse(frappe.get_hooks("override_doctype_class", app_name="erpnext_spain"))

	# --- submit: renombre quirúrgico (spec 04 §4) ---------------------------

	def test_submit_renames_to_mapped_series(self):
		"""El submit consume el número fiscal EXACTO una vez y el nombre
		final sigue el patrón de la serie mapeada al tipo F1."""
		self._activate()
		series_before = self._current_series("SIF1-")

		a = self._draft_invoice()
		self.assertTrue(emission._is_draft(a.name, DRAFT_SERIES))
		a.submit()

		self.assertEqual(a.docstatus, 1)
		self.assertRegex(a.name, r"^SIF1-\d{4}$")
		series_after = self._current_series("SIF1-")
		self.assertEqual(series_after - series_before, 1)

		# persistido con el nombre fiscal:
		self.assertEqual(frappe.db.get_value("Sales Invoice", a.name, "docstatus"), 1)

	def test_children_intact_after_rename(self):
		"""LA regresión crítica del v1: tras el renombre, items y taxes
		siguen colgando del NUEVO nombre (en memoria y en DB), sin huerfanar
		nada bajo el nombre de borrador."""
		self._activate()
		a = self._draft_invoice(n_items=2)
		draft_name = a.name
		counts = {"items": len(a.items), "taxes": len(a.taxes)}
		self.assertEqual(counts["items"], 2)
		self.assertEqual(counts["taxes"], 1)

		a.submit()
		final = a.name

		# en memoria: children re-padreados al nombre fiscal
		for child in a.get_all_children():
			self.assertEqual(child.parent, final)

		# en DB: mismas cantidades bajo el nombre final...
		self.assertEqual(frappe.db.count("Sales Invoice Item", {"parent": final}), counts["items"])
		self.assertEqual(frappe.db.count("Sales Taxes and Charges", {"parent": final}), counts["taxes"])
		# ...y NADA huerfano bajo el borrador:
		self.assertEqual(frappe.db.count("Sales Invoice Item", {"parent": draft_name}), 0)
		self.assertEqual(frappe.db.count("Sales Taxes and Charges", {"parent": draft_name}), 0)

	def test_gl_entries_with_final_name(self):
		"""El core (on_submit) corre DESPUÉS del renombre: los asientos
		nacen con el nombre fiscal — el bug catastrófico del v1 queda
		estructuralmente imposible."""
		self._activate()
		a = self._draft_invoice()
		draft_name = a.name
		a.submit()

		self.assertTrue(frappe.get_all("GL Entry", filters={"voucher_no": a.name}, pluck="name"))
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": draft_name}), 0)

	def test_failed_submit_releases_number(self):
		"""Un fallo DESPUÉS del renombre (seam es_test_fail_submit) revierte
		la media emisión y el contador queda como estaba: el siguiente submit
		recibe EL MISMO número fiscal (sin huecos). El rollback al savepoint
		reproduce el rollback de petición que hace frappe en producción."""
		self._activate()
		a = self._draft_invoice()
		draft_name = a.name
		series_before = self._current_series("SIF1-")

		frappe.db.savepoint("es_l4b")
		frappe.flags.es_test_fail_submit = True
		try:
			with self.assertRaises(frappe.ValidationError):
				a.submit()
		finally:
			frappe.flags.es_test_fail_submit = False

		# el submit falló DESPUÉS del renombre:
		failed = a.name
		self.assertTrue(failed.startswith("SIF1-"), failed)

		# la petición real se revierte entera; aquí, al savepoint:
		frappe.db.rollback(save_point="es_l4b")

		# el contador volvió al valor previo:
		self.assertEqual(self._current_series("SIF1-"), series_before)
		# y la factura volvió a ser borrador con su nombre temporal:
		self.assertEqual(frappe.db.get_value("Sales Invoice", draft_name, "docstatus"), 0)

		# el siguiente submit de una factura NUEVA recibe EL MISMO número:
		frappe.delete_doc("Sales Invoice", draft_name, ignore_permissions=True)
		b = self._draft_invoice()
		b.submit()
		self.assertEqual(b.name, failed)

	def test_import_explicit_name_not_renamed(self):
		"""GUARD del defecto v1: una factura con nombre explícito (vía
		import/migración — insert(set_name=...) preserva el nombre y el
		mixin ni corre) NO se renombra al submit; se emite tal cual."""
		self._activate()
		si = self._draft_invoice(set_name="OLD-INV-001")
		self.assertEqual(si.name, "OLD-INV-001")

		si.submit()

		self.assertEqual(si.name, "OLD-INV-001")
		self.assertEqual(frappe.db.get_value("Sales Invoice", "OLD-INV-001", "docstatus"), 1)
		self.assertTrue(frappe.get_all("GL Entry", filters={"voucher_no": "OLD-INV-001"}, pluck="name"))

	def test_operative_mode_snapshot(self):
		"""El modo operativo se congela POR FACTURA al emitir (spec 04
		§2.3): «Verifactu en pruebas» en modo pruebas, «Verifactu» en
		producción."""
		self._activate(test_mode="Pruebas")
		pruebas = self._draft_invoice()
		pruebas.submit()
		self.assertEqual(pruebas.es_verifactu_mode, "Verifactu en pruebas")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", pruebas.name, "es_verifactu_mode"),
			"Verifactu en pruebas",
		)

		self._activate(test_mode="Producción")
		produccion = self._draft_invoice()
		produccion.submit()
		self.assertEqual(produccion.es_verifactu_mode, "Verifactu")
		self.assertEqual(
			frappe.db.get_value("Sales Invoice", produccion.name, "es_verifactu_mode"),
			"Verifactu",
		)

	def test_posting_date_kept_today(self):
		"""Recomendación «mantener» de la AEAT: sin retrodatación — el
		posteriore a ayer se fuerza a hoy en el submit."""
		self._activate()
		yesterday = add_days(nowdate(), -1)
		a = self._draft_invoice(posting_date=yesterday)
		self.assertEqual(str(a.posting_date), yesterday)

		a.submit()

		self.assertEqual(str(a.posting_date), nowdate())
		self.assertEqual(str(frappe.db.get_value("Sales Invoice", a.name, "posting_date")), nowdate())

	# --- guards de la compuerta en el submit ---------------------------------

	def test_missing_credential_blocks_with_remedy(self):
		"""Compañía activa sin credencial habilitada (empresa, VeriFactu):
		el submit rebota con remedio ANTES de renombrar — la factura sigue
		siendo borrador con su nombre temporal."""
		self._activate()
		frappe.db.set_value(
			"ES AEAT Credential",
			{"company": self.company},
			"enabled",
			0,
		)

		a = self._draft_invoice()
		name = a.name
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.submit()

		self.assertIn("certificado AEAT habilitado", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

		# sin renombre, sin snapshot, sin GL: sigue siendo borrador:
		self.assertEqual(frappe.db.get_value("Sales Invoice", name, "docstatus"), 0)
		self.assertFalse(frappe.db.get_value("Sales Invoice", name, "es_verifactu_mode"))
		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": name}), 0)

	def test_missing_series_mapping_blocks_with_remedy(self):
		"""Compañía activa sin mapeo serie↔tipo (la compuerta lo permite):
		el submit rebota con remedio antes de consumir nada."""
		self._activate(with_series=False)
		series_before = self._current_series("SIF1-")

		a = self._draft_invoice()
		name = a.name
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.submit()

		self.assertIn("No hay serie mapeada", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))
		self.assertEqual(frappe.db.get_value("Sales Invoice", name, "docstatus"), 0)
		self.assertEqual(self._current_series("SIF1-"), series_before)

	def test_inactive_company_submit_untouched(self):
		"""Sin VeriFactu, el submit prosigue UNTOUCHED: ni renombre ni campos
		es_; la factura conserva el número de su naming_series (H1)."""
		# setUp deja la compañía sin activar
		a = self._draft_invoice()
		name = a.name
		self.assertTrue(name.startswith("ACC-SINV-"), name)

		a.submit()

		self.assertEqual(a.docstatus, 1)
		self.assertEqual(a.name, name)
		self.assertIsNone(frappe.db.get_value("Sales Invoice", name, "es_verifactu_mode"))
		self.assertTrue(frappe.get_all("GL Entry", filters={"voucher_no": name}, pluck="name"))

	# --- cerrojo de cadena (utils/locks.py, spec 04 §12) --------------------

	def test_chain_lock(self):
		"""El cerrojo serializa por compañía: una segunda adquisición con
		timeout corto rebota con REMEDIO (sin bloqueo eterno) y al liberar
		se puede readquirir."""
		with locks.chain_lock(self.company):
			with self.assertRaises(frappe.ValidationError) as ctx:
				with locks.chain_lock(self.company, timeout=0.2):
					pass
			self.assertIn("cerrojo", str(ctx.exception))
			self.assertIn("Remedio", str(ctx.exception))

		# liberado → readquisición inmediata:
		with locks.chain_lock(self.company, timeout=1):
			pass


class TestPerformanceIndexes(IntegrationTestCase):
	"""Índices compuestos del renombre (spec 04 §4.3). PRECONDICIÓN:
	`bench --site es.localhost migrate` (after_migrate los crea de forma
	idempotente: has_index + ADD INDEX IF NOT EXISTS)."""

	INDEXES: ClassVar[list[tuple[str, str]]] = [
		("tabVersion", "docname_ref_doctype_index"),
		("tabFile", "attached_to_name_attached_to_doctype_index"),
		("tabCommunication", "reference_name_reference_doctype_index"),
		("tabStock Ledger Entry", "voucher_no_voucher_type_index"),
	]

	def test_composite_indexes_exist(self):
		for tabla, indice in self.INDEXES:
			self.assertTrue(
				frappe.db.has_index(tabla, indice),
				f"Falta el índice {indice} en {tabla} (¿corrió bench migrate?)",
			)
