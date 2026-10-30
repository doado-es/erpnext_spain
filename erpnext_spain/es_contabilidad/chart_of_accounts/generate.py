"""Genera los planes de cuentas PGC en el formato de ERPNext (spec 02 §1).

Herramienta de desarrollo: se ejecuta a mano y su salida (pgc_normal.json y
pgc_pymes.json) se commitea. Nadie edita esos JSON a mano; un test comprueba
que coinciden con la salida de este generador.

	python generate.py

Entrada: source/boe_pgc_*.json (cuadro de cuentas del BOE tal cual, ver
extract_boe.py). Reglas que aplica:

1. Cinco raíces nativas (Activo, Pasivo, Patrimonio neto, Gastos, Ingresos):
   cada cuenta va a la rama de ROOT_RULES (spec 02 §1, decisión D4).
2. Un grupo o subgrupo del PGC cuyas cuentas caen en ramas distintas se parte:
   una copia sin número en cada rama, con la rama entre paréntesis en el
   nombre (ERPNext exige nombres únicos por compañía).
3. Hojas de 4 dígitos (decisión de 30/10/2026, opción B): cada cuenta de 3
   dígitos sin subcuentas en el PGC recibe una subcuenta «xxx0» con el mismo
   nombre, que es donde se contabiliza.
4. account_type según TYPE_RULES (spec 02 §3, inventario administrativo A3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source"

# Versión de los datos del plan. Se sube con cada cambio del generador o de la
# fuente que altere los JSON (spec 02 §5).
VERSION = 2

MODELS = {
	"Normal": ("boe_pgc_normal.json", "pgc_normal.json", "PGC Normal (RD 1514/2007)"),
	"PYMES": ("boe_pgc_pymes.json", "pgc_pymes.json", "PGC PYMES (RD 1515/2007)"),
}

ROOTS = {
	"Asset": "Activo",
	"Liability": "Pasivo",
	"Equity": "Patrimonio neto",
	"Expense": "Gastos",
	"Income": "Ingresos",
}

# Prefijo → rama. Gana el prefijo más largo. Propuesta de la spec 02 §1,
# alineada con el lado en que los modelos oficiales de balance (3ª parte del
# PGC y del PGC PYMES) presentan cada cuenta, para que los totales del Balance
# nativo coincidan con los de las plantillas PGC (spec 04). Las correctoras van
# en la rama de la partida que corrigen: 406 en Pasivo (minora proveedores),
# 437 en Activo (minora clientes), 1034/1044 y el subgrupo 19 en Pasivo (otras
# deudas a corto plazo), 557 en Patrimonio neto. Pendiente de revisión contable.
ROOT_RULES = {
	"10": "Equity",
	"11": "Equity",
	"12": "Equity",
	"13": "Equity",
	"14": "Liability",
	"15": "Liability",
	"16": "Liability",
	"17": "Liability",
	"18": "Liability",
	"1034": "Liability",
	"1044": "Liability",
	"19": "Liability",
	"2": "Asset",
	"3": "Asset",
	"40": "Liability",
	"407": "Asset",
	"41": "Liability",
	"43": "Asset",
	"437": "Asset",
	"438": "Liability",
	"44": "Asset",
	"46": "Asset",
	"465": "Liability",
	"466": "Liability",
	"47": "Asset",
	"475": "Liability",
	"476": "Liability",
	"477": "Liability",
	"479": "Liability",
	"48": "Asset",
	"485": "Liability",
	"49": "Asset",
	"499": "Liability",
	"50": "Liability",
	"51": "Liability",
	"52": "Liability",
	"53": "Asset",
	"54": "Asset",
	"55": "Asset",
	"555": "Liability",
	"556": "Liability",
	"557": "Equity",
	"5595": "Liability",
	"5598": "Liability",
	"56": "Asset",
	"560": "Liability",
	"561": "Liability",
	"568": "Liability",
	"569": "Liability",
	"57": "Asset",
	"58": "Asset",
	"585": "Liability",
	"586": "Liability",
	"587": "Liability",
	"588": "Liability",
	"589": "Liability",
	"59": "Asset",
	"6": "Expense",
	"7": "Income",
	"8": "Equity",
	"9": "Equity",
}

# Prefijo de la cuenta de contabilización → account_type. Gana el más largo;
# None anula una regla más corta.
TYPE_RULES = {
	# Clientes y anticipos de clientes (ERPNext exige Pasivo + Receivable en el
	# anticipo recibido).
	"430": "Receivable",
	"431": "Receivable",
	"432": "Receivable",
	"433": "Receivable",
	"434": "Receivable",
	"435": "Receivable",
	"436": "Receivable",
	"4380": "Receivable",
	# Proveedores, acreedores y anticipos a proveedores (Activo + Payable).
	"400": "Payable",
	"401": "Payable",
	"402": "Payable",
	"403": "Payable",
	"404": "Payable",
	"405": "Payable",
	"410": "Payable",
	"4070": "Payable",
	# Impuestos.
	"472": "Tax",
	"473": "Tax",
	"4751": "Tax",
	"477": "Tax",
	# Tesorería.
	"570": "Cash",
	"571": "Cash",
	"572": "Bank",
	"573": "Bank",
	# Inmovilizado.
	"20": "Fixed Asset",
	"21": "Fixed Asset",
	"23": "Capital Work in Progress",
	"280": "Accumulated Depreciation",
	"281": "Accumulated Depreciation",
	"680": "Depreciation",
	"681": "Depreciation",
	# Existencias con inventario administrativo (A3): solo para cumplir los
	# tipos obligatorios de ERPNext; no generan asientos automáticos.
	"30": "Stock",
	"31": "Stock",
	"32": "Stock",
	"33": "Stock",
	"34": "Stock",
	"35": "Stock",
	"36": "Stock",
	"610": "Stock Adjustment",
	"611": "Stock Adjustment",
	"612": "Stock Adjustment",
	"600": "Cost of Goods Sold",
}

# account_type de algunos GRUPOS. ERPNext espera grupos Bank, Cash y Stock
# (get_mandatory_group_accounts del importador de planes) para crear debajo las
# cuentas de bancos, cajas y almacenes.
GROUP_TYPES = {
	"570": "Cash",
	"571": "Cash",
	"572": "Bank",
	"573": "Bank",
	"30": "Stock",
	"31": "Stock",
	"32": "Stock",
	"33": "Stock",
	"34": "Stock",
	"35": "Stock",
	"36": "Stock",
}

# Erratas del texto del BOE (se corrigen al generar; la fuente queda intacta).
TYPOS = {
	"deterioroy": "deterioro y",
	"donacionesy": "donaciones y",
	"activosy": "activos y",
	"carácterísticas": "características",
	"alargo plazo": "a largo plazo",
	"acorto plazo": "a corto plazo",
	"^Gastor ": "Gastos ",
}

# Correcciones de nombres que no son erratas tipográficas. En el PGC PYMES
# las cuentas 232, 233, 237 y 239 aparecen todas como «Propiedad industrial»
# (también en el texto original de 2007). Se toman los nombres del PGC Normal,
# que coinciden con las definiciones de la 5ª parte del propio PGC PYMES.
NAME_FIXES = {
	# Nombre abreviado: el oficial (138 caracteres) no cabe en el nombre del
	# documento Account de ERPNext («número - nombre - abreviatura», máx. 140).
	"Normal": {
		"5993": (
			"Deterioro de existencias, deudores comerciales y otras cuentas a cobrar"
			" de grupos enajenables mantenidos para la venta"
		),
	},
	"PYMES": {
		"232": "Instalaciones técnicas en montaje",
		"233": "Maquinaria en montaje",
		"237": "Equipos para procesos de información en montaje",
		"239": "Anticipos para inmovilizaciones materiales",
	},
}


PARTY_TYPES = ("Receivable", "Payable")

# Longitud máxima de «número - nombre» para que el nombre del documento Account
# («número - nombre - abreviatura») no pase de 140 caracteres con abreviaturas de
# compañía de hasta MAX_COMPANY_ABBR caracteres.
MAX_COMPANY_ABBR = 12
MAX_NUMBER_AND_NAME = 140 - len(" - ") - MAX_COMPANY_ABBR


def longest_prefix(number: str, rules: dict) -> tuple[bool, object]:
	for size in range(len(number), 0, -1):
		if number[:size] in rules:
			return True, rules[number[:size]]
	return False, None


def root_of(number: str) -> str:
	found, root = longest_prefix(number, ROOT_RULES)
	if not found:
		raise ValueError(f"La cuenta {number} no tiene rama en ROOT_RULES.")
	return root


def normalize_name(name: str) -> str:
	name = name.replace("\xad", "")
	name = re.sub(r"\s+", " ", name).strip()
	name = name.rstrip(".").strip()
	for wrong, right in TYPOS.items():
		name = re.sub(wrong, right, name, flags=re.IGNORECASE)
	if name.isupper():
		name = name[0] + name[1:].lower()
	if name.endswith(" etc"):
		name += "."
	return name


def build_tree(source: dict) -> dict:
	names = {number: normalize_name(name) for number, name in source["accounts"]}
	names.update(NAME_FIXES.get(source["model"], {}))
	for digit, name in source["groups"].items():
		names[digit] = normalize_name(name)

	children: dict[str, list[str]] = {}
	for number in names:
		if len(number) > 1:
			children.setdefault(number[:-1], []).append(number)
	for kids in children.values():
		kids.sort()

	def leaf_roots(number: str) -> set[str]:
		kids = children.get(number)
		if not kids:
			return {root_of(number)}
		return set().union(*(leaf_roots(kid) for kid in kids))

	def posting_leaf(number: str) -> dict:
		node: dict = {"account_number": number}
		found, account_type = longest_prefix(number, TYPE_RULES)
		if account_type in PARTY_TYPES and number.endswith("9"):
			# 4009, 4039, 4109, 4309, 4339…: facturas pendientes de recibir o de
			# formalizar. Son cuentas provisionales sin tercero; con tipo
			# Receivable/Payable ERPNext exigiría tercero en cada apunte.
			account_type = None
		if found and account_type:
			node["account_type"] = account_type
		return node

	def group_type(number: str) -> dict:
		return {"account_type": GROUP_TYPES[number]} if number in GROUP_TYPES else {}

	def put(parent: dict, name: str, node: dict) -> None:
		number = node.get("account_number")
		label = f"{number} - {name}" if number else name
		if len(label) > MAX_NUMBER_AND_NAME:
			raise ValueError(f"Nombre demasiado largo para ERPNext ({len(label)}): {label}")
		if name in parent:
			raise ValueError(f"Nombre de cuenta repetido en el mismo grupo: {name}")
		parent[name] = node

	def add(number: str, parents: dict[str, dict]) -> None:
		name = names[number]
		roots = sorted(leaf_roots(number), key=list(ROOTS).index)
		kids = children.get(number, [])
		if len(roots) == 1:
			root = roots[0]
			if kids:
				node = {"account_number": number, **group_type(number)}
				put(parents[root], name, node)
				for kid in kids:
					add(kid, {root: node})
			elif len(number) == 3:
				# Opción B: hoja de 4 dígitos bajo la cuenta de 3.
				put(
					parents[root],
					name,
					{"account_number": number, **group_type(number), name: posting_leaf(number + "0")},
				)
			elif len(number) < 3:
				raise ValueError(f"El subgrupo {number} no tiene cuentas.")
			else:
				put(parents[root], name, posting_leaf(number))
			return
		split = {}
		for root in roots:
			node = {}
			put(parents[root], f"{name} ({ROOTS[root]})", node)
			split[root] = node
		for kid in kids:
			kid_roots = leaf_roots(kid)
			add(kid, {root: split[root] for root in kid_roots})

	tree = {label: {"root_type": root_type} for root_type, label in ROOTS.items()}
	by_root = {root_type: tree[label] for root_type, label in ROOTS.items()}
	for digit in sorted(source["groups"]):
		add(digit, by_root)
	return tree


def generate(model: str) -> dict:
	source_file, _, title = MODELS[model]
	source = json.loads((SOURCE / source_file).read_text(encoding="utf-8"))
	return {
		"name": title,
		"country_code": "es",
		"version": VERSION,
		"source": source["source"],
		"boe_last_update": source["boe_last_update"],
		"tree": build_tree(source),
	}


def render(chart: dict) -> str:
	return json.dumps(chart, ensure_ascii=False, indent="\t") + "\n"


def main() -> None:
	for model, (_, output, _) in MODELS.items():
		(HERE / output).write_text(render(generate(model)), encoding="utf-8")
		print(f"{model} → {output}")


if __name__ == "__main__":
	main()
