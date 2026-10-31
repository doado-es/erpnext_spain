# Catálogos de Facturae 3.2.x (esquema oficial, schemas/Facturaev3_2_2.xsd) y
# tablas auxiliares: provincias por código postal y códigos de país ISO alfa-3.

from __future__ import annotations

import functools
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
SCHEMA_FILES = {"3.2.2": SCHEMA_DIR / "Facturaev3_2_2.xsd"}
NAMESPACES = {"3.2.2": "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"}
DEFAULT_VERSION = "3.2.2"


# Rectificativas: motivo (ReasonCodeType) con el texto fijo que exige el esquema
# (ReasonDescriptionType) y método de corrección (CorrectionMethodType).
REASONS = {
	"01": "Número de la factura",
	"02": "Serie de la factura",
	"03": "Fecha expedición",
	"04": "Nombre y apellidos/Razón Social-Emisor",
	"05": "Nombre y apellidos/Razón Social-Receptor",
	"06": "Identificación fiscal Emisor/obligado",
	"07": "Identificación fiscal Receptor",
	"08": "Domicilio Emisor/Obligado",
	"09": "Domicilio Receptor",
	"10": "Detalle Operación",
	"11": "Porcentaje impositivo a aplicar",
	"12": "Cuota tributaria a aplicar",
	"13": "Fecha/Periodo a aplicar",
	"14": "Clase de factura",
	"15": "Literales legales",
	"16": "Base imponible",
	"80": "Cálculo de cuotas repercutidas",
	"81": "Cálculo de cuotas retenidas",
	"82": "Base imponible modificada por devolución de envases / embalajes",
	"83": "Base imponible modificada por descuentos y bonificaciones",
	"84": "Base imponible modificada por resolución firme, judicial o administrativa",
	"85": "Base imponible modificada cuotas repercutidas no satisfechas. Auto de declaración de concurso",
}
# CorrectionMethod de Facturae a partir del método de rectificación de la factura
# (es_rectification_method, un solo campo para Facturae y VeriFactu). Los códigos
# 03 (descuento por volumen) y 04 (autorizadas por la AEAT) no se emiten.
CORRECTION_METHOD_BY_RECTIFICATION = {"Por diferencias": "02", "Por sustitución": "01"}

CORRECTION_METHODS = {
	"01": "Rectificación íntegra",
	"02": "Rectificación por diferencias",
	"03": "Rectificación por descuento por volumen de operaciones durante un periodo",
	"04": "Autorizadas por la Agencia Tributaria",
}

UNITS = {
	"01": "Unidades",
	"02": "Horas",
	"03": "Kilogramos",
	"04": "Litros",
	"05": "Otros",
	"06": "Cajas",
	"18": "Docenas",
	"21": "Gramos",
	"22": "Kilómetros",
	"25": "Metros",
	"28": "Paquetes",
	"33": "Metro cúbico",
	"36": "Kilovatio por hora",
}
DEFAULT_UNIT = "01"

PAYMENT_MEANS = {
	"01": "Al contado",
	"02": "Recibo domiciliado",
	"03": "Recibo",
	"04": "Transferencia",
	"05": "Letra aceptada",
	"11": "Cheque",
	"14": "Compensación",
	"19": "Pago mediante tarjeta",
}
DEFAULT_PAYMENT_MEANS = "04"
MEANS_WITH_IBAN = ("02", "04")

# Centros administrativos DIR3 de FACe: rol Facturae de cada código.
DIR3_ROLES = {
	"es_dir3_accounting_office": ("01", "Oficina contable"),
	"es_dir3_managing_body": ("02", "Órgano gestor"),
	"es_dir3_processing_unit": ("03", "Unidad tramitadora"),
	"es_dir3_proposing_body": ("04", "Órgano proponente"),
}

# Provincia por los dos primeros dígitos del código postal. Facturae limita el
# campo a 20 caracteres.
PROVINCES = {
	"01": "Araba/Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila",
	"06": "Badajoz", "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres",
	"11": "Cádiz", "12": "Castellón", "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña",
	"16": "Cuenca", "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
	"21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León", "25": "Lleida",
	"26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
	"31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas",
	"36": "Pontevedra", "37": "Salamanca", "38": "S.C. Tenerife", "39": "Cantabria", "40": "Segovia",
	"41": "Sevilla", "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo",
	"46": "Valencia", "47": "Valladolid", "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza",
	"51": "Ceuta", "52": "Melilla",
}  # fmt: skip

EU_COUNTRIES = {
	"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "GR", "ES", "FI", "FR", "HR", "HU",
	"IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
}  # fmt: skip


def province_for(postcode: str | None) -> str | None:
	return PROVINCES.get((postcode or "").strip()[:2])


@functools.cache
def schema_countries(version: str = DEFAULT_VERSION) -> frozenset[str]:
	"""Códigos alfa-3 que admite el esquema (CountryType)."""
	from lxml import etree

	xs = "{http://www.w3.org/2001/XMLSchema}"
	root = etree.parse(str(SCHEMA_FILES[version])).getroot()
	for simple_type in root.iter(xs + "simpleType"):
		if simple_type.get("name") == "CountryType":
			return frozenset(e.get("value") for e in simple_type.iter(xs + "enumeration"))
	return frozenset()


@functools.cache
def alpha3(alpha2: str | None) -> str | None:
	"""ISO 3166 alfa-2 → alfa-3 admitido por Facturae (datos CLDR de Babel)."""
	if not alpha2:
		return None
	from babel.core import get_global

	code = alpha2.upper()
	allowed = schema_countries()
	for alias, targets in get_global("territory_aliases").items():
		if len(alias) == 3 and alias.isalpha() and code in targets and alias in allowed:
			return alias
	return None
