# WSDL y esquemas de la AEAT servidos desde la copia local (spec 01 §8, H7).
#
# Desde zeep 4.3.3, `Settings(forbid_external=True)` bloquea cualquier import
# transitivo por http(s). El WSDL de VeriFactu importa sus XSD con rutas
# relativas (que se vuelven https si el WSDL se descarga) y
# SuministroInformacion.xsd importa xmldsig-core-schema.xsd de w3.org. Para no
# relajar `forbid_external`:
#
# 1. El cliente carga siempre el WSDL incluido en la app cuando la URL
#    configurada es la oficial de la AEAT (`OFFICIAL_WSDLS`): los imports
#    relativos se resuelven contra el directorio local.
# 2. `LocalSchemaTransport` (subclase del Transport de zeep, su punto de
#    extensión documentado) reescribe al cargar cada documento los
#    `schemaLocation` remotos conocidos (`erpnext_spain.schemas.REMOTE_SCHEMAS`)
#    a la copia local. Los ficheros se conservan idénticos a los publicados.

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

from zeep.transports import Transport

from erpnext_spain.schemas import REMOTE_SCHEMAS, VERIFACTU_WSDL

# URL oficial del WSDL → copia incluida en la app. La AEAT publica el mismo WSDL
# de VeriFactu (con los puertos de pruebas y de producción) en las dos
# direcciones: comprobado el 31/10/2026, los seis ficheros coinciden salvo un
# espacio al final de una línea de SuministroLR.xsd en la copia de producción.
_VERIFACTU_PATH = (
	"static_files/common/internet/dep/aplicaciones/es/aeat/tikeV1.0/cont/ws/SistemaFacturacion.wsdl"
)
OFFICIAL_WSDLS: dict[str, Path] = {
	f"https://prewww2.aeat.es/{_VERIFACTU_PATH}": VERIFACTU_WSDL,
	f"https://www2.agenciatributaria.gob.es/{_VERIFACTU_PATH}": VERIFACTU_WSDL,
}

_SCHEMA_LOCATION = re.compile(rb"""schemaLocation\s*=\s*(?P<quote>["'])(?P<url>.*?)(?P=quote)""")


def local_wsdl(wsdl: str) -> str:
	"""Ruta de la copia local si `wsdl` es una URL oficial conocida; si no, `wsdl`
	tal cual (una ruta local o una URL que zeep cargará con `forbid_external`)."""
	local = OFFICIAL_WSDLS.get(wsdl.strip())
	return str(local) if local else wsdl


def rewrite_schema_locations(content: bytes, remote_schemas: dict[str, Path]) -> bytes:
	"""Sustituye en `content` cada `schemaLocation` remoto conocido por la ruta
	absoluta de su copia local. El resto del documento no cambia."""

	def replace(match: re.Match) -> bytes:
		local = remote_schemas.get(match.group("url").decode())
		if local is None:
			return match.group(0)
		return b"schemaLocation=" + quoteattr(str(local)).encode()

	return _SCHEMA_LOCATION.sub(replace, content)


class LocalSchemaTransport(Transport):
	"""Transport de zeep que resuelve los esquemas externos con las copias de la
	app, de modo que el cliente se construye sin red."""

	def __init__(self, *args, remote_schemas: dict[str, Path] | None = None, **kwargs):
		super().__init__(*args, **kwargs)
		self.remote_schemas = dict(REMOTE_SCHEMAS if remote_schemas is None else remote_schemas)

	def load(self, url: str) -> bytes:
		local = self.remote_schemas.get(url)
		content = super().load(str(local) if local else url)
		return rewrite_schema_locations(content, self.remote_schemas)
