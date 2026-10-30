# Catálogos fiscales comunes (spec 03 §1). Los usan la clasificación de las
# líneas de impuesto, el Registro Fiscal IVA, VeriFactu, el SII y los modelos.
#
# Los códigos de calificación, exención y clave de régimen son los del esquema
# de VeriFactu de la AEAT (SuministroInformacion.xsd, versionado en
# es_verifactu/tests/data/wsdl/): CalificacionOperacionType (S1, S2, N1, N2),
# OperacionExentaType (E1-E8) e IdOperacionesTrascendenciaTributariaType.
# El esquema admite además E7 y E8 y la clave 21, cuyo significado no está en el
# XSD; no se ofrecen hasta verificarlos en la documentación de la AEAT.

from __future__ import annotations

TAX_TYPES = {
	"IVA": "IVA",
	"RE": "Recargo de equivalencia",
	"IRPF": "Retención IRPF",
	"OTRO": "Otro",
}

# Calificación de la operación (S/N) o causa de exención (E). En el esquema de la
# AEAT son elementos distintos y excluyentes; aquí se guardan en un solo campo.
VAT_CLASSIFICATIONS = {
	"S1": "Sujeta y no exenta, sin inversión del sujeto pasivo",
	"S2": "Sujeta y no exenta, con inversión del sujeto pasivo",
	"N1": "No sujeta (artículos 7, 14 y otros)",
	"N2": "No sujeta por reglas de localización",
	"E1": "Exenta por el artículo 20",
	"E2": "Exenta por el artículo 21 (exportaciones)",
	"E3": "Exenta por el artículo 22",
	"E4": "Exenta por los artículos 23 y 24",
	"E5": "Exenta por el artículo 25 (entregas intracomunitarias)",
	"E6": "Exenta por otros",
}
EXEMPT = tuple(code for code in VAT_CLASSIFICATIONS if code.startswith("E"))

OPERATION_TYPES = (
	"Interior",
	"Entrega intracomunitaria",
	"Adquisición intracomunitaria de bienes",
	"Adquisición intracomunitaria de servicios",
	"Importación",
	"Exportación",
	"Servicios a/desde fuera de la UE",
)

DEDUCTIBILITY = ("Corriente", "Bien de inversión", "No deducible")

# Claves de régimen especial o trascendencia (lista L8A de VeriFactu y SII)
# **[verificar textos contra la Orden HAC/1177/2024]**.
REGIME_KEYS = {
	"01": "Operación de régimen general",
	"02": "Exportación",
	"03": "Régimen especial de bienes usados, objetos de arte, antigüedades y objetos de colección",
	"04": "Régimen especial del oro de inversión",
	"05": "Régimen especial de las agencias de viajes",
	"06": "Régimen especial del grupo de entidades en IVA (nivel avanzado)",
	"07": "Régimen especial del criterio de caja",
	"08": "Operaciones sujetas al IPSI o al IGIC",
	"09": "Servicios de agencias de viajes que actúan como mediadoras",
	"10": "Cobros por cuenta de terceros",
	"11": "Arrendamiento de local de negocio",
	"14": "IVA pendiente de devengo en certificaciones de obra a Administraciones Públicas",
	"15": "IVA pendiente de devengo en operaciones de tracto sucesivo",
	"17": "Régimen de ventanilla única (OSS / IOSS)",
	"18": "Recargo de equivalencia",
	"19": "Régimen especial de la agricultura, ganadería y pesca",
	"20": "Régimen simplificado",
}
DEFAULT_REGIME_KEY = "01"

WITHHOLDING_KEYS = (
	"Trabajo",
	"Actividades profesionales",
	"Arrendamiento de inmuebles",
	"Capital mobiliario",
	"Otras",
)


def options(values) -> str:
	"""Opciones de un campo Select: una línea vacía y los códigos."""
	return "\n" + "\n".join(values)


def describe(catalog: dict) -> str:
	return "; ".join(f"{code}: {label}" for code, label in catalog.items())
