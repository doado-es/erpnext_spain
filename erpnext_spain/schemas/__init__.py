# Esquemas externos incluidos en la app (spec 01 §8, H7).
#
# Los WSDL y XSD de la AEAT y los esquemas del W3C que importan se resuelven
# siempre desde estas copias locales: sin red al construir clientes SOAP ni al
# validar XML. Los ficheros se guardan tal como los publica su autor; las
# referencias remotas que contienen (p. ej. el import de xmldsig en
# SuministroInformacion.xsd) se redirigen a la copia local al cargarlos
# (`REMOTE_SCHEMAS` y `erpnext_spain.es_aeat.wsdl.LocalSchemaTransport`).
#
# Al actualizar un fichero por un cambio del publicador, se sustituye entero y
# se ejecutan los tests de contrato (es_verifactu/tests/test_contrato_wsdl.py,
# es_aeat/tests/test_wsdl.py, es_efactura/tests/test_facturae.py).

from __future__ import annotations

from pathlib import Path

SCHEMA_ROOT = Path(__file__).resolve().parent

# Firma XML (W3C), importado por los XSD de VeriFactu y de Facturae.
XMLDSIG_SCHEMA = SCHEMA_ROOT / "w3c" / "xmldsig-core-schema.xsd"

# WSDL de VeriFactu (tikeV1.0) con sus cinco XSD en el mismo directorio.
VERIFACTU_WSDL = SCHEMA_ROOT / "aeat" / "verifactu" / "SistemaFacturacion.wsdl"

# URL remota (tal como aparece en `schemaLocation`) → copia local.
REMOTE_SCHEMAS: dict[str, Path] = {
	"http://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd": XMLDSIG_SCHEMA,
	"https://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd": XMLDSIG_SCHEMA,
}
