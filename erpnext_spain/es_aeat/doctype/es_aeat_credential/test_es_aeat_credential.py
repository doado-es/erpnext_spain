# Site tests de ES AEAT Credential (spec 13 §2): extracción p12→PEM al
# validar, vigencia parseada, unicidad por empresa, limpieza al
# desactivar/cambiar y password conservado.
#
# La integración corre en una transacción que se revierte al terminar la
# clase, pero los ARCHIVOS en disco no: la clase limpia PEM y p12 en teardown.

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_spain.es_aeat.doctype.es_aeat_credential.es_aeat_credential import pem_names, pem_paths
from erpnext_spain.es_aeat.tests.helpers import (
	clean_pem,
	delete_private_file,
	generate_p12,
	test_company,
	write_private_p12,
)

PASSWORD = "es-test-pass"

# La caminata de dependencias del IntegrationTestCase (make_test_records de
# «Company») importa la maquinaria de tests de erpnext, cuyo BootStrapTestData
# asume fixtures en inglés («All Departments») que no existen en un site
# localizado — LinkValidationError en el import. Estos tests usan la primera
# compañía REAL del site (test_company): no necesitan registros Company
# autogenerados.
IGNORE_TEST_RECORD_DEPENDENCIES = ["Company"]


class TestESAEATCredential(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = test_company()
		cls.password = PASSWORD
		cls.url_p12 = write_private_p12("es_test_cred.p12", generate_p12(password=cls.password.encode())[0])
		cls.addClassCleanup(delete_private_file, cls.url_p12)
		cls.addClassCleanup(clean_pem, cls.company)

	def setUp(self):
		frappe.set_user("Administrator")
		# Los tests de la clase comparten transacción: cada test arranca sin
		# credenciales (delete_doc dispara on_trash → limpia los PEM de disco).
		for name in frappe.get_all("ES AEAT Credential", filters={"company": self.company}, pluck="name"):
			frappe.delete_doc("ES AEAT Credential", name, ignore_permissions=True)

	def _new_credential(self, **overrides) -> object:
		doc = frappe.get_doc(
			{
				"doctype": "ES AEAT Credential",
				"company": self.company,
				"cert_file": self.url_p12,
				"cert_password": self.password,
				"enabled": 1,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _pems_exist(self) -> bool:
		import os

		return all(os.path.exists(path) for path in pem_paths(self.company))

	def test_insert_extracts_pem_and_parses_validity(self):
		import os
		from datetime import datetime, timedelta, timezone

		p12, desde, hasta = generate_p12(password=self.password.encode())
		url = write_private_p12("es_test_cred_fechas.p12", p12)
		self.addClassCleanup(delete_private_file, url)

		doc = self._new_credential(cert_file=url)

		# El nombre es la compañía (un certificado por empresa)
		self.assertEqual(doc.name, self.company)
		# PEM fuera de private/files, con permisos 0600 (H3)
		for path in pem_paths(self.company):
			self.assertTrue(os.path.exists(path), path)
			self.assertIn(os.path.join("private", "es_keys"), path)
			self.assertNotIn(os.path.join("private", "files"), path)
			self.assertEqual(os.stat(path).st_mode & 0o777, 0o600, path)
		self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)
		# Vigencia parseada del certificado (fechas UTC del p12)
		self.assertEqual(frappe.utils.getdate(doc.valid_from), desde.date())
		self.assertEqual(frappe.utils.getdate(doc.valid_until), hasta.date())

	def test_one_credential_per_company(self):
		"""Un certificado por empresa: VeriFactu, el SII y Facturae lo comparten."""
		self._new_credential()
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._new_credential()
		self.assertIn("Ya existe la credencial AEAT", str(ctx.exception))
		self.assertIn("Remedio", str(ctx.exception))

	def test_duplicate_blocks_even_disabled(self):
		primera = self._new_credential()
		primera.enabled = 0
		primera.save(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			self._new_credential()

	def test_disable_cleans_pem_and_reenable_reextracts(self):
		doc = self._new_credential()
		self.assertTrue(self._pems_exist())

		doc.enabled = 0
		doc.save(ignore_permissions=True)
		self.assertFalse(self._pems_exist())

		doc.enabled = 1
		doc.save(ignore_permissions=True)
		self.assertTrue(self._pems_exist())

	def test_password_kept_for_reextraction(self):
		"""Decisión del spec 13 §2: el password SE CONSERVA (cifrado, Password
		field) — re-extraer sin re-subir el archivo debe funcionar."""
		doc = self._new_credential()
		doc.reload()
		self.assertTrue(doc.get_password("cert_password", raise_exception=False))

	def test_wrong_password_blocks_with_remedy(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._new_credential(cert_password="incorrecta")
		self.assertIn("contraseña", str(ctx.exception).lower())
		self.assertIn("Remedio", str(ctx.exception))

	def test_file_change_reextracts(self):
		import os
		from datetime import timedelta

		from cryptography import x509

		doc = self._new_credential()

		# Segundo p12 con vigencia distinta
		other_p12, _, other_end = generate_p12(password=self.password.encode(), days_to=99)
		other_url = write_private_p12("es_test_cred_otro.p12", other_p12)
		self.addClassCleanup(delete_private_file, other_url)

		doc.cert_file = other_url
		doc.save(ignore_permissions=True)

		self.assertEqual(frappe.utils.getdate(doc.valid_until), other_end.date())
		self.assertTrue(all(os.path.exists(path) for path in pem_paths(self.company)))

	def test_named_after_company_and_company_set_only_once(self):
		"""El docname es la compañía y la compañía no se puede cambiar (los PEM van
		claveados por ella)."""
		doc = self._new_credential()
		self.assertEqual(doc.name, self.company)
		meta = frappe.get_meta("ES AEAT Credential")
		self.assertTrue(meta.get_field("company").set_only_once)
		self.assertFalse(meta.has_field("purpose"))

	def test_get_days_remaining(self):
		doc = self._new_credential()
		doc.reload()
		days = doc.get_days_remaining()
		self.assertIsNotNone(days)
		self.assertTrue(20 <= days <= 30, days)

		doc.valid_until = None
		self.assertIsNone(doc.get_days_remaining())

	def test_delete_credential_cleans_pem(self):
		import os

		doc = self._new_credential()
		self.assertTrue(self._pems_exist())
		doc.delete(ignore_permissions=True)
		self.assertFalse(any(os.path.exists(path) for path in pem_paths(self.company)))

	def test_pem_extracted_at_absolute_site_path(self):
		"""Fix del drenaje en vivo (workers con CWDs mixtos): los PEM viven
		en la ruta ABSOLUTA del site real (ancla get_bench_path), no una
		relativa al CWD — tras el save existen EXACTAMENTE ahí y el cliente
		TLS los resuelve igual desde cualquier proceso."""
		import os

		from frappe.utils import get_bench_path

		doc = self._new_credential()
		files_root = os.path.join(get_bench_path(), "sites", frappe.local.site, "private", "es_keys")
		cert, key = pem_paths(self.company)
		for path in (cert, key):
			self.assertTrue(os.path.isabs(path), path)
			self.assertTrue(path.startswith(files_root), path)
			self.assertTrue(os.path.exists(path), path)
		self.assertTrue(doc.name)  # el save no revienta: extracción ok

	def test_company_rename_keeps_certificate(self):
		"""Renombrar la compañía no deja la credencial sin PEM: los ficheros van por
		el nombre de la credencial, que no cambia (caso real: «ctg» → razón social)."""
		import os

		from erpnext_spain.es_aeat.client import enabled_credential_pem_paths

		doc = self._new_credential()
		renamed = f"{self.company} Renombrada"
		frappe.rename_doc("Company", self.company, renamed, force=True)
		self.addCleanup(frappe.rename_doc, "Company", renamed, self.company, force=True)

		self.assertEqual(frappe.db.get_value("ES AEAT Credential", doc.name, "company"), renamed)
		cert, key = enabled_credential_pem_paths(renamed, "VeriFactu")
		self.assertEqual((cert, key), pem_paths(doc.name))
		self.assertTrue(os.path.exists(cert) and os.path.exists(key))

	def test_pem_names_keyed_by_company(self):
		# frappe.scrub de la compañía: espacios y guiones a «_», sin tocar
		# puntos («S.L.» → «s.l.»).
		cert, key = pem_names("Mi Empresa S.L.")
		self.assertEqual(cert, "mi_empresa_s.l.-cert.pem")
		self.assertEqual(key, "mi_empresa_s.l.-key.pem")

	def test_pfx_accepted(self):
		"""El PFX es el mismo contenedor PKCS#12 que el p12 (misma estructura
		ASN.1, extensión distinta — es el formato que entregan las CA
		españolas). La extracción (cryptography.load_pkcs12) es agnóstica de
		 extensión: un .pfx subido extrae PEM y parsea vigencia igual que un
		.p12. Regresión del contrato de admisión PFX/P12."""
		import os

		pfx, desde, hasta = generate_p12(password=self.password.encode())
		url_pfx = write_private_p12("es_test_pfx.pfx", pfx)
		self.addCleanup(delete_private_file, url_pfx)

		doc = self._new_credential(cert_file=url_pfx)
		self.assertTrue(self._pems_exist())
		# Vigencia parseada igual que un .p12 (fechas UTC → date, patrón del
		# test de fechas de la misma clase)
		self.assertEqual(frappe.utils.getdate(doc.valid_from), desde.date())
		self.assertEqual(frappe.utils.getdate(doc.valid_until), hasta.date())
		# Los PEM extraídos del PFX son legibles como cualquier otro
		for path in pem_paths(self.company):
			self.assertTrue(os.path.getsize(path) > 0)

	# --- el certificado siempre privado ---

	def _attach(self, credential: str, name: str, is_private: int):
		return frappe.get_doc(
			{
				"doctype": "File",
				"file_name": name,
				"content": generate_p12(password=self.password.encode())[0],
				"is_private": is_private,
				"attached_to_doctype": "ES AEAT Credential",
				"attached_to_name": credential,
				"attached_to_field": "cert_file",
			}
		)

	def _remove_from_disk(self, name: str) -> None:
		import os

		for folder in ("public", "private"):
			path = frappe.get_site_path(folder, "files", name)
			if os.path.exists(path):
				os.remove(path)

	def test_public_certificate_rejected(self):
		"""Una URL pública (/files/…) no se privatiza en silencio: se rechaza."""
		self.assertRaisesRegex(
			frappe.ValidationError, "archivo público", self._new_credential, cert_file="/files/es_test.p12"
		)

	def test_certificate_cannot_be_uploaded_public(self):
		doc = self._new_credential()
		name = "es_test_publico.p12"
		self.addCleanup(self._remove_from_disk, name)
		self.assertRaisesRegex(
			frappe.PermissionError, "archivo privado", self._attach(doc.name, name, 0).insert
		)

	def test_certificate_cannot_be_made_public(self):
		"""El rechazo va antes de que File mueva el archivo a public/files."""
		import os

		doc = self._new_credential()
		name = "es_test_privado.p12"
		self.addCleanup(self._remove_from_disk, name)
		attached = self._attach(doc.name, name, 1).insert(ignore_permissions=True)
		attached.is_private = 0
		self.assertRaisesRegex(frappe.PermissionError, "archivo privado", attached.save)
		self.assertTrue(os.path.exists(frappe.get_site_path("private", "files", name)))
		self.assertFalse(os.path.exists(frappe.get_site_path("public", "files", name)))

	def test_other_public_files_untouched(self):
		"""Los archivos de otros documentos siguen pudiendo ser públicos (R7)."""
		name = "es_test_otro_publico.txt"
		self.addCleanup(self._remove_from_disk, name)
		file_doc = frappe.get_doc(
			{"doctype": "File", "file_name": name, "content": b"x", "is_private": 0}
		).insert(ignore_permissions=True)
		self.assertFalse(file_doc.is_private)

	def test_patch_points_to_private_file(self):
		"""Credenciales anteriores con /files/…: la versión previa privatizaba el
		archivo pero dejaba la URL pública en el campo."""
		from erpnext_spain.patches.v16.private_aeat_certificate import execute

		doc = self._new_credential()
		name = "es_test_migrado.p12"
		self.addCleanup(self._remove_from_disk, name)
		private = self._attach(doc.name, name, 1).insert(ignore_permissions=True)
		frappe.db.set_value("ES AEAT Credential", doc.name, "cert_file", f"/files/{name}")
		execute()
		self.assertEqual(frappe.db.get_value("ES AEAT Credential", doc.name, "cert_file"), private.file_url)

	# --- nombres de los PEM sin salir de private/es_keys ---

	def test_pem_names_without_path_separators(self):
		for name in ("../../sites/x", "A/B", "C\\D"):
			for pem in pem_names(name):
				self.assertNotIn("/", pem)
				self.assertNotIn("\\", pem)
		# Sustituir el separador no hace coincidir dos compañías distintas.
		self.assertNotEqual(pem_names("A/B"), pem_names("A_B"))
		# Los nombres que ya eran seguros no cambian (los PEM existentes siguen valiendo).
		self.assertEqual(pem_names("A_B"), ("a_b-cert.pem", "a_b-key.pem"))

	def test_pem_paths_stay_in_keys_dir(self):
		import os

		from erpnext_spain.es_aeat.doctype.es_aeat_credential.es_aeat_credential import KEYS_DIR
		from erpnext_spain.es_aeat.utils import absolute_site_path

		keys = absolute_site_path(*KEYS_DIR)
		for path in pem_paths("../../../tmp/es_test"):
			self.assertEqual(os.path.dirname(os.path.normpath(path)), keys)

	def test_write_secret_refuses_symlink(self):
		import os
		import tempfile

		from erpnext_spain.es_aeat.doctype.es_aeat_credential.es_aeat_credential import write_secret

		with tempfile.TemporaryDirectory() as folder:
			target = os.path.join(folder, "target")
			link = os.path.join(folder, "link")
			with open(target, "w") as f:
				f.write("intacto")
			os.symlink(target, link)
			self.assertRaises(OSError, write_secret, link, b"clave")
			with open(target) as f:
				self.assertEqual(f.read(), "intacto")
