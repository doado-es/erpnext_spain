"""Borrador del mapeo de los balances Normal y Abreviado desde el texto del BOE.

Herramienta de desarrollo (no se ejecuta en el sitio). Lee el texto plano de la
3ª parte del PGC (modelos normales y abreviados del BOE-A-2007-19884,
consolidado) y escribe las filas del balance en el formato de
epigrafe_mapping.csv: código jerárquico, nivel, cuentas («incluir») y fórmulas
de los totales. Las correcciones (filas por signo, cuentas que el modelo no
recoge) se aplican después a mano en el CSV y se marcan en la columna `nota`.

	python extract_models.py modelos.txt <inicio> <fin> <Normal|Abreviado>
"""

import csv
import re
import sys

ACCOUNTS = re.compile(r"^[\(\)\d\s,\*]+$")
LETTER = re.compile(r"^([A-Z])\)\s")
SUBLETTER = re.compile(r"^([A-Z])-(\d)\)\s")
ROMAN = re.compile(r"^([IVX]+)\.\s")
NUMBER = re.compile(r"^(\d+)\.\s")
TOTAL = re.compile(r"^TOTAL\s")
SKIP = {
	"N° CUENTAS",
	"N.° CUENTAS",
	"ACTIVO",
	"NOTAS de la MEMORIA",
	"NOTAS de la",
	"MEMORIA",
	"200X",
	"200X-1",
	"PATRIMONIO NETO Y PASIVO",
}


def clean_accounts(text: str) -> str:
	numbers = re.findall(r"\d+", text)
	return " ".join(dict.fromkeys(numbers))


def parse(lines: list[str]) -> list[dict]:
	rows: list[dict] = []
	pending: list[str] = []
	for line in lines:
		line = line.strip()
		if not line or line in SKIP:
			continue
		if ACCOUNTS.match(line) and re.search(r"\d", line):
			# Continuación de la lista de la fila anterior (acaba en coma).
			if not pending and rows and rows[-1]["raw"].rstrip().endswith(","):
				rows[-1]["raw"] += " " + line
			else:
				pending.append(line)
			continue
		if (
			LETTER.match(line)
			or SUBLETTER.match(line)
			or ROMAN.match(line)
			or NUMBER.match(line)
			or TOTAL.match(line)
		):
			rows.append({"label": line, "raw": " ".join(pending)})
			pending = []
		elif rows:
			rows[-1]["label"] += " " + line
	return rows


def structure(rows: list[dict], side_codes=("ACT", "PN")) -> list[dict]:
	out = []
	side = "ACT"
	letter = sub = roman = None
	for row in rows:
		label = row["label"]
		if TOTAL.match(label):
			out.append(
				{
					"codigo": f"TOTAL_{'ACTIVO' if side == 'ACT' else 'PN_PASIVO'}",
					"label": label,
					"nivel": 0,
					"raw": "",
					"parent": None,
				}
			)
			side = "PN"
			letter = sub = roman = None
			continue
		if m := LETTER.match(label):
			prefix = "PN" if side == "PN" and m.group(1) == "A" else ("PAS" if side == "PN" else "ACT")
			letter = f"{prefix}_{m.group(1)}"
			sub = roman = None
			code, level, parent = letter, 0, None
		elif m := SUBLETTER.match(label):
			sub = f"{letter}{m.group(2)}"
			roman = None
			code, level, parent = sub, 1, letter
		elif m := ROMAN.match(label):
			base = sub or letter
			roman = f"{base}_{m.group(1)}"
			code, level, parent = roman, 2 if sub else 1, base
		elif m := NUMBER.match(label):
			base = roman or sub or letter
			code = f"{base}_{m.group(1)}"
			level = (2 if not sub else 3) if roman else (2 if sub else 1)
			parent = base
		else:
			continue
		out.append({"codigo": code, "label": label, "nivel": level, "raw": row["raw"], "parent": parent})
	children: dict[str, list[str]] = {}
	for row in out:
		if row["parent"]:
			children.setdefault(row["parent"], []).append(row["codigo"])
	for row in out:
		row["children"] = children.get(row["codigo"], [])
	return out


def to_csv_rows(model: str, rows: list[dict]) -> list[dict]:
	result = []
	letters = {"ACT": [], "PN": []}
	for row in rows:
		equity_side = row["codigo"].startswith(("PN_", "PAS_", "TOTAL_PN"))
		base = {
			"modelo": model,
			"estado": "Balance",
			"codigo": row["codigo"],
			"epigrafe": row["label"],
			"nivel": str(row["nivel"]),
			"tipo": "",
			"incluir": "",
			"excluir": "",
			"segun_signo": "",
			"lado": "",
			"invertir_signo": "",
			"formula": "",
			"nota": "",
		}
		accounts = clean_accounts(row["raw"])
		if row["codigo"].startswith("TOTAL_"):
			side = "ACT" if row["codigo"] == "TOTAL_ACTIVO" else "PN"
			base.update(tipo="formula", formula=" + ".join(letters[side]))
		elif row["children"]:
			base.update(tipo="formula", formula=" + ".join(row["children"]))
		elif accounts:
			base.update(tipo="cuentas", incluir=accounts, invertir_signo="1" if equity_side else "")
		else:
			base.update(tipo="vacio")
		if row["nivel"] == 0 and not row["codigo"].startswith("TOTAL_"):
			letters["PN" if equity_side else "ACT"].append(row["codigo"])
		result.append(base)
	return result


def main() -> None:
	path, start, end, model = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
	lines = open(path, encoding="utf-8").read().split("\n")[start:end]
	rows = to_csv_rows(model, structure(parse(lines)))
	writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
	writer.writeheader()
	writer.writerows(rows)


if __name__ == "__main__":
	main()
