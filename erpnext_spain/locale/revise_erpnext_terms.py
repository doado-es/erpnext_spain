"""Revisión es-ES de las cadenas compuestas de ERPNext (herramienta de desarrollo).

Lee el es.po de ERPNext y, para las cadenas que aún usan la variante general
(«Orden de venta», «Nota de entrega», «Cotización», «Producto»…), propone la de
España («Pedido de venta», «Albarán», «Presupuesto», «Artículo»…) con la
concordancia del artículo. Escribe las entradas nuevas al final del catálogo de
la app (las que ya estén en él no se tocan). Revisar el resultado a mano.

	python revise_erpnext_terms.py ../../erpnext/erpnext/locale/es.po es.po
"""

import re
import sys

from babel.messages.pofile import read_po, write_po

# (patrón, sustitución, género del término nuevo cuando cambia: "m" o None)
RULES = [
	(r"[ÓO]rdenes de [Vv]enta", "pedidos de venta", "mp"),
	(r"Orden de [Vv]enta", "pedido de venta", "m"),
	(r"[ÓO]rdenes de [Cc]ompra", "pedidos de compra", "mp"),
	(r"Orden de [Cc]ompra", "pedido de compra", "m"),
	(r"Notas de [Ee]ntrega", "albaranes", "mp"),
	(r"Nota de [Ee]ntrega", "albarán", "m"),
	(r"Recibos de [Cc]ompra", "albaranes de compra", None),
	(r"Recibo de [Cc]ompra", "albarán de compra", None),
	(r"Cotizaciones", "presupuestos", "mp"),
	(r"Cotización", "presupuesto", "m"),
	(r"Centros de [Cc]ostos", "centros de coste", None),
	(r"Centro de [Cc]ostos", "centro de coste", None),
	(r"Entrada de Stock", "movimiento de existencias", "m"),
]
ITEM_RULES = [(r"\bProductos\b", "artículos", None), (r"\bProducto\b", "artículo", None)]
ARTICLES = {
	"m": {
		"la": "el",
		"La": "El",
		"una": "un",
		"Una": "Un",
		"esta": "este",
		"Esta": "Este",
		"esa": "ese",
		"nueva": "nuevo",
		"Nueva": "Nuevo",
		"dicha": "dicho",
	},
	"mp": {
		"las": "los",
		"Las": "Los",
		"unas": "unos",
		"estas": "estos",
		"Estas": "Estos",
		"nuevas": "nuevos",
		"Nuevas": "Nuevos",
	},
}


def apply(text: str, rules) -> str:
	for pattern, replacement, gender in rules:

		def substitute(match, replacement=replacement):
			start = match.start()
			sentence_start = (
				start == 0
				or text[:start].rstrip().endswith((".", ":", "\n", "¿", "¡"))
				or text[:start].strip() == ""
			)
			return replacement[0].upper() + replacement[1:] if sentence_start else replacement

		new = re.sub(pattern, substitute, text)
		if gender and new != text:
			for old, masculine in ARTICLES[gender].items():
				new = re.sub(
					rf"\b{old}\s+(?=({replacement}|{replacement.capitalize()})\b)", f"{masculine} ", new
				)
		text = new
	# Contracciones tras pasar a masculino: «de el» → «del», «a el» → «al».
	text = re.sub(r"\bde el\b", "del", text)
	text = re.sub(r"\bDe el\b", "Del", text)
	return re.sub(r"\ba el\b", "al", text)


def main(source: str, target: str) -> None:
	with open(source, "rb") as f:
		erpnext = read_po(f)
	with open(target, "rb") as f:
		ours = read_po(f)
	known = {(m.id, m.context) for m in ours if m.id}
	added = 0
	for message in erpnext:
		if (
			not message.id
			or not message.string
			or isinstance(message.id, tuple)
			or (message.id, message.context) in known
		):
			continue
		rules = RULES + (ITEM_RULES if re.search(r"\bItems?\b", message.id) else [])
		revised = apply(message.string, rules)
		if revised != message.string:
			ours.add(
				message.id,
				revised,
				context=message.context,
				auto_comments=["Revisión es-ES de ERPNext (automática, revisar)"],
			)
			added += 1
	with open(target, "wb") as f:
		write_po(f, ours, width=0, sort_output=False)
	print(f"{added} entradas añadidas")


if __name__ == "__main__":
	main(sys.argv[1], sys.argv[2])
