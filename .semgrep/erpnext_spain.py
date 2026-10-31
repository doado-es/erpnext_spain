# Casos de prueba de .semgrep/erpnext_spain.yml (spec 01, criterio 3).
# `semgrep --test .semgrep` comprueba que cada `ruleid` se detecta y cada
# `ok` no. No es código de la app.
# ruff: noqa
import frappe
import frappe.utils as frappe_utils
from erpnext.accounts import utils as accounts_utils
from frappe.model import document


def patched(*args, **kwargs):
	return None


# ruleid: es-no-doctype-class-override
override_doctype_class = {"Sales Invoice": "erpnext_spain.overrides.SalesInvoice"}

# ruleid: es-no-doctype-class-override
extend_doctype_class = {"Sales Invoice": ["erpnext_spain.mixins.Mixin"]}

# ok: es-no-doctype-class-override
doc_events = {"Sales Invoice": {"validate": "erpnext_spain.events.validate"}}


def monkey_patches():
	# ruleid: es-no-monkey-patching
	frappe.get_doc = patched
	# ruleid: es-no-monkey-patching
	frappe.utils.nowdate = patched
	# ruleid: es-no-monkey-patching
	accounts_utils.get_fiscal_year = patched
	# ruleid: es-no-monkey-patching
	document.Document.save = patched
	# ruleid: es-no-monkey-patching
	frappe_utils.flt = patched


def legitimate_state():
	# ok: es-no-monkey-patching
	frappe.flags.in_import = True
	# ok: es-no-monkey-patching
	frappe.local.response_headers = {}
	# ok: es-no-monkey-patching
	frappe.response.message = "ok"
	doc = frappe.new_doc("ToDo")
	# ok: es-no-monkey-patching
	doc.description = "x"


def raw_sql():
	# ruleid: es-no-raw-sql
	frappe.db.sql("select 1")
	# ruleid: es-no-db-commit
	frappe.db.commit()
	# ok: es-no-raw-sql
	frappe.get_all("ToDo", pluck="name")
