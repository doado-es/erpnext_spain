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
	"Customer": {"validate": "erpnext_spain.nif.party.validate"},
	"Supplier": {"validate": "erpnext_spain.nif.party.validate"},
	"Company": {
		# El NIF de la compañía lo valida primero el verificador (nif/party);
		# la compuerta de activación de VeriFactu (spec 04 §2.1) corre después.
		"validate": [
			"erpnext_spain.nif.party.validate",
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
		"validate": "erpnext_spain.es_verifactu.emission.validate",
		"before_submit": "erpnext_spain.es_verifactu.emission.before_submit",
		"on_submit": "erpnext_spain.es_verifactu.emission.on_submit",
		"before_cancel": "erpnext_spain.es_verifactu.emission.before_cancel",
	},
}

# Extensiones de clase (mixins PRIMERO en el MRO — frappe/model/
# base_document.py _get_extended_class): naming de borradores de Sales
# Invoice (spec 04 §4). Adición pura: el controlador core no define
# autoname.
extend_doctype_class = {
	"Sales Invoice": ["erpnext_spain.es_verifactu.invoice.SalesInvoiceVerifactuMixin"],
}

# Desk JS por DocType
# ------------------
# UX de Company (spec 04 §2.1/§15): avisos legales del toggle de VeriFactu,
# banner discreto de modo pruebas y congelación read-only de la fecha de
# activación.
# UX de Sales Invoice (spec 04 §15, lote 6a): banner de modo pruebas
# (set_intro — snapshot de la factura + test_mode de la compañía en drafts)
# y glue del dialog de subsanación (get_dialog_fields → rectify).

doctype_js = {
	"Company": "es_verifactu/public/js/company.js",
	"Sales Invoice": "es_verifactu/public/js/sales_invoice.js",
}

# Estilado de BORRADOR-* en el list view de Sales Invoice (spec 04 §15):
# un solo archivo por doctype, mismo criterio que doctype_js.

doctype_list_js = {
	"Sales Invoice": "es_verifactu/public/js/sales_invoice_list.js",
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
	"daily": [
		"erpnext_spain.aeat.tasks.daily",
		"erpnext_spain.es_verifactu.tasks.daily",
	],
	"cron": {
		"* * * * *": ["erpnext_spain.es_verifactu.tasks.drain_outbox"],
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
