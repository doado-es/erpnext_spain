app_name = "erpnext_spain"
app_title = "ERPNext Spain"
app_publisher = "doado"
app_description = "Spain ERPNext localization"
app_email = "info@doado.es"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe/erpnext"]

# Document Events
# ---------------
# Los handlers salen pronto si la compañía no usa la función correspondiente.

doc_events = {
	"Account": {"validate": "erpnext_spain.es_contabilidad.account.validate"},
	"Customer": {"validate": "erpnext_spain.es_nif.party.validate"},
	"Address": {"validate": "erpnext_spain.es_impuestos.tax_category.set_address_category"},
	# Filas de la plantilla del artículo replicadas para recargo, retención y
	# adquisición intracomunitaria.
	"Item": {"validate": "erpnext_spain.es_impuestos.item_tax.mirror_rows"},
	"Item Group": {"validate": "erpnext_spain.es_impuestos.item_tax.mirror_rows"},
	"Supplier": {
		"validate": [
			"erpnext_spain.es_nif.party.validate",
			"erpnext_spain.es_impuestos.tax_category.set_supplier_category",
			"erpnext_spain.es_retenciones.withholding.validate_supplier",
		]
	},
	"Purchase Invoice": {
		"validate": [
			"erpnext_spain.es_retenciones.withholding.validate_purchase_invoice",
			"erpnext_spain.es_iva.rows.validate",
		],
		"on_submit": "erpnext_spain.es_sii.outbox.on_submit",
		"on_cancel": "erpnext_spain.es_sii.outbox.on_cancel",
		"onload": "erpnext_spain.es_facturacion.fiscal_tab.onload",
	},
	"Payment Entry": {
		"validate": "erpnext_spain.es_retenciones.withholding.validate_payment_entry",
		"on_submit": "erpnext_spain.es_efactura.b2b.payment_changed",
		"on_cancel": "erpnext_spain.es_efactura.b2b.payment_changed",
	},
	"Journal Entry": {
		"on_submit": "erpnext_spain.es_efactura.b2b.payment_changed",
		"on_cancel": "erpnext_spain.es_efactura.b2b.payment_changed",
	},
	"Bank Account": {"validate": "erpnext_spain.es_sepa.bank_account.validate"},
	"Bank Transaction": {"validate": "erpnext_spain.es_bancos.importer.validate_bank_transaction"},
	"Company": {
		# El orden importa: NIF, conflicto SII/VeriFactu y activación de VeriFactu.
		"validate": [
			"erpnext_spain.utils.company.set_default_legal_name",
			"erpnext_spain.es_nif.party.validate",
			"erpnext_spain.es_sii.company.validate",
			"erpnext_spain.es_verifactu.company.validate",
		],
		"on_update": "erpnext_spain.utils.gating.clear_site_pgc_cache",
		"after_insert": "erpnext_spain.es_contabilidad.onboarding.after_insert",
	},
	"Sales Invoice": {
		"autoname": "erpnext_spain.es_verifactu.invoice.autoname",
		"onload": "erpnext_spain.es_facturacion.fiscal_tab.onload",
		"validate": [
			"erpnext_spain.es_facturacion.numbering.validate",
			"erpnext_spain.es_iva.rows.validate",
			"erpnext_spain.es_verifactu.emission.validate",
		],
		"before_submit": [
			"erpnext_spain.es_verifactu.invoice.release_draft_name",
			"erpnext_spain.es_facturacion.numbering.before_submit",
			"erpnext_spain.es_verifactu.emission.before_submit",
		],
		"on_submit": [
			"erpnext_spain.es_verifactu.emission.on_submit",
			"erpnext_spain.es_sii.outbox.on_submit",
			"erpnext_spain.es_efactura.b2b.on_submit",
		],
		"before_cancel": [
			"erpnext_spain.es_efactura.api.block_cancel_if_presented",
			"erpnext_spain.es_verifactu.emission.before_cancel",
		],
		"on_cancel": "erpnext_spain.es_sii.outbox.on_cancel",
	},
}


# Regional overrides de ERPNext: la región es el país de la compañía.
regional_overrides = {
	"Spain": {
		"erpnext.controllers.accounts_controller.validate_regional": (
			"erpnext_spain.es_impuestos.invoice.validate_regional"
		),
	},
}

# Desk JS
# -------

# Avisos en el escritorio (evento realtime «erpnext_spain_notice»), sin bundle.
app_include_js = ["/assets/erpnext_spain/js/notices.js"]

boot_session = "erpnext_spain.utils.gating.boot_session"

doctype_js = {
	"Company": [
		"es_verifactu/public/js/company.js",
		"es_contabilidad/public/js/company.js",
		"es_sii/public/js/company.js",
		"es_aeat/public/js/company_modes.js",
	],
	"Sales Invoice": [
		"es_verifactu/public/js/sales_invoice.js",
		"es_efactura/public/js/sales_invoice.js",
		"es_facturacion/public/js/sales_invoice.js",
		"es_facturacion/public/js/fiscal_tab.js",
	],
	"Purchase Invoice": "es_facturacion/public/js/fiscal_tab.js",
	"Customer": "es_nif/public/js/party.js",
	"Supplier": "es_nif/public/js/party.js",
	"Payment Order": "es_sepa/public/js/payment_order.js",
}

BULK_ACTIONS_JS = "es_facturacion/public/js/bulk_actions.js"
doctype_list_js = {
	"Sales Invoice": ["es_verifactu/public/js/sales_invoice_list.js", BULK_ACTIONS_JS],
	"Delivery Note": BULK_ACTIONS_JS,
	"Purchase Receipt": BULK_ACTIONS_JS,
	"Customer": BULK_ACTIONS_JS,
	"Supplier": BULK_ACTIONS_JS,
	"Purchase Invoice": BULK_ACTIONS_JS,
}

# Métodos de los formatos de impresión (rutas explícitas por función).
jinja = {
	"methods": [
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_qr_url",
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_qr_code",
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_breakup",
		"erpnext_spain.es_verifactu.utils.jinja.get_es_display_name",
		"erpnext_spain.es_verifactu.utils.jinja.get_es_legal_name",
		"erpnext_spain.es_facturacion.printing.get_es_tax_summary",
		"erpnext_spain.es_facturacion.printing.get_es_rectified_reference",
	],
}

# Asistente de configuración: pantalla y etapa del Plan General Contable.
setup_wizard_requires = "assets/erpnext_spain/js/setup_wizard.js"
setup_wizard_stages = "erpnext_spain.es_contabilidad.onboarding.get_setup_stages"

# Installation / Migration
# ------------------------
# Custom fields por código e idempotentes: se crean en after_install y after_migrate.

after_install = "erpnext_spain.install.after_install"
after_migrate = "erpnext_spain.install.after_migrate"
before_uninstall = "erpnext_spain.install.before_uninstall"
# Custom fields de apps opcionales (p. ej. HRMS) instaladas después.
after_app_install = "erpnext_spain.install.after_app_install"

# Scheduler Events
# ----------------

scheduler_events = {
	"hourly": [
		"erpnext_spain.es_efactura.b2b.communicate_payments",
	],
	"daily": [
		"erpnext_spain.es_aeat.tasks.daily",
		"erpnext_spain.es_verifactu.tasks.daily",
		"erpnext_spain.es_facturacion.collection.flag_doubtful_candidates",
		"erpnext_spain.es_bancos.aggregator.warn_expiring_consents",
		"erpnext_spain.es_sii.outbox.warn_deadlines",
	],
	"cron": {
		"* * * * *": ["erpnext_spain.es_verifactu.tasks.drain_outbox"],
		"0 */6 * * *": ["erpnext_spain.es_bancos.aggregator.sync_all"],
		"*/15 * * * *": ["erpnext_spain.es_sii.outbox.drain_outbox"],
	},
}

# Configuración y registros legales que no se borran con las transacciones de la compañía.
company_data_to_be_ignored = [
	"ES AEAT Credential",
	"ES Sii Record",
	"ES Leased Property",
	"ES Invoice Series",
	"ES Verifactu Notification Role",
	"ES Verifactu Billing Record",
	"ES Bank Aggregator",
]

# Registros históricos que no bloquean el borrado de documentos de negocio.
ignore_links_on_delete = [
	"ES AEAT Response",
	"ES AEAT Response Line",
	"ES Verifactu Billing Record",
]

# Protección de datos: la contraseña del certificado se oculta al exportar.
user_data_fields = [
	{"doctype": "ES AEAT Credential", "filter_by": "owner", "redact_fields": ["cert_password"]},
]
