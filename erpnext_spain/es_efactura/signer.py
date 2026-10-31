# Firma XAdES-EPES de Facturae (spec 10 §3) con la política de firma de
# Facturae v3.1. El certificado es el de la empresa (ES AEAT Credential, uno por
# empresa), el mismo que usan VeriFactu y el SII.
#
# Política (facturae.gob.es, «Políticas de firma electrónica», versión 3.1):
# identificador y huella SHA-1 publicados en politica_firma_v3_1_sha1.txt.

from __future__ import annotations

import frappe
from frappe import _

POLICY_IDENTIFIER = (
	"http://www.facturae.es/politica_de_firma_formato_facturae/politica_de_firma_formato_facturae_v3_1.pdf"
)
POLICY_DESCRIPTION = "Política de Firma FacturaE v3.1"
POLICY_DIGEST_SHA1 = "Ohixl6upD6av8N7pEvDABhEL6hM="
SIGNER_ROLE = "emisor"


def credential_for(company: str) -> str:
	from erpnext_spain.aeat.utils import require_credential

	return require_credential(company, "firmar facturas electrónicas")


def sign(root, company: str):
	"""Firma el documento Facturae (firma envolvente) y devuelve el árbol firmado y
	el sujeto del certificado."""
	from cryptography import x509
	from signxml import CanonicalizationMethod, DigestAlgorithm
	from signxml.xades import XAdESDataObjectFormat, XAdESSignaturePolicy, XAdESSigner

	from erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential import pem_paths

	credential = frappe.get_doc("ES AEAT Credential", credential_for(company))
	cert_path, key_path = pem_paths(credential.company)
	try:
		with open(cert_path, "rb") as f:
			cert_pem = f.read()
		with open(key_path, "rb") as f:
			key_pem = f.read()
	except FileNotFoundError:
		frappe.throw(
			_(
				"No se encuentra el certificado extraído de la credencial {0}. Vuelva a guardarla para extraerlo de"
				" nuevo."
			).format(frappe.bold(credential.name))
		)
	certificate = x509.load_pem_x509_certificate(cert_pem)
	signer = XAdESSigner(
		signature_policy=XAdESSignaturePolicy(
			Identifier=POLICY_IDENTIFIER,
			Description=POLICY_DESCRIPTION,
			DigestMethod=DigestAlgorithm.SHA1,
			DigestValue=POLICY_DIGEST_SHA1,
		),
		claimed_roles=[SIGNER_ROLE],
		data_object_format=XAdESDataObjectFormat(Description="Factura electrónica", MimeType="text/xml"),
		c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0,
	)
	signed = signer.sign(root, key=key_pem, cert=[certificate])
	return signed, certificate.subject.rfc4514_string()
