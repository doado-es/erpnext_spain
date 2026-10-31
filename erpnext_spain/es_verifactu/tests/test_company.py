# Site tests de la puerta de activación de VeriFactu en Company (spec 04
# §2.1): doc_events «validate» (nif/party corre primero; esta compuerta
# cierra después), biyección de series y no compartición entre empresas,
# colisión de la serie de borradores, NOI derivado UNA vez e inmutable,
# congelación de la fecha de activación con registros emitidos y límite de
# lote de la AEAT.
#
# NOTA de colocación: a diferencia de los tests en carpeta doctype/
# (test_es_aeat_credential, test_es_verifactu_billing_record), este módulo
# vive en tests/ — el framework NO admite IGNORE_TEST_RECORD_DEPENDENCIES
# fuera de una carpeta de doctype (raise NotImplementedError) y tampoco
# camina dependencias (no hay doctype inferido del módulo). No hace falta:
# se usa la primera compañía REAL del site (test_company) y los
# fixtures se insertan a mano; el rollback POR CLASE los devuelve todo.

from __future__ import annotations

import glob
import os

import frappe
from frappe.model.document import Document
from frappe.tests import IntegrationTestCase

from erpnext_spain.aeat.tests.helpers import (
	clean_pem,
	generate_p12,
	test_company,
	write_private_p12,
)
from erpnext_spain.aeat.utils import absolute_site_path
from erpnext_spain.es_verifactu import company as company_module

P12_PATTERN = "es_test_company_*.p12"
PASSWORD = "es-test-pass"

VALID_NIF = "12345678Z"  # DNI con letra de control correcta (usado como válido en test_party)
INVALID_NIF = "12345678A"  # letra equivocada: la correcta es Z (sugerencia del verificador)
SECOND_COMPANY_CIF = "B58834813"  # CIF con control correcto (verificado contra stdnum)

ACTIVATION_DATE = "2026-01-01"
NEW_DATE = "2026-02-01"

SERIES_F1 = "SI-F1-.####."
DRAFT_SERIES = "BORRADOR-.#####"

NOI_REGEX = r"^[A-Z2-7]{52}$"  # SHA-256 (32 bytes) en Base32 sin padding


def _delete_test_p12s() -> None:
	"""Borra de disco los p12 de test de esta clase (los archivos físicos NO
	se revierten con la transacción)."""
	for ruta in glob.glob(absolute_site_path("private", "files", P12_PATTERN)):
		os.remove(ruta)


class TestVerifactuActivationGate(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		# Los bytes del p12 se generan UNA vez; cada credencial escribe su
		# PROPIO archivo. NO se comparte un p12 entre credenciales: el
		# framework crea un File doc por Attach y al borrar la ÚLTIMA
		# referencia (mismo content_hash) elimina el archivo físico de disco
		# — con un único p12 compartido, el setUp que borra credenciales
		# terminaría arrastrando el fixture de las demás.
		cls.p12 = generate_p12(password=PASSWORD.encode())[0]
		_delete_test_p12s()  # restos de corridas abortadas
		cls.addClassCleanup(_delete_test_p12s)
		cls.addClassCleanup(clean_pem, cls.company, "VeriFactu")

		# Segunda empresa REAL (España, EUR, CIF propio): duplicado de NIF y
		# compartición de series. El insert arrastra COA/almacenes/centros de
		# costo (~2 s); el rollback de la clase lo devuelve todo.
		cls.second_company = (
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": "ES VeriFactu Segunda SL",
					"abbr": "SCV2",
					"default_currency": "EUR",
					"country": "Spain",
					"tax_id": SECOND_COMPANY_CIF,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		cls.addClassCleanup(clean_pem, cls.second_company, "VeriFactu")

	def setUp(self):
		frappe.set_user("Administrator")
		# La clase comparte transacción: cada test arranca con ambas empresas
		# en estado prístino. El reset es por db.set_value (sin hooks) porque
		# el guard de NOI RESTAURARÍA el valor persistido al guardar — y aquí
		# lo que se quiere es despejar el fixture entre tests.
		for company_name in (self.company, self.second_company):
			frappe.db.set_value(
				"Company",
				company_name,
				{
					"es_verifactu_enabled": 0,
					"es_verifactu_activation_date": None,
					"es_verifactu_credential": None,
					"es_draft_series": None,
					"es_verifactu_noi": None,
				},
			)
			frappe.db.delete("ES Invoice Series", {"parent": company_name})
			frappe.db.delete("ES Verifactu Notification Role", {"parent": company_name})
			for credential in frappe.get_all("ES AEAT Credential", filters={"company": company_name}, pluck="name"):
				frappe.delete_doc("ES AEAT Credential", credential, ignore_permissions=True)
			for record in frappe.get_all(
				"ES Verifactu Billing Record", filters={"company": company_name}, pluck="name"
			):
				frappe.delete_doc("ES Verifactu Billing Record", record, ignore_permissions=True)
		# El NIF de la primera empresa solo se toca en los tests que lo usan;
		# el de la segunda es la identidad del fixture de duplicado.
		frappe.db.set_value("Company", self.company, "tax_id", None)

	# --- helpers -----------------------------------------------------------

	def _company_doc(self) -> Document:
		return frappe.get_doc("Company", self.company)

	def _second_doc(self) -> Document:
		return frappe.get_doc("Company", self.second_company)

	def _credential(self, company: str) -> Document:
		"""Credencial habilitada (empresa, VeriFactu) con su PROPIO p12 en
		private/files (véase setUpClass: no se comparte archivo)."""
		url = write_private_p12(f"es_test_company_{frappe.generate_hash(length=8)}.p12", self.p12)
		return frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": company,
				"purpose": "VeriFactu",
				"cert_file": url,
				"cert_password": PASSWORD,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)

	def _valid_config(self, doc: Document) -> Document:
		"""Deja el doc listo para activar: NIF válido y único, fecha de
		activación, serie de borradores sin colisión y mapeo serie↔tipo F1."""
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		doc.es_verifactu_activation_date = ACTIVATION_DATE
		doc.es_draft_series = DRAFT_SERIES
		doc.append("es_invoice_series", {"series": SERIES_F1, "invoice_type": "F1"})
		return doc

	def _activate(self) -> Document:
		doc = self._valid_config(self._company_doc())
		self._credential(self.company)
		doc.save(ignore_permissions=True)
		return doc

	# --- compuerta de activación (spec 04 §2.1) ----------------------------

	def test_activate_without_nif_blocks_with_remedy(self):
		doc = self._company_doc()
		doc.tax_id = None
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("no puede activar VeriFactu sin NIF", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_activate_invalid_nif_blocks_and_suggests(self):
		# Capa nif/party (doc_event que corre PRIMERO): el save rebota con la
		# sugerencia del verificador (la letra de control correcta es Z).
		doc = self._company_doc()
		doc.tax_id = INVALID_NIF
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))

		# La compuerta VeriFactu en sí también bloquea, con su remedio propio,
		# si llega a correr (llamada directa al handler).
		doc = self._company_doc()
		doc.tax_id = INVALID_NIF
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			company_module.validate(doc)
		self.assertIn("no es válido y VeriFactu no se puede activar", str(ctx.exception))
		self.assertIn("¿quisiste decir `Z`?", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_activate_duplicate_nif_in_other_company_blocks(self):
		"""Sin unicidad de NIF en el site, las respuestas de la AEAT llegan a
		la empresa equivocada (spec 04 §2.1)."""
		doc = self._company_doc()
		doc.tax_id = SECOND_COMPANY_CIF  # ya pertenece a la segunda empresa
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("ya pertenece a otra empresa", str(ctx.exception))
		self.assertIn(self.second_company, str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_activate_without_credential_blocks(self):
		"""La remisión exige TLS mutua con el certificado digital (spec 13
		§2): sin credencial HABILITADA (empresa, VeriFactu) no se activa."""
		doc = self._company_doc()
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("No hay credencial AEAT habilitada", str(ctx.exception))
		self.assertIn("VeriFactu", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_activate_without_date_blocks(self):
		self._credential(self.company)
		doc = self._company_doc()
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("Falta la fecha de activación", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_activate_without_draft_series_blocks(self):
		"""Con VeriFactu activo los borradores usan nombre temporal: el
		número fiscal solo se consume al emitir (spec 04 §4)."""
		self._credential(self.company)
		doc = self._company_doc()
		doc.tax_id = VALID_NIF
		doc.es_verifactu_enabled = 1
		doc.es_verifactu_activation_date = ACTIVATION_DATE
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("Falta la serie de borradores", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_happy_path_activates_and_derives_noi(self):
		doc = self._activate()
		persistido = frappe.db.get_value(
			"Company", self.company, ["es_verifactu_enabled", "es_verifactu_noi"], as_dict=True
		)
		self.assertEqual(persistido.es_verifactu_enabled, 1)

		# NOI derivado al activar: SHA-256 en Base32 (52 símbolos, sin padding)
		self.assertRegex(doc.es_verifactu_noi, NOI_REGEX)
		self.assertEqual(doc.es_verifactu_noi, company_module._derive_noi(self.company))
		self.assertEqual(persistido.es_verifactu_noi, doc.es_verifactu_noi)

	def test_not_active_no_validations(self):
		"""Early exit del interruptor: desactivada, la compuerta no valida
		NIF (el verificador nif/party sigue aplicando por su cuenta), ni
		exige credencial, fecha, series... y no deriva NOI."""
		doc = self._company_doc()
		doc.tax_id = INVALID_NIF
		company_module.validate(doc)  # no lanza
		self.assertFalse(doc.get("es_verifactu_noi"))

		# El NIF duplicado se tolera DESACTIVADA: la unicidad es exigencia de
		# la ACTIVACIÓN, no de la ficha (save real con los dos hooks).
		doc = self._company_doc()
		doc.tax_id = SECOND_COMPANY_CIF
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Company", self.company, "tax_id"), SECOND_COMPANY_CIF)

	# --- series (biyección + no compartición + borradores) -----------------

	def test_duplicate_series_in_mapping_blocks(self):
		self._activate()
		doc = self._company_doc()
		doc.append("es_invoice_series", {"series": SERIES_F1, "invoice_type": "F2"})
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("está duplicada en el mapeo", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_duplicate_type_in_mapping_blocks(self):
		"""Biyección serie↔tipo: un tipo por serie — dos series para F1 rebota."""
		self._activate()
		doc = self._company_doc()
		doc.append("es_invoice_series", {"series": "SI-OTRO-.####.", "invoice_type": "F1"})
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("El tipo de factura «F1» está duplicado", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_series_shared_with_other_company_blocks(self):
		"""El contador de series de ERPNext es global por prefijo, sin
		dimensión empresa: dos empresas con la misma serie intercalarían
		números y romperían la correlatividad de ambas (spec 04 §2.1)."""
		second = self._second_doc()
		second.append("es_invoice_series", {"series": SERIES_F1, "invoice_type": "F1"})
		second.save(ignore_permissions=True)

		doc = self._valid_config(self._company_doc())  # mapea la MISMA serie
		self._credential(self.company)
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("ya la usa la empresa", str(ctx.exception))
		self.assertIn(self.second_company, str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_draft_series_colliding_with_mapped_blocks(self):
		"""El prefijo de la serie de borradores no puede chocar con una serie
		fiscal mapeada: la colisión quemaría números de la serie fiscal."""
		doc = self._valid_config(self._company_doc())
		doc.es_draft_series = "SI-F1-.YYYY.-"  # prefijo «SI-F1-» = serie F1
		self._credential(self.company)
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("serie de borradores", str(ctx.exception))
		self.assertIn("colisiona", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	# --- NOI (identidad de la instalación ante la AEAT) --------------------

	def test_noi_stable_never_rederived(self):
		"""El NOI se deriva UNA vez y se restaura ante manipulación por API:
		jamás se recalcula (la identidad de la instalación debe ser estable)."""
		original = self._activate().es_verifactu_noi
		self.assertTrue(original)

		doc = self._company_doc()
		doc.es_verifactu_noi = "MANIPULADO-POR-API"
		doc.save(ignore_permissions=True)

		self.assertEqual(doc.es_verifactu_noi, original)
		self.assertEqual(frappe.db.get_value("Company", self.company, "es_verifactu_noi"), original)

	def test_noi_distinct_per_company(self):
		first = self._activate()
		self._credential(self.second_company)
		second = self._second_doc()
		second.es_verifactu_enabled = 1
		second.es_verifactu_activation_date = ACTIVATION_DATE
		second.es_draft_series = "BORRA2-.#####"
		second.append("es_invoice_series", {"series": "SI-F2-.####.", "invoice_type": "F2"})
		second.save(ignore_permissions=True)

		self.assertTrue(first.es_verifactu_noi)
		self.assertTrue(second.es_verifactu_noi)
		self.assertNotEqual(first.es_verifactu_noi, second.es_verifactu_noi)
		self.assertEqual(second.es_verifactu_noi, company_module._derive_noi(self.second_company))

	# --- congelación de la fecha de activación ------------------------------

	def test_changing_date_with_records_blocks(self):
		"""Mover la fecha con registros emitidos invalidaría la semántica del
		libro (spec 04 §2.1); la congelación corre SIEMPRE, activa o no."""
		self._activate()
		frappe.get_doc(
			{
				"doctype": "ES Verifactu Billing Record",
				"company": self.company,
				"record_type": "RegistroAlta",
				"invoice_type": "F1",
				"chain_index": 1,
			}
		).insert(ignore_permissions=True)

		doc = self._company_doc()
		doc.es_verifactu_activation_date = NEW_DATE
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("No se puede cambiar la fecha de activación", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))
		self.assertEqual(
			frappe.db.get_value("Company", self.company, "es_verifactu_activation_date"),
			frappe.utils.getdate(ACTIVATION_DATE),
		)

	def test_changing_date_without_records_allowed(self):
		self._activate()
		doc = self._company_doc()
		doc.es_verifactu_activation_date = NEW_DATE
		doc.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Company", self.company, "es_verifactu_activation_date"),
			frappe.utils.getdate(NEW_DATE),
		)

	# --- límites -------------------------------------------------------------

	def test_batch_limit_over_max_blocks(self):
		"""El límite de lote respeta el máximo de la AEAT aunque la empresa
		esté desactivada: el valor queda persistido y la remisión lo usa."""
		doc = self._company_doc()
		doc.es_verifactu_batch_limit = 1001
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("límite de lote", str(ctx.exception))
		self.assertIn("1000", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

		# frontera: exactamente el máximo pasa
		doc = self._company_doc()
		doc.es_verifactu_batch_limit = 1000
		doc.save(ignore_permissions=True)


class TestVerifactuFieldsOnSalesInvoice(IntegrationTestCase):
	"""Meta de los Custom Fields VeriFactu en Sales Invoice (spec 04 §2.3):
	presencia + defaults. Test de meta barato: sin crear documentos."""

	def test_fields_present_with_defaults(self):
		meta = frappe.get_meta("Sales Invoice")

		tipo = meta.get_field("es_invoice_type")
		self.assertIsNotNone(tipo)
		self.assertEqual(tipo.fieldtype, "Link")
		self.assertEqual(tipo.options, "ES Invoice Type")
		self.assertEqual(tipo.default, "F1")

		for campo, fieldtype in (
			("es_verifactu_mode", "Data"),
			("es_external_rectified_nif", "Data"),
			("es_external_rectified_number", "Data"),
			("es_external_rectified_date", "Date"),
		):
			df = meta.get_field(campo)
			self.assertIsNotNone(df, campo)
			self.assertEqual(df.fieldtype, fieldtype, campo)

		# snapshot de modo y estado denormalizado: read_only (los fija el
		# ciclo de vida de emisión/procesador, no el usuario)
		self.assertTrue(meta.get_field("es_verifactu_mode").read_only)
		self.assertTrue(meta.get_field("es_verifactu_status").read_only)

		regime_key = meta.get_field("es_verifactu_regime_key")
		self.assertIsNotNone(regime_key)
		self.assertEqual(regime_key.default, "01")

		exenta = meta.get_field("es_verifactu_exempt_cause")
		self.assertIsNotNone(exenta)
		opciones = (exenta.options or "").split("\n")
		for causa in ("E1", "E2", "E3", "E4", "E5", "E6"):
			self.assertIn(causa, opciones)

	def test_status_es_select_con_los_cuatro_estados(self):
		"""es_verifactu_status es Select (enumerable para pills en el list
		view — el indicador lo da sales_invoice_list.js#get_indicator) con
		EXACTAMENTE los estados del mapper (INVOICE_STATUS_*) y PRIMERA
		OPCIÓN VACÍA (la factura sin emitir no tiene estado — el Select sin
		default se autorrellena con la primera opción, ver el E1 fantasma)."""
		df = frappe.get_meta("Sales Invoice").get_field("es_verifactu_status")
		self.assertIsNotNone(df)
		self.assertEqual(df.fieldtype, "Select")
		opciones = df.options.split("\n")
		self.assertEqual(opciones[0], "")
		self.assertEqual(
			sorted(opciones[1:]),
			sorted(["Pendiente Envío", "Alta Aceptada", "Alta Con Errores", "Anulada"]),
		)
