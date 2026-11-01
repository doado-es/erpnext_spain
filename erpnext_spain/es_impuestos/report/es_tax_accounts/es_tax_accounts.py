# Mapa de cuentas de impuestos: qué impuesto, con su nombre oficial, recoge cada
# cuenta de las plantillas de la compañía.
#
# La clasificación fiscal vive en las filas de las plantillas de impuestos (y en
# las cuentas de las categorías de retención): este informe la reúne por cuenta,
# con el nombre que usan la AEAT y el PGC, y señala lo que no cuadra. Se corrige
# en la plantilla, que es la única fuente.

from collections import defaultdict

import frappe
from frappe import _

from erpnext_spain.es_impuestos.codes import TAX_TYPES

TEMPLATES = {
	"Sales Taxes and Charges Template": ("Sales Taxes and Charges", "sale"),
	"Purchase Taxes and Charges Template": ("Purchase Taxes and Charges", "purchase"),
}

# Prefijo de cuenta del PGC esperado para cada nombre (si lo hay).
EXPECTED_PREFIX = {
	"IVA repercutido": "477",
	"Recargo de equivalencia repercutido": "477",
	"IVA devengado en adquisiciones intracomunitarias": "477",
	"IVA devengado por inversión del sujeto pasivo": "477",
	"IVA soportado deducible en operaciones interiores corrientes": "472",
	"IVA soportado deducible en bienes de inversión": "472",
	"IVA deducible en adquisiciones intracomunitarias": "472",
	"IVA deducible en importaciones": "472",
	"Retenciones e ingresos a cuenta soportados": "473",
	"Retenciones IRPF practicadas": "4751",
}
INTRA = ("Adquisición intracomunitaria de bienes", "Adquisición intracomunitaria de servicios")


def family(name: str) -> str:
	"""Grupo de impuestos que una misma cuenta del PGC puede recoger junto (p. ej. la 4720,
	todo el IVA soportado deducible). Mezclar grupos en una cuenta es un error."""
	if name.startswith("Recargo"):
		return name
	if name.startswith("Retenciones"):
		return name
	if name.startswith(("IVA repercutido", "IVA devengado")):
		return "IVA repercutido o devengado"
	if name == "IVA soportado no deducible":
		return name
	if name.startswith("IVA"):
		return "IVA soportado deducible"
	return name


def official_name(row, side: str) -> str | None:
	"""Nombre oficial del impuesto de una fila de plantilla (None si no está clasificada)."""
	tax_type = row.get("es_tax_type")
	if not tax_type:
		return None
	if tax_type == TAX_TYPES["RE"]:
		return (
			"Recargo de equivalencia repercutido" if side == "sale" else "Recargo de equivalencia soportado"
		)
	if tax_type == TAX_TYPES["IRPF"]:
		return (
			"Retenciones e ingresos a cuenta soportados" if side == "sale" else "Retenciones IRPF practicadas"
		)
	if tax_type != TAX_TYPES["IVA"]:
		return _("Otro impuesto")
	if side == "sale":
		return "IVA repercutido"
	operation = row.get("es_operation_type")
	if row.get("es_self_assessed"):
		return (
			"IVA devengado en adquisiciones intracomunitarias"
			if operation in INTRA
			else "IVA devengado por inversión del sujeto pasivo"
		)
	if row.get("es_deductibility") == "No deducible":
		return "IVA soportado no deducible"
	if operation in INTRA:
		return "IVA deducible en adquisiciones intracomunitarias"
	if operation == "Importación":
		return "IVA deducible en importaciones"
	if row.get("es_deductibility") == "Bien de inversión":
		return "IVA soportado deducible en bienes de inversión"
	return "IVA soportado deducible en operaciones interiores corrientes"


def execute(filters: dict | None = None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Elija la compañía."))
	frappe.has_permission("Account", "read", throw=True)
	columns = [
		{
			"fieldname": "account",
			"label": _("Cuenta"),
			"fieldtype": "Link",
			"options": "Account",
			"width": 280,
		},
		{
			"fieldname": "official_name",
			"label": _("Impuesto (nombre oficial)"),
			"fieldtype": "Data",
			"width": 330,
		},
		{"fieldname": "rates", "label": _("Tipos"), "fieldtype": "Data", "width": 110},
		{"fieldname": "templates", "label": _("Usada en"), "fieldtype": "Data", "width": 320},
		{"fieldname": "issue", "label": _("Revisar"), "fieldtype": "Data", "width": 320},
	]
	return columns, tax_accounts(filters.company)


def tax_accounts(company: str) -> list[dict]:
	usage: dict[tuple, dict] = {}
	unclassified: dict[str, set] = defaultdict(set)
	for template_doctype, (row_doctype, side) in TEMPLATES.items():
		templates = frappe.get_all(template_doctype, filters={"company": company}, pluck="name")
		if not templates:
			continue
		fields = ["parent", "account_head", "rate", "es_tax_type", "es_operation_type"]
		if side == "purchase":
			fields += ["es_deductibility", "es_self_assessed"]
		for row in frappe.get_all(
			row_doctype,
			filters={"parenttype": template_doctype, "parent": ["in", templates]},
			fields=fields,
			order_by="parent, idx",
		):
			name = official_name(row, side)
			if not name:
				unclassified[row.account_head].add(row.parent)
				continue
			entry = usage.setdefault((row.account_head, name), {"rates": set(), "templates": set()})
			entry["rates"].add(row.rate)
			entry["templates"].add(row.parent)

	for row in frappe.get_all(
		"Tax Withholding Account",
		filters={"company": company, "parenttype": "Tax Withholding Category"},
		fields=["parent", "account"],
	):
		entry = usage.setdefault(
			(row.account, "Retenciones IRPF practicadas"), {"rates": set(), "templates": set()}
		)
		entry["templates"].add(_("Categoría {0}").format(row.parent))

	families_per_account = defaultdict(set)
	for account, name in usage:
		families_per_account[account].add(family(name))
	numbers = dict(
		frappe.get_all(
			"Account",
			filters={"name": ["in", list({a for a, _n in usage} | set(unclassified))]},
			fields=["name", "account_number"],
			as_list=True,
		)
	)

	result = []
	for (account, name), entry in sorted(
		usage.items(), key=lambda item: (numbers.get(item[0][0]) or "", item[0])
	):
		issues = []
		prefix = EXPECTED_PREFIX.get(name)
		if prefix and numbers.get(account) and not str(numbers[account]).startswith(prefix):
			issues.append(_("Se espera una cuenta {0}").format(prefix))
		if len(families_per_account[account]) > 1:
			issues.append(_("La cuenta mezcla impuestos de distinto tipo"))
		result.append(
			{
				"account": account,
				"official_name": name,
				"rates": ", ".join(
					f"{rate:g} %" for rate in sorted(r for r in entry["rates"] if r is not None)
				),
				"templates": ", ".join(sorted(entry["templates"])),
				"issue": "; ".join(issues),
			}
		)
	for account, templates in sorted(unclassified.items()):
		result.append(
			{
				"account": account,
				"official_name": "",
				"rates": "",
				"templates": ", ".join(sorted(templates)),
				"issue": _("Filas sin tipo de impuesto: clasifíquelas en la plantilla"),
			}
		)
	return result
