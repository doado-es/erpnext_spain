"""Extrae el cuadro de cuentas (4ª parte) del texto consolidado del BOE.

Herramienta de desarrollo, no se ejecuta en el sitio. Uso:

	curl -sSL -o normal.html "https://www.boe.es/buscar/act.php?id=BOE-A-2007-19884&tn=1"
	curl -sSL -o pymes.html "https://www.boe.es/buscar/act.php?id=BOE-A-2007-19966&tn=1"
	python extract_boe.py normal.html Normal source/boe_pgc_normal.json
	python extract_boe.py pymes.html PYMES source/boe_pgc_pymes.json

El fichero de salida guarda el texto del BOE tal cual (sin normalizar): la
normalización y las correcciones de erratas las hace generate.py, para que el
dato fuente sea auditable contra el BOE.
"""

from __future__ import annotations

import html
import json
import re
import sys

BOE_IDS = {"Normal": "BOE-A-2007-19884", "PYMES": "BOE-A-2007-19966"}
NUMBER = re.compile(r"^(\d{1,5})\.?$")
GROUP = re.compile(r"^(?:\[encabezado\])?Grupo (\d)$")
LAST_UPDATE = re.compile(r"Última actualización publicada el (\d{2}/\d{2}/\d{4})")


def extract(text: str) -> tuple[dict[str, str], list[list[str]]]:
	# La página consolidada repite «CUARTA PARTE» en el índice; el cuadro es el
	# tramo más largo entre una «CUARTA PARTE» y la «QUINTA PARTE» siguiente.
	segment = ""
	for match in re.finditer("CUARTA PARTE", text):
		end = text.find("QUINTA PARTE", match.start())
		if end > 0 and end - match.start() > len(segment):
			segment = text[match.start() : end]
	if not segment:
		raise SystemExit("No se encuentra la cuarta parte (cuadro de cuentas) en el documento.")
	plain = html.unescape(re.sub(r"<[^>]+>", "\n", segment))
	lines = [line.strip() for line in plain.split("\n") if line.strip()]

	groups: dict[str, str] = {}
	accounts: list[list[str]] = []
	i = 0
	while i < len(lines) - 1:
		if match := GROUP.match(lines[i]):
			groups[match.group(1)] = lines[i + 1]
			i += 2
		elif match := NUMBER.match(lines[i]):
			name = lines[i + 1]
			i += 2
			# Títulos de subgrupo (en mayúsculas) partidos en varias líneas.
			while i < len(lines) and name.isupper() and lines[i].isupper() and not NUMBER.match(lines[i]):
				name = f"{name} {lines[i]}"
				i += 1
			accounts.append([match.group(1), name])
		else:
			i += 1
	return groups, accounts


def main(source_html: str, model: str, output: str) -> None:
	text = open(source_html, encoding="utf-8").read()
	groups, accounts = extract(text)
	numbers = [number for number, _ in accounts]
	if len(numbers) != len(set(numbers)):
		raise SystemExit("Hay números de cuenta duplicados en el cuadro extraído.")
	last_update = LAST_UPDATE.search(text)
	data = {
		"model": model,
		"source": f"https://www.boe.es/buscar/act.php?id={BOE_IDS[model]}",
		"boe_last_update": last_update.group(1) if last_update else None,
		"groups": groups,
		"accounts": accounts,
	}
	with open(output, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, indent=1)
		f.write("\n")
	print(f"{model}: {len(groups)} grupos, {len(accounts)} cuentas → {output}")


if __name__ == "__main__":
	main(*sys.argv[1:4])
