# Helpers de test de la capa AEAT: generación de p12 autofirmado con
# `cryptography` y escritura/limpieza de archivos en private/files.
#
# NOTA: los archivos físicos NO se revierten con la transacción del test —
# cada clase de test limpia con addClassCleanup lo que escribe en disco.

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta, timezone

import frappe

from erpnext_spain.tests.fixtures import (
	ensure_sif_identity,
	ensure_test_company,
	ensure_test_customer,
	ensure_test_item,
)


def generate_p12(
	password: bytes = b"es-test-pass",
	days_from: int = 5,
	days_to: int = 25,
) -> tuple[bytes, datetime, datetime]:
	"""Genera un p12 autofirmado y devuelve (bytes, not_valid_before, not_valid_after) UTC."""
	from cryptography import x509
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import rsa
	from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
	from cryptography.hazmat.primitives.serialization.pkcs12 import serialize_key_and_certificates
	from cryptography.x509.oid import NameOID

	now = datetime.now(UTC)
	start = now - timedelta(days=days_from)
	end = now + timedelta(days=days_to)

	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Spain Compliance Test")])
	cert = (
		x509.CertificateBuilder()
		.subject_name(name)
		.issuer_name(name)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(start)
		.not_valid_after(end)
		.sign(key, hashes.SHA256())
	)

	p12 = serialize_key_and_certificates(
		name=b"es-test",
		key=key,
		cert=cert,
		cas=None,
		encryption_algorithm=BestAvailableEncryption(password),
	)
	return p12, start, end


def write_private_p12(name: str, content: bytes) -> str:
	"""Escribe un archivo en private/files y devuelve su file_url de Attach.

	Ruta ABSOLUTA (absolute_site_path): los tests deben ser cwd-proof igual
	que el código de producción que luego lee estos archivos."""
	from erpnext_spain.aeat.utils import absolute_site_path

	path = absolute_site_path("private", "files", name)
	with open(path, "wb") as f:
		f.write(content)
	return f"/private/files/{name}"


def delete_private_file(file_url: str) -> None:
	"""Borra de disco un archivo de private/files dado su file_url."""
	from erpnext_spain.aeat.utils import absolute_site_path

	path = absolute_site_path("private", "files", os.path.basename(file_url))
	if os.path.exists(path):
		os.remove(path)


def clean_pem(company: str, purpose: str) -> None:
	"""Borra los PEM extraídos de (empresa, propósito) si quedaron en disco."""
	from erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential import pem_paths

	for path in pem_paths(company, purpose):
		if os.path.exists(path):
			os.remove(path)


def test_company() -> str:
	"""Compañía española propia de los tests (fixture idempotente, H8).

	Asegura también el cliente, el artículo y la identidad SIF de test, que
	usan todos los tests de facturación: así basta con llamar a esta función
	en `setUpClass` para no depender de los datos del sitio."""
	company = ensure_test_company()
	ensure_test_customer()
	ensure_test_item()
	ensure_sif_identity()
	return company
