# Copyright (c) 2026, ct.galega and contributors
# For license information, please see license.txt

# Credencial AEAT: un certificado por empresa (spec 13 §2, revisión del 31/10/2026),
# compartido por VeriFactu, el SII y la firma de Facturae.
#
# Extracción PFX/P12 (contenedor PKCS#12)→PEM al validar (patrón de la
# referencia): los PEM viven en sites/<sitio>/private/es_keys (H3, spec 01 §8):
# fuera de private/files, así que no entran en las copias de ficheros de
# `bench backup --with-files`, con el directorio en 0700 y los ficheros en 0600,
# nombres claveados por el nombre de la credencial (no cambia aunque se
# renombre la compañía) y solo accesibles server-side. PFX y P12 son el
# MISMO contenedor PKCS#12 (estructura ASN.1 idéntica, extensión distinta) —
# el PFX es el que entregan habitualmente las CA españolas (FNMT, Camerfirma),
# y cryptography.load_pkcs12 lo lee sin distinción. Se CONSERVA el password
# (decisión del spec: permite re-extraer/rotar sin re-subir el archivo; la
# referencia lo borraba).
#
# Indicador de días restantes para el list view / form (spec 04 §15): el
# controller expone `get_days_remaining()`; el job diario de caducidad vive en
# erpnext_spain/es_aeat/tasks.py.

from __future__ import annotations

import os

import frappe
from frappe.model.document import Document

from erpnext_spain.es_aeat.utils import absolute_site_path, get_days_remaining


def pem_names(credential: str) -> tuple[str, str]:
	"""Nombres de los PEM extraídos, claveados por el nombre de la credencial.

	No por la compañía: el nombre de la credencial se fija al crearla y no cambia
	si después se renombra la compañía (el enlace `company` sí cambia)."""
	base = frappe.scrub(credential)
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


def pem_paths(credential: str) -> tuple[str, str]:
	"""Rutas absolutas (site) de los PEM de la credencial (private/es_keys).

	Ancladas al bench real vía absolute_site_path (get_bench_path):
	INDEPENDIENTES del CWD del proceso — los workers corren con CWDs mixtos
	(raíz del bench y sites/) y una ruta relativa haría que la TLS mutua
	resolviera el PEM distinto (o no lo encontrara) según quién drenara.
	"""
	cert, key = pem_names(credential)
	return (
		absolute_site_path(*KEYS_DIR, cert),
		absolute_site_path(*KEYS_DIR, key),
	)


DOCTYPE = "ES AEAT Credential"
PRIVATE_FILES = "/private/files/"


def validate_attached_file(doc: Document, method: str | None = None) -> None:
	"""doc_event `before_validate` de File: el certificado de una credencial no
	puede ser público, ni al subirlo ni después (antes de que File mueva el
	archivo a public/files al cambiar `is_private`)."""
	if doc.attached_to_doctype != DOCTYPE or doc.is_private:
		return
	frappe.throw(
		"El certificado de la credencial AEAT tiene que ser un archivo privado: contiene la"
		" clave de firma de la empresa. Remedio: súbalo de nuevo desde la credencial"
		" (se guarda como privado) y no lo marque como público.",
		frappe.PermissionError,
	)


class ESAEATCredential(Document):
	def validate(self):
		self._validate_unique_company()
		if self.cert_file:
			self._validate_private_file()
		if self.enabled and self.cert_file:
			self._extract_pem()
		else:
			self._clean_pem()

	def on_trash(self):
		self._clean_pem()

	def get_days_remaining(self) -> int | None:
		"""Días hasta el fin de vigencia (negativos si ya caducó), para el
		indicador de caducidad del list view / form (spec 04 §15)."""
		return get_days_remaining(self.valid_until)

	# --- extracción y limpieza de PEM ---

	def _validate_unique_company(self) -> None:
		"""Un certificado por empresa. La compañía no cambia (`set_only_once`): el
		nombre y los PEM van claveados por ella."""
		filters = {"company": self.company}
		if not self.is_new():
			filters["name"] = ("!=", self.name)
		duplicate = frappe.db.exists("ES AEAT Credential", filters)
		if duplicate:
			frappe.throw(
				f"Ya existe la credencial AEAT de {self.company} ({duplicate}). Remedio: edite esa"
				" credencial (por ejemplo, para subir el certificado renovado) en lugar de crear otra:"
				" VeriFactu, el SII y Facturae usan el mismo certificado de la empresa."
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
		cert_path, key_path = pem_paths(self.name)
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

	def _validate_private_file(self) -> None:
		"""El certificado PFX/P12 tiene que estar en private/files. No se privatiza
		en silencio: un archivo subido como público ya ha estado accesible sin
		sesión, y hay que saberlo (y renovar el certificado si procede)."""
		if self.cert_file.startswith(PRIVATE_FILES):
			return
		frappe.throw(
			f"El certificado {self.cert_file} es un archivo público. Remedio: bórrelo de"
			" Archivos y súbalo de nuevo desde la credencial (se guarda como privado). Si"
			" ha estado público, valore pedir a la entidad emisora un certificado nuevo.",
			frappe.ValidationError,
		)

	def _clean_pem(self) -> None:
		_delete_pem(self.name)


def _delete_pem(credential: str | None) -> None:
	"""Borra los PEM extraídos de la credencial, si existen.

	Ignora `credential` vacío (credenciales a medio crear nunca escribieron PEM).
	Ausencia de archivos no es error (limpieza idempotente).
	"""
	if not credential:
		return
	for path in pem_paths(credential):
		if os.path.exists(path):
			os.remove(path)
