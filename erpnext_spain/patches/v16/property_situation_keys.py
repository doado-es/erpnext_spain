# Situación del inmueble arrendado: las claves antiguas seguían al 347 (2 = País
# Vasco o Navarra, 3 = sin referencia, 4 = extranjero); las nuevas distinguen
# País Vasco y Navarra, como pide el 180. La antigua «2» pasa a País Vasco:
# revise los inmuebles de Navarra.

import frappe

OLD_TO_NEW = {
	"2 - En el País Vasco o Navarra": "2 - Con referencia catastral en el País Vasco",
	"3 - Sin referencia catastral": "4 - Sin referencia catastral",
	"4 - En el extranjero": "5 - En el extranjero",
}


def execute():
	for old, new in OLD_TO_NEW.items():
		frappe.db.set_value("ES Leased Property", {"situation": old}, "situation", new, update_modified=False)
