# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Credencial AEAT por (empresa, propósito) — spec 13 §2.
#
# Extracción PFX/P12 (contenedor PKCS#12)→PEM al validar (patrón de la
# referencia): los PEM viven en sites/<sitio>/private/es_keys (H3, spec 01 §8):
# fuera de private/files, así que no entran en las copias de ficheros de
# `bench backup --with-files`, con el directorio en 0700 y los ficheros en 0600,
# nombres claveados por (company, purpose) y solo accesibles server-side. PFX y P12 son el
# MISMO contenedor PKCS#12 (estructura ASN.1 idéntica, extensión distinta) —
# el PFX es el que entregan habitualmente las CA españolas (FNMT, Camerfirma),
# y cryptography.load_pkcs12 lo lee sin distinción. Se CONSERVA el password
# (decisión del spec: permite re-extraer/rotar sin re-subir el archivo; la
# referencia lo borraba).
#
# Indicador de días restantes para el list view / form (spec 04 §15): el
# controller expone `get_days_remaining()`; el job diario de caducidad vive en
# erpnext_spain/aeat/tasks.py.

from __future__ import annotations

import os

import frappe
from frappe.model.document import Document

from erpnext_spain.aeat.utils import absolute_site_path, get_days_remaining


def pem_names(company: str, purpose: str) -> tuple[str, str]:
	"""Nombres de los PEM extraídos, claveados por (empresa, propósito)."""
	base = f"{frappe.scrub(company)}-{frappe.scrub(purpose)}"
	return f"{base}-cert.pem", f"{base}-key.pem"


KEYS_DIR = ("private", "es_keys")


def keys_dir() -> str:
	"""Directorio de los PEM, creado con permisos 0700 si no existe."""
	path = absolute_site_path(*KEYS_DIR)
	os.makedirs(path, mode=0o700, exist_ok=True)
	os.chmod(path, 0o700)
	return path


def write_secret(path: str, content: bytes) -> None:
	"""Escribe un fichero con permisos 0600 desde su creación (sin ventana en la
	que otro usuario del sistema pueda leerlo)."""
	fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
	try:
		os.write(fd, content)
	finally:
		os.close(fd)
	os.chmod(path, 0o600)


def pem_paths(company: str, purpose: str) -> tuple[str, str]:
	"""Rutas absolutas (site) de los PEM de la credencial (private/es_keys).

	Ancladas al bench real vía absolute_site_path (get_bench_path):
	INDEPENDIENTES del CWD del proceso — los workers corren con CWDs mixtos
	(raíz del bench y sites/) y una ruta relativa haría que la TLS mutua
	resolviera el PEM distinto (o no lo encontrara) según quién drenara.
	"""
	cert, key = pem_names(company, purpose)
	return (
		absolute_site_path(*KEYS_DIR, cert),
		absolute_site_path(*KEYS_DIR, key),
	)


class ESAEATCredential(Document):
	def autoname(self):
		# Nombre determinista y seguro para URL (scrub evita '/' y otros
		# caracteres problemáticos en docnames): {empresa}-{propósito}.
		if self.company and self.purpose:
			self.name = f"{frappe.scrub(self.company)}-{frappe.scrub(self.purpose)}"

	def validate(self):
		self._validate_unique_pair()
		if self.enabled and self.cert_file:
			self._extract_pem()
			self._ensure_private_file()
		else:
			self._clean_pem()

	def on_trash(self):
		self._clean_pem()

	def get_days_remaining(self) -> int | None:
		"""Días hasta el fin de vigencia (negativos si ya caducó), para el
		indicador de caducidad del list view / form (spec 04 §15)."""
		return get_days_remaining(self.valid_until)

	# --- extracción y limpieza de PEM ---

	def _validate_unique_pair(self) -> None:
		"""Una credencial por (empresa, propósito), y el par es INMUTABLE: el
		docname y los PEM están claveados por él. Cambiarlo dejaría nombres y
		claves inconsistentes — para otro par se crea otra credencial."""
		if not self.is_new():
			previous = frappe.db.get_value(self.doctype, self.name, ["company", "purpose"], as_dict=True)
			if (previous.company, previous.purpose) != (self.company, self.purpose):
				frappe.throw(
					"No se puede cambiar la compañía o el propósito de una credencial"
					" existente: el par (empresa, propósito) identifica la credencial"
					" (nombre y archivos PEM claveados por él). Remedio: cree una"
					" credencial nueva para el nuevo par y borre esta si ya no procede."
				)

		filters = {"company": self.company, "purpose": self.purpose}
		if not self.is_new():
			filters["name"] = ("!=", self.name)
		duplicate = frappe.db.exists("ES AEAT Credential", filters)
		if duplicate:
			frappe.throw(
				f"Ya existe una credencial AEAT de {self.company} para el propósito"
				f" {self.purpose} ({duplicate}). Remedio: edite esa credencial en lugar"
				" de crear una duplicada — un certificado por (empresa, propósito)."
			)

	def _extract_pem(self) -> None:
		"""Extrae certificado y clave del contenedor PKCS#12 (p12/pfx) a PEM en
		private/files y parsea la vigencia (patrón de la referencia:
		cryptography.load_pkcs12)."""
		from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
		from cryptography.hazmat.primitives.serialization.pkcs12 import load_pkcs12

		password = self.get_password("cert_password", raise_exception=False)
		if not password:
			frappe.throw(
				"La contraseña del certificado es obligatoria para extraer los PEM."
				" Remedio: indique la contraseña del certificado PFX/P12 en la"
				" credencial.",
				frappe.ValidationError,
			)

		try:
			p12 = load_pkcs12(self._read_pkcs12(), password.encode("utf-8"))
		except Exception as e:
			frappe.throw(
				f"No se pudo leer el certificado PFX/P12 (¿contraseña incorrecta?): {e}."
				" Remedio: verifique la contraseña y que el archivo subido sea un"
				" contenedor PKCS#12 válido (extensiones .p12 o .pfx).",
				frappe.ValidationError,
			)

		if not p12.cert or not p12.key:
			frappe.throw(
				"El archivo PFX/P12 no contiene certificado o clave privada."
				" Remedio: suba un certificado que incluya ambos (certificado + clave).",
				frappe.ValidationError,
			)

		certificate = p12.cert.certificate
		cert_pem = certificate.public_bytes(Encoding.PEM)
		key_pem = p12.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

		keys_dir()
		cert_path, key_path = pem_paths(self.company, self.purpose)
		write_secret(cert_path, cert_pem)
		write_secret(key_path, key_pem)

		self.valid_from = certificate.not_valid_before_utc.date()
		self.valid_until = certificate.not_valid_after_utc.date()

	def _read_pkcs12(self) -> bytes:
		"""Lee el contenedor PKCS#12 (p12/pfx) desde private/files (File doc o
		ruta directa del Attach)."""
		path = self._file_path(self.cert_file)
		if not os.path.exists(path):
			frappe.throw(
				f"No se encontró el certificado PFX/P12 en {self.cert_file}."
				" Remedio: vuelva a subirlo en la credencial.",
				frappe.ValidationError,
			)
		with open(path, "rb") as f:
			return f.read()

	@staticmethod
	def _file_path(file_url: str) -> str:
		"""Resuelve un Attach a ruta física: vía File doc (resuelve tanto
		/private/files como /files) con fallback a private/files por nombre."""
		file_doc = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if file_doc:
			return frappe.get_doc("File", file_doc).get_full_path()
		return absolute_site_path("private", "files", os.path.basename(file_url))

	def _ensure_private_file(self) -> None:
		"""El certificado PFX/P12 subido debe ser privado: si se subió público,
		se privatiza (contiene la identidad fiscal de la empresa)."""
		file_doc = frappe.db.get_value("File", {"file_url": self.cert_file}, "name")
		if not file_doc:
			return
		file_doc = frappe.get_doc("File", file_doc)
		if not file_doc.is_private:
			file_doc.is_private = 1
			file_doc.save(ignore_permissions=True)

	def _clean_pem(self) -> None:
		_delete_pem(self.company, self.purpose)


def _delete_pem(company: str | None, purpose: str | None) -> None:
	"""Borra los PEM extraídos de (empresa, propósito), si existen.

	Ignora `company`/`purpose` vacíos (credenciales a medio crear nunca
	escribieron PEM). Ausencia de archivos no es error (limpieza idempotente).
	"""
	if not company or not purpose:
		return
	for path in pem_paths(company, purpose):
		if os.path.exists(path):
			os.remove(path)
