# Correspondencia cuentas → epígrafes de los estados financieros PGC (spec 04 §2).
#
# Fuente única: epigrafe_mapping.csv, que revisa un contable. De ella salen las
# Financial Report Template (generate_templates.py) y la configuración de las
# filas que dependen del signo del saldo (api.balance_by_sign).

from __future__ import annotations

import csv
import functools
from pathlib import Path

MAPPING_FILE = Path(__file__).resolve().parent / "epigrafe_mapping.csv"

# (modelo, estado) → nombre de la Financial Report Template.
TEMPLATE_NAMES = {
	("PYMES", "Balance"): "PGC PYMES - Balance",
	("PYMES", "PyG"): "PGC PYMES - Pérdidas y ganancias",
}

ROW_TYPES = ("titulo", "formula", "cuentas", "signo")


@functools.cache
def load_mapping() -> tuple[dict, ...]:
	with MAPPING_FILE.open(encoding="utf-8", newline="") as f:
		rows = tuple(dict(row) for row in csv.DictReader(f))
	for row in rows:
		if row["tipo"] not in ROW_TYPES:
			raise ValueError(f"Tipo de fila desconocido en {row['codigo']}: {row['tipo']}")
	return rows


def model_rows(model: str, statement: str) -> list[dict]:
	return [row for row in load_mapping() if row["modelo"] == model and row["estado"] == statement]


def find_row(template_name: str, reference_code: str) -> dict | None:
	for (model, statement), name in TEMPLATE_NAMES.items():
		if name == template_name:
			for row in model_rows(model, statement):
				if row["codigo"] == reference_code:
					return row
	return None


def prefixes(value: str) -> list[str]:
	return value.split() if value else []


def account_filter(include: list[str], exclude: list[str] | None = None) -> str:
	"""Fórmula de filtro de cuentas del motor de plantillas de ERPNext v16.

	El prefijo lleva siempre «%» explícito: sin él el motor busca «%valor%» y
	«430» casaría también con 4430 (spec 04 §1)."""
	conditions = [["account_number", "like", f"{prefix}%"] for prefix in include]
	formula: list | dict = conditions[0] if len(conditions) == 1 else {"or": conditions}
	if exclude:
		formula = {"and": [formula, *[["account_number", "not like", f"{prefix}%"] for prefix in exclude]]}
	return repr(formula).replace("'", '"')
