# Libro registro de facturas recibidas (spec 06 §5).

from erpnext_spain.es_iva.books import book_columns, book_rows, check_filters


def execute(filters: dict | None = None):
	filters = check_filters(filters)
	return book_columns(received=True), book_rows(filters, "Recibidas")
