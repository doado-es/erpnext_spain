"""Genera las Financial Report Template PGC a partir de epigrafe_mapping.csv (spec 04 §2).

Herramienta de desarrollo: se ejecuta a mano y su salida se commitea. Nadie
edita los JSON de financial_report_template a mano; un test comprueba que
coinciden con la salida de este generador.

	python -m erpnext_spain.es_contabilidad.statements.generate_templates

(o directamente `python generate_templates.py` desde esta carpeta).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
	sys.path.insert(0, str(HERE.parents[2]))

from erpnext_spain.es_contabilidad.statements.mapping import (
	TEMPLATE_NAMES,
	account_filter,
	model_rows,
	prefixes,
)

TEMPLATE_DIR = HERE.parent / "financial_report_template"
MODULE = "ES Contabilidad"
SIGN_API = "erpnext_spain.es_contabilidad.statements.api.balance_by_sign"
REPORT_TYPES = {"Balance": "Balance Sheet", "PyG": "Profit and Loss Statement"}
BALANCE_TYPES = {"Balance": "Closing Balance", "PyG": "Period Movement (Debits - Credits)"}
FOLDERS = {("PYMES", "Balance"): "pgc_pymes_balance", ("PYMES", "PyG"): "pgc_pymes_pyg"}


def build_row(row: dict, statement: str) -> dict:
	level = int(row["nivel"] or 0)
	out = {
		"doctype": "Financial Report Row",
		"reference_code": row["codigo"],
		"display_name": row["epigrafe"],
		"indentation_level": level,
		"bold_text": 1 if level == 0 else 0,
		"reverse_sign": 1 if row["invertir_signo"] == "1" else 0,
	}
	if row["tipo"] == "titulo":
		out["data_source"] = "Blank Line"
	elif row["tipo"] == "formula":
		out["data_source"] = "Calculated Amount"
		out["calculation_formula"] = row["formula"]
	elif row["tipo"] == "cuentas":
		out["data_source"] = "Account Data"
		out["balance_type"] = BALANCE_TYPES[statement]
		out["calculation_formula"] = account_filter(prefixes(row["incluir"]), prefixes(row["excluir"]))
	elif row["tipo"] == "signo":
		out["data_source"] = "Custom API"
		out["balance_type"] = BALANCE_TYPES[statement]
		out["calculation_formula"] = SIGN_API
	return out


def generate(model: str, statement: str) -> dict:
	name = TEMPLATE_NAMES[(model, statement)]
	return {
		"doctype": "Financial Report Template",
		"name": name,
		"template_name": name,
		"report_type": REPORT_TYPES[statement],
		"module": MODULE,
		"disabled": 0,
		"rows": [build_row(row, statement) for row in model_rows(model, statement)],
	}


def render(template: dict) -> str:
	return json.dumps(template, ensure_ascii=False, indent="\t") + "\n"


def output_path(model: str, statement: str) -> Path:
	folder = FOLDERS[(model, statement)]
	return TEMPLATE_DIR / folder / f"{folder}.json"


def main() -> None:
	for model, statement in TEMPLATE_NAMES:
		path = output_path(model, statement)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(render(generate(model, statement)), encoding="utf-8")
		print(f"{model} {statement} → {path.relative_to(HERE.parent)}")


if __name__ == "__main__":
	main()
