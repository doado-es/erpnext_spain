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
# Validación de NIF español en el ciclo de vida de terceros y compañía
# (spec 14 §2). Early-exits baratos dentro del handler (doc 12 §2).

doc_events = {
	# Número y rama de las cuentas nuevas en compañías PGC (spec 02 §4).
	"Account": {"validate": "erpnext_spain.es_contabilidad.account.validate"},
	"Customer": {"validate": "erpnext_spain.nif.party.validate"},
	# Categoría de impuestos por país (España, UE, resto) en direcciones y proveedores.
	"Address": {"validate": "erpnext_spain.es_impuestos.tax_category.set_address_category"},
	# Plantilla de impuestos del artículo también para recargo, retención y
	# adquisición intracomunitaria (es_impuestos/item_tax.py).
	"Item": {"validate": "erpnext_spain.es_impuestos.item_tax.mirror_rows"},
	"Item Group": {"validate": "erpnext_spain.es_impuestos.item_tax.mirror_rows"},
	"Supplier": {
		"validate": [
			"erpnext_spain.nif.party.validate",
			"erpnext_spain.es_impuestos.tax_category.set_supplier_category",
			# Grupo de retención con fila de tipo en su categoría (spec 08 §3).
			"erpnext_spain.es_retenciones.withholding.validate_supplier",
		]
	},
	# Retenciones practicadas: clasificación de la fila e inmueble arrendado (spec 08 §3).
	"Purchase Invoice": {
		"validate": [
			"erpnext_spain.es_retenciones.withholding.validate_purchase_invoice",
			# Datos del desglose fiscal congelados en la factura (spec 06).
			"erpnext_spain.es_iva.rows.validate",
		],
		"on_submit": "erpnext_spain.es_sii.outbox.on_submit",
		"on_cancel": "erpnext_spain.es_sii.outbox.on_cancel",
		# Historial de la pestaña «SII / Factura electrónica».
		"onload": "erpnext_spain.es_facturacion.fiscal_tab.onload",
	},
	"Payment Entry": {
		"validate": "erpnext_spain.es_retenciones.withholding.validate_payment_entry",
		# Pago efectivo completo de facturas electrónicas recibidas (spec 10 §5).
		"on_submit": "erpnext_spain.es_efactura.b2b.payment_changed",
		"on_cancel": "erpnext_spain.es_efactura.b2b.payment_changed",
	},
	"Journal Entry": {
		"on_submit": "erpnext_spain.es_efactura.b2b.payment_changed",
		"on_cancel": "erpnext_spain.es_efactura.b2b.payment_changed",
	},
	# Normas bancarias y mandato SEPA en la cuenta (spec 11-12).
	"Bank Account": {"validate": "erpnext_spain.es_sepa.bank_account.validate"},
	# Tercero por IBAN y pago por EndToEndId SEPA (spec 13 §4).
	"Bank Transaction": {"validate": "erpnext_spain.es_bancos.importer.validate_bank_transaction"},
	"Company": {
		# El NIF de la compañía lo valida primero el verificador (nif/party);
		# la compuerta de activación de VeriFactu (spec 04 §2.1) corre después.
		"validate": [
			# Razón social por defecto: el nombre de la compañía.
			"erpnext_spain.utils.company.set_default_legal_name",
			"erpnext_spain.nif.party.validate",
			# SII y VeriFactu excluyentes (spec 14 §1): antes que la compuerta de
			# activación de VeriFactu, para que el error explique el conflicto.
			"erpnext_spain.es_sii.company.validate",
			"erpnext_spain.es_verifactu.company.validate",
		]
	},
	# Ciclo de EMISIÓN de Sales Invoice (spec 04 §4-6, lotes 4b/4c):
	# validate aplica las compuertas (amend, desglose, simplificada↔POS,
	# NIFs, rectificativa, tipo); before_submit renombra el borrador a la
	# serie fiscal (snapshot de modo + posting_date + guard de nombres
	# explícitos) y sostiene el cerrojo de cadena; on_submit crea el
	# RegistroAlta encadenado bajo el cerrojo (+ remisión Inmediata tras el
	# commit); before_cancel genera el RegistroAnulación (gateado por el
	# SNAPSHOT de modo de la factura).
	"Sales Invoice": {
		# Nombre temporal del borrador solo en compañías que numeran al emitir
		# (H1); como doc_event y no como extensión de la clase (H2).
		"autoname": "erpnext_spain.es_verifactu.invoice.autoname",
		# Historial de la pestaña «VeriFactu / SII».
		"onload": "erpnext_spain.es_facturacion.fiscal_tab.onload",
		"validate": [
			# Numeración fiscal sin VeriFactu, amend y rectificativas (spec 05 §1-§2).
			"erpnext_spain.es_facturacion.numbering.validate",
			# Datos del desglose fiscal congelados en la factura (spec 06).
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
			# Envío al SII (spec 14).
			"erpnext_spain.es_sii.outbox.on_submit",
			# Factura electrónica B2B (spec 10 §5).
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
		# Clasificación fiscal de las filas de impuestos (spec 03 §5).
		"erpnext.controllers.accounts_controller.validate_regional": (
			"erpnext_spain.es_impuestos.invoice.validate_regional"
		),
	},
}

# Desk JS por DocType
# ------------------
# UX de Company (spec 04 §2.1/§15): avisos legales del toggle de VeriFactu,
# banner discreto de modo pruebas y congelación read-only de la fecha de
# activación.
# UX de Sales Invoice (spec 04 §15, lote 6a): banner de modo pruebas
# (set_intro — snapshot de la factura + test_mode de la compañía en drafts)
# y glue del dialog de subsanación (get_dialog_fields → rectify).

# Avisos en el escritorio (evento realtime «erpnext_spain_notice»). Fichero
# servido tal cual desde public/, sin bundle.
app_include_js = ["/assets/erpnext_spain/js/notices.js"]

doctype_js = {
	"Company": [
		"es_verifactu/public/js/company.js",
		# Acción «Aplicar plan PGC» (spec 02 §2).
		"es_contabilidad/public/js/company.js",
		"es_sii/public/js/company.js",
		# Avisos al activar, pasar a producción, volver a pruebas o desactivar.
		"aeat/public/js/company_modes.js",
	],
	"Sales Invoice": [
		"es_verifactu/public/js/sales_invoice.js",
		# Botón «Generar Facturae» (spec 10).
		"es_efactura/public/js/sales_invoice.js",
		# Situación de cobro (spec 05 §4).
		"es_facturacion/public/js/sales_invoice.js",
		# Pestaña «VeriFactu / SII».
		"es_facturacion/public/js/fiscal_tab.js",
	],
	"Purchase Invoice": "es_facturacion/public/js/fiscal_tab.js",
	# Formato de nombre de las personas físicas y contraste del NIF con la AEAT.
	"Customer": "nif/public/js/party.js",
	"Supplier": "nif/public/js/party.js",
}

# Estilado de BORRADOR-* en el list view de Sales Invoice (spec 04 §15):
# un solo archivo por doctype, mismo criterio que doctype_js.

doctype_js.update(
	{
		# Fichero SEPA de transferencias (spec 11 §4).
		"Payment Order": "es_sepa/public/js/payment_order.js",
	}
)

# Acciones masivas (spec 15): facturar albaranes, enviar facturas, comprobar NIF.
BULK_ACTIONS_JS = "es_facturacion/public/js/bulk_actions.js"
doctype_list_js = {
	"Sales Invoice": ["es_verifactu/public/js/sales_invoice_list.js", BULK_ACTIONS_JS],
	"Delivery Note": BULK_ACTIONS_JS,
	"Purchase Receipt": BULK_ACTIONS_JS,
	"Customer": BULK_ACTIONS_JS,
	"Supplier": BULK_ACTIONS_JS,
	"Purchase Invoice": BULK_ACTIONS_JS,
}

# Métodos Jinja para los Print Formats (doc 12 §14, patrón India Compliance;
# spec 04 §11): QR de validación VeriFactu, su URL (el formato imprime el
# enlace legible junto al código), desglose IVA y denominación display del
# tercero (spec 14). Rutas explícitas por función — solo el API público del
# módulo queda expuesto a plantillas.

jinja = {
	"methods": [
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_qr_url",
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_qr_code",
		"erpnext_spain.es_verifactu.utils.jinja.get_verifactu_breakup",
		"erpnext_spain.es_verifactu.utils.jinja.get_es_display_name",
		"erpnext_spain.es_verifactu.utils.jinja.get_es_legal_name",
		# Desglose por clasificación y rectificada (spec 05 §5).
		"erpnext_spain.es_facturacion.printing.get_es_tax_summary",
		"erpnext_spain.es_facturacion.printing.get_es_rectified_reference",
	],
}

# Installation / Migration
# ------------------------
# Custom Fields declarados en Python (doc 12 §11). La app puede estar ya
# instalada cuando se añaden campos, por eso el wiring va tanto en
# after_install como en after_migrate (idempotente).

after_install = "erpnext_spain.install.after_install"
after_migrate = "erpnext_spain.install.after_migrate"
before_uninstall = "erpnext_spain.install.before_uninstall"
# R11: crea los custom fields que dependen de apps opcionales (p. ej. HRMS)
# cuando estas se instalan después que ERPNext Spain.
after_app_install = "erpnext_spain.install.after_app_install"

# Scheduler Events
# ----------------
# Capa AEAT (spec 13 §2 + spec 04 §15): aviso diario de caducidad de
# certificados a 30/7/1 días del fin de vigencia, por los dos canales de
# incidencias de la compañía. Drenaje del outbox VeriFactu cada minuto
# (spec 13 §5 + spec 04 §8): el driver drena solo las empresas con registros
# pendientes (sin gate de «activada») y el manager aísla errores por empresa.
# Diario VeriFactu (lote 5b): alerta de outbox ESTANCADO (spec 04 §8) —
# registros PendienteEnvio parados > 24 h → incidencia por los dos canales.
# Formato cron de 5 campos (mismo que frappe/hooks.py y erpnext/hooks.py).

scheduler_events = {
	"hourly": [
		# Comunicación del pago de facturas electrónicas recibidas (spec 10 §5).
		"erpnext_spain.es_efactura.b2b.communicate_payments",
	],
	"daily": [
		"erpnext_spain.aeat.tasks.daily",
		"erpnext_spain.es_verifactu.tasks.daily",
		# Aviso de facturas candidatas a dudoso cobro (spec 05 §4).
		"erpnext_spain.es_facturacion.collection.flag_doubtful_candidates",
		# Aviso de caducidad del consentimiento bancario (spec 13 §3).
		"erpnext_spain.es_bancos.aggregator.warn_expiring_consents",
		# Plazos del SII (spec 14 §3).
		"erpnext_spain.es_sii.outbox.warn_deadlines",
	],
	"cron": {
		"* * * * *": ["erpnext_spain.es_verifactu.tasks.drain_outbox"],
		# Sincronización con el agregador bancario (spec 13 §3).
		"0 */6 * * *": ["erpnext_spain.es_bancos.aggregator.sync_all"],
		# Envío al SII (spec 14 §3).
		"*/15 * * * *": ["erpnext_spain.es_sii.outbox.drain_outbox"],
	},
}

# Hooks transversales de la capa AEAT (spec 13 §8)

# Config/credenciales que NO se borran al limpiar transacciones de una Company
# (doc 12 §17): la configuración de cumplimiento sobrevive a resets de
# pruebas. VeriFactu añade sus child tables de config (series por empresa y
# roles de notificación) y el libro de registros — el ledger es historia legal
# inmutable: NUNCA debe barrerse con las transacciones de la empresa.
company_data_to_be_ignored = [
	"ES AEAT Credential",
	# Registros del SII: historia legal, como el libro de VeriFactu.
	"ES Sii Record",
	"ES Leased Property",
	"ES Invoice Series",
	"ES Verifactu Notification Role",
	"ES Verifactu Billing Record",
]

# Las respuestas AEAT y los registros del libro VeriFactu son logs históricos:
# no deben bloquear borrados legítimos de documentos de negocio (doc 12 §17,
# spec 04 §13). La línea es child table: se ignora su enlace implícito vía el
# padre.
ignore_links_on_delete = [
	"ES AEAT Response",
	"ES AEAT Response Line",
	"ES Verifactu Billing Record",
]

# Protección de datos en exportaciones/anonimizado (doc 12 §17): el password
# del certificado es dato sensible del propietario de la credencial.
user_data_fields = [
	{"doctype": "ES AEAT Credential", "filter_by": "owner", "redact_fields": ["cert_password"]},
]
