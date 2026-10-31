# Validación de cuentas en compañías con el plan PGC aplicado (spec 02 §4).
#
# Al crear o renumerar una cuenta:
# - una hoja necesita número de cuenta;
# - el número empieza por el del ancestro numerado más próximo;
# - la rama (root_type, heredada del padre por ERPNext) es la que corresponde
#   al prefijo según la tabla del §1 (ROOT_RULES del generador).
# No se cambia root_type ni la herencia de ERPNext (R2): solo se valida.

import frappe
from frappe import _

from erpnext_spain.es_contabilidad.chart_of_accounts.generate import ROOT_RULES, ROOTS
from erpnext_spain.utils.gating import is_pgc_company


def validate(doc, method=None) -> None:
	if not is_pgc_company(doc.company):
		return
	if not (
		doc.is_new() or doc.has_value_changed("account_number") or doc.has_value_changed("parent_account")
	):
		return

	number = (doc.account_number or "").strip()
	if not number:
		if not doc.is_group:
			frappe.throw(
				_(
					"La cuenta {0} no tiene número. En una compañía con el plan PGC, toda cuenta"
					" en la que se contabiliza necesita su número del PGC (por ejemplo 5721 para un"
					" segundo banco). Indique el número de cuenta."
				).format(frappe.bold(doc.account_name)),
				title=_("Falta el número de cuenta"),
			)
		return

	ancestor_number = numbered_ancestor(doc.parent_account)
	if ancestor_number and not number.startswith(ancestor_number):
		frappe.throw(
			_(
				"El número {0} no cuelga de la cuenta padre: debe empezar por {1}. Cambie el"
				" número o elija como padre la cuenta del PGC a la que pertenece."
			).format(frappe.bold(number), frappe.bold(ancestor_number)),
			title=_("Número de cuenta incoherente"),
		)

	expected = expected_root_type(number)
	if expected and doc.root_type and doc.root_type != expected:
		frappe.throw(
			_(
				"Las cuentas {0} van en la rama {1} del plan PGC, no en {2}. Elija como padre una"
				" cuenta de la rama {1}."
			).format(
				frappe.bold(number), frappe.bold(_(ROOTS[expected])), frappe.bold(_(ROOTS[doc.root_type]))
			),
			title=_("Rama incorrecta"),
		)


def numbered_ancestor(parent: str | None) -> str | None:
	"""Número del ancestro numerado más próximo (los grupos partidos entre ramas
	no llevan número)."""
	while parent:
		number, parent = frappe.get_cached_value("Account", parent, ["account_number", "parent_account"])
		if number:
			return number.strip()
	return None


def expected_root_type(number: str) -> str | None:
	"""Rama según el prefijo más largo de ROOT_RULES."""
	for length in range(len(number), 0, -1):
		root = ROOT_RULES.get(number[:length])
		if root:
			return root
	return None
