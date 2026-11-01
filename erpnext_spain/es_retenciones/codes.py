# Catálogo de retenciones practicadas (spec 08 §2-§3).
#
# Tipos según el cuadro de la AEAT aplicable desde el 10/09/2026 (spec 08 §2).
# **[revisar]** con el cuadro vigente y con el asesor: tipos, claves y subclaves
# del modelo 190 (orden vigente) y la reducción del 60 % (art. 68.4 LIRPF) por
# categoría. El grupo «General» es la fila SIN grupo (spec 08 §1).

GROUP_START = "Inicio de actividad"
GROUP_REDUCTION = "Reducción 68.4 LIRPF"
GROUP_SMALL_ENTITY = "Entidad con cifra de negocios inferior a 100.000 €"
GROUPS = (GROUP_START, GROUP_REDUCTION, GROUP_SMALL_ENTITY)

# Vigencia de las filas de tipo. Un cambio legal cierra la fila vigente y añade
# otra con un patch idempotente (spec 08 §3).
FROM_DATE = "2015-07-12"
TO_DATE = "2099-12-31"

PROFESSIONAL = "Actividades profesionales"
PROFESSIONAL_7 = "Actividades profesionales — 7 % por actividad"
MODULES = "Módulos (estimación objetiva)"
AGRICULTURE = "Actividades agrícolas, ganaderas y forestales"
DIRECTORS = "Consejeros y administradores"
COURSES = "Cursos y conferencias"
LEASING = "Arrendamiento de inmuebles urbanos"

# nombre: modelo trimestral, resumen anual, clave de retención (spec 03),
# clave y subclave del 190 y tipos por grupo (None = General).
CATEGORIES = {
	PROFESSIONAL: {
		"model": "111",
		"key": "Actividades profesionales",
		"key_190": "G",
		"subkey_190": "01",
		"rates": {None: 15, GROUP_START: 7, GROUP_REDUCTION: 6},
	},
	PROFESSIONAL_7: {
		"model": "111",
		"key": "Actividades profesionales",
		"key_190": "G",
		"subkey_190": "02",
		"rates": {None: 7, GROUP_REDUCTION: 2.8},
	},
	MODULES: {
		"model": "111",
		"key": "Otras",
		"key_190": "H",
		"subkey_190": "04",
		"rates": {None: 1, GROUP_REDUCTION: 0.4},
	},
	AGRICULTURE: {
		"model": "111",
		"key": "Otras",
		"key_190": "H",
		"subkey_190": "01",
		"rates": {None: 2, GROUP_REDUCTION: 0.8},
	},
	DIRECTORS: {
		"model": "111",
		"key": "Trabajo",
		"key_190": "E",
		"subkey_190": "",
		"rates": {None: 35, GROUP_SMALL_ENTITY: 19},
	},
	COURSES: {
		"model": "111",
		"key": "Trabajo",
		"key_190": "F",
		"subkey_190": "01",
		"rates": {None: 15, GROUP_REDUCTION: 6},
	},
	LEASING: {
		"model": "115",
		"key": "Arrendamiento de inmuebles",
		"key_190": "",
		"subkey_190": "",
		"rates": {None: 19, GROUP_REDUCTION: 7.6},
	},
}

TAX_MODELS = ("111", "115")
WITHHOLDING_ACCOUNT = "4751"  # Hacienda Pública, acreedora por retenciones practicadas

# Situación del inmueble arrendado. Los modelos usan claves distintas: el 180
# separa País Vasco y Navarra; el 347, no, y tiene una para el extranjero
# (diseños de registro del 180 de 2023 y del 347 de 2025).
PROPERTY_SITUATIONS = (
	"1 - Con referencia catastral en territorio común",
	"2 - Con referencia catastral en el País Vasco",
	"3 - Con referencia catastral en Navarra",
	"4 - Sin referencia catastral",
	"5 - En el extranjero",
)
SITUATION_180 = {"1": "1", "2": "2", "3": "3", "4": "4"}
SITUATION_347 = {"1": "1", "2": "2", "3": "2", "4": "3", "5": "4"}
