# Custom fields del módulo base (spec 01 §5): sección «Contabilidad y
# fiscalidad» en la pestaña de la app en Company (es_tab, creada por
# nif/setup.py). Va antes de la sección VeriFactu.
#
# Nombres de las specs → fieldnames (maestro §3):
#   pgc_aplicado → es_pgc_applied · numeracion_fiscal → es_fiscal_numbering
#   modelo_plan → es_chart_model · modelo_cuentas_anuales → es_annual_accounts_model
#   regimen_iva → es_vat_regime · periodicidad_303 → es_vat_return_frequency
#   prorrata_general → es_general_prorata
#   exigir_clasificacion_fiscal → es_require_tax_classification
#   version_datos_iniciales → es_initial_data_version (spec 09 S5)

from __future__ import annotations

COMPANY_FIELDS = [
	{
		"fieldname": "es_accounting_section",
		"label": "Contabilidad y fiscalidad",
		"fieldtype": "Section Break",
		"insert_after": "es_incidents_email",
	},
	{
		"fieldname": "es_pgc_applied",
		"label": "Plan PGC aplicado",
		"fieldtype": "Check",
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "es_accounting_section",
		"description": (
			"Lo marca la acción «Aplicar plan PGC». Activa lo que depende del plan"
			" contable español en esta compañía."
		),
	},
	{
		"fieldname": "es_chart_model",
		"label": "Plan aplicado",
		"fieldtype": "Select",
		"options": "\nNormal\nPYMES",
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "es_pgc_applied",
		"depends_on": "eval:doc.es_pgc_applied",
	},
	{
		"fieldname": "es_initial_data_version",
		"label": "Versión de los datos iniciales",
		"fieldtype": "Int",
		"read_only": 1,
		"no_copy": 1,
		"insert_after": "es_chart_model",
		"depends_on": "eval:doc.es_pgc_applied",
		"description": "Versión de las plantillas, reglas y cuentas de arranque creadas para esta compañía.",
	},
	{
		"fieldname": "es_fiscal_numbering",
		"label": "Numeración fiscal al emitir",
		"fieldtype": "Check",
		"insert_after": "es_initial_data_version",
		"description": (
			"Los borradores de factura de venta no consumen número; al validar reciben el"
			" siguiente número de la serie de su tipo de factura. Todavía sin efecto: hoy la"
			" numeración al emitir solo se aplica con VeriFactu activado."
		),
	},
	{
		"fieldname": "es_accounting_column",
		"fieldtype": "Column Break",
		"insert_after": "es_fiscal_numbering",
	},
	{
		"fieldname": "es_annual_accounts_model",
		"label": "Modelo de cuentas anuales",
		"fieldtype": "Select",
		"options": "PYMES\nAbreviado\nNormal",
		"default": "PYMES",
		"insert_after": "es_accounting_column",
	},
	{
		"fieldname": "es_vat_regime",
		"label": "Régimen de IVA",
		"fieldtype": "Select",
		"options": "General\nCriterio de caja\nRecargo de equivalencia\nSimplificado",
		"default": "General",
		"insert_after": "es_annual_accounts_model",
	},
	{
		"fieldname": "es_vat_return_frequency",
		"label": "Periodicidad del modelo 303",
		"fieldtype": "Select",
		"options": "Trimestral\nMensual",
		"default": "Trimestral",
		"insert_after": "es_vat_regime",
	},
	{
		"fieldname": "es_general_prorata",
		"label": "Prorrata general",
		"fieldtype": "Percent",
		"insert_after": "es_vat_return_frequency",
		"description": "Porcentaje de deducción del IVA soportado. Vacío equivale al 100 %.",
	},
	{
		"fieldname": "es_require_tax_classification",
		"label": "Exigir clasificación fiscal",
		"fieldtype": "Check",
		"insert_after": "es_general_prorata",
		"description": ("Impide validar facturas con líneas de IVA, recargo o retención sin clasificar."),
	},
]

CUSTOM_FIELDS = {"Company": COMPANY_FIELDS}

FIELDS_PER_DOCTYPE = {"Company": [field["fieldname"] for field in COMPANY_FIELDS]}


def setup_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cleanup_custom_fields() -> None:
	"""Contrapartida de limpieza en before_uninstall (R3)."""
	from erpnext_spain.utils.custom_fields import cleanup_custom_fields as _cleanup

	_cleanup(FIELDS_PER_DOCTYPE)
