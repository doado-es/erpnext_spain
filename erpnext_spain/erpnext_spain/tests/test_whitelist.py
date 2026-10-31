# Endpoints de la app: Frappe valida y convierte los argumentos según las
# anotaciones (maestro R6). Si un módulo usa `from __future__ import
# annotations`, las anotaciones son cadenas y Frappe NO las valida ni las
# convierte: un `dry_run: bool` recibido como "0" desde el navegador llega
# como la cadena "0" (verdadera). Así fallaba en silencio el botón «Aplicar
# plan PGC» (pendientes de la fase 0).

import importlib
import inspect
import pathlib

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.typing_validations import transform_parameter_types

APP_ROOT = pathlib.Path(frappe.get_app_path("erpnext_spain"))


def _import_whitelisted_modules() -> None:
	for path in APP_ROOT.rglob("*.py"):
		if "tests" in path.parts or "@frappe.whitelist" not in path.read_text(encoding="utf-8"):
			continue
		module = ".".join(("erpnext_spain", *path.relative_to(APP_ROOT).with_suffix("").parts))
		importlib.import_module(module)


def _app_endpoints() -> list:
	_import_whitelisted_modules()
	return [fn for fn in frappe.whitelisted if getattr(fn, "__module__", "").startswith("erpnext_spain.")]


class TestWhitelistedSignatures(IntegrationTestCase):
	def test_endpoints_found(self):
		self.assertIn("erpnext_spain.es_contabilidad.pgc", {fn.__module__ for fn in _app_endpoints()})

	def test_annotations_are_real_types(self):
		"""Ningún endpoint tiene anotaciones en forma de cadena."""
		for fn in _app_endpoints():
			for name, annotation in inspect.unwrap(fn).__annotations__.items():
				with self.subTest(endpoint=f"{fn.__module__}.{fn.__qualname__}", argument=name):
					self.assertNotIsInstance(
						annotation,
						str,
						"Anotación en forma de cadena: quita `from __future__ import annotations`"
						" del módulo para que Frappe valide y convierta los argumentos.",
					)

	def test_arguments_typed(self):
		"""Todos los argumentos de los endpoints llevan type hint (R6)."""
		for fn in _app_endpoints():
			target = inspect.unwrap(fn)
			for name in inspect.signature(target).parameters:
				with self.subTest(endpoint=f"{fn.__module__}.{fn.__qualname__}", argument=name):
					self.assertIn(name, target.__annotations__)

	def test_form_value_zero_is_false(self):
		"""El navegador envía `dry_run=0`: debe llegar como falso."""
		from erpnext_spain.es_contabilidad.pgc import apply_pgc_chart

		_args, kwargs = transform_parameter_types(
			inspect.unwrap(apply_pgc_chart), (), {"company": "x", "chart_model": "PYMES", "dry_run": "0"}
		)
		self.assertFalse(kwargs["dry_run"])
