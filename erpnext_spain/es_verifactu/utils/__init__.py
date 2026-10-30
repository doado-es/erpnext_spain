# Adaptador de datos VeriFactu (lote 4a): capa PURA (sin frappe). API pública:
# compute_issuance_hash, compute_cancellation_hash, build_issuance_record,
# build_cancellation_record, build_tax_breakdown, get_rectification_type,
# get_spain_tax_breakup. Ver data_adapter.py para el contrato completo.

from erpnext_spain.es_verifactu.utils.data_adapter import (
	build_cancellation_record,
	build_issuance_record,
	build_tax_breakdown,
	compute_cancellation_hash,
	compute_issuance_hash,
	get_rectification_type,
	get_spain_tax_breakup,
)

__all__ = [
	"build_cancellation_record",
	"build_issuance_record",
	"build_tax_breakdown",
	"compute_cancellation_hash",
	"compute_issuance_hash",
	"get_rectification_type",
	"get_spain_tax_breakup",
]
