# Tests de VECTORES del adaptador puro VeriFactu (lote 4a, spec 04 §7): huella
# SHA-256 contra cadenas canónicas byte-exactas construidas AQUÍ (visibles y
# regression-proof), encadenamiento de 3 registros, sensibilidad de 1 byte,
# forma de los registros alta/anulación, formato de montos de la referencia
# (str(float): 1210.0 -> "1210.0", 0.5 -> "0.5" — SIN coma ni relleno),
# agregación del desglose con Decimal ROUND_HALF_UP y el STUB del contrato 07.
#
# Este módulo es 100% PURO: sin frappe, sin site — corre bajo bench run-tests
# pero también standalone (python -m unittest) porque el adaptador no toca DB.

from __future__ import annotations

import hashlib
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import ClassVar

from erpnext_spain.es_verifactu.utils.data_adapter import (
	build_cancellation_record,
	build_issuance_record,
	build_tax_breakdown,
	compute_cancellation_hash,
	compute_issuance_hash,
	get_rectification_type,
	get_spain_tax_breakup,
)

ISSUER = "B12345678"
SERIES_NUMBER = "2026-001"
ISSUE_DATE = date(2026, 2, 1)
AEAT_DATE = "01-02-2026"
TS = "2026-02-01T13:58:26+01:00"

ISSUANCE_CHAIN_1 = (
	f"IDEmisorFactura={ISSUER}"
	f"&NumSerieFactura={SERIES_NUMBER}"
	f"&FechaExpedicionFactura={AEAT_DATE}"
	"&TipoFactura=F1"
	"&CuotaTotal=211.05"
	"&ImporteTotal=1211.05"
	"&Huella="
	f"&FechaHoraHusoGenRegistro={TS}"
)

HASH_1 = hashlib.sha256(ISSUANCE_CHAIN_1.encode("utf-8")).hexdigest().upper()

ISSUANCE_CHAIN_2 = (
	f"IDEmisorFactura={ISSUER}"
	"&NumSerieFactura=2026-002"
	f"&FechaExpedicionFactura={AEAT_DATE}"
	"&TipoFactura=F1"
	"&CuotaTotal=0.5"
	"&ImporteTotal=500.5"
	f"&Huella={HASH_1}"
	"&FechaHoraHusoGenRegistro=2026-02-01T14:00:00+01:00"
)

HASH_2 = hashlib.sha256(ISSUANCE_CHAIN_2.encode("utf-8")).hexdigest().upper()

ANULACION_CHAIN_1 = (
	f"IDEmisorFacturaAnulada={ISSUER}"
	f"&NumSerieFacturaAnulada={SERIES_NUMBER}"
	f"&FechaExpedicionFacturaAnulada={AEAT_DATE}"
	"&Huella="
	"&FechaHoraHusoGenRegistro=2026-02-02T09:00:00+01:00"
)

CANCELLATION_HASH_1 = hashlib.sha256(ANULACION_CHAIN_1.encode("utf-8")).hexdigest().upper()

ANULACION_CHAIN_2 = (
	f"IDEmisorFacturaAnulada={ISSUER}"
	"&NumSerieFacturaAnulada=2026-002"
	f"&FechaExpedicionFacturaAnulada={AEAT_DATE}"
	f"&Huella={CANCELLATION_HASH_1}"
	"&FechaHoraHusoGenRegistro=2026-02-02T09:30:00+01:00"
)

CANCELLATION_HASH_2 = hashlib.sha256(ANULACION_CHAIN_2.encode("utf-8")).hexdigest().upper()


def _issuance_data(**overrides) -> dict:
	"""Registro plano de entrada de build_issuance_record (contrato del lote 4a)."""
	data = {
		"issuer_nif": ISSUER,
		"series_number": SERIES_NUMBER,
		"issue_date": ISSUE_DATE,
		"invoice_type_code": "F1",
		"tax_breakdown": [
			{
				"tax_type": "IVA",
				"tax_rate": "21",
				"taxable_base": 1000.0,
				"tax_amount": 211.05,
				"operation_classification": "S1",
				"regime_key": "01",
				"exemption_cause": None,
				"recipients": None,
			}
		],
		"total_tax": 211.05,
		"total_amount": 1211.05,
		"previous_hash": "",
		"generation_timestamp": TS,
	}
	data.update(overrides)
	return data


class TestHashVectors(unittest.TestCase):
	"""Vectores de valor conocido: la cadena canónica se construye byte-exacta
	AQUÍ y se hashea de forma INDEPENDIENTE al adaptador."""

	def test_issuance_hash_first_record(self):
		record = {
			"IDEmisorFactura": ISSUER,
			"NumSerieFactura": SERIES_NUMBER,
			"FechaExpedicionFactura": AEAT_DATE,
			"TipoFactura": "F1",
			"CuotaTotal": 211.05,
			"ImporteTotal": 1211.05,
			"Huella": "",
			"FechaHoraHusoGenRegistro": TS,
		}
		self.assertEqual(compute_issuance_hash(record), HASH_1)

	def test_issuance_hash_chains_previous_hash_as_given(self):
		record = {
			"IDEmisorFactura": ISSUER,
			"NumSerieFactura": "2026-002",
			"FechaExpedicionFactura": AEAT_DATE,
			"TipoFactura": "F1",
			"CuotaTotal": 0.5,
			"ImporteTotal": 500.5,
			"Huella": HASH_1,
			"FechaHoraHusoGenRegistro": "2026-02-01T14:00:00+01:00",
		}
		self.assertEqual(compute_issuance_hash(record), HASH_2)

	def test_issuance_hash_normalizes_decimal_amount(self):
		# Decimal("1210.00") entra a la cadena como el float ERPNext: "1210.0".
		record = {
			"IDEmisorFactura": ISSUER,
			"NumSerieFactura": "2026-003",
			"FechaExpedicionFactura": AEAT_DATE,
			"TipoFactura": "F1",
			"CuotaTotal": Decimal("211.05"),
			"ImporteTotal": Decimal("1211.05"),
			"Huella": "",
			"FechaHoraHusoGenRegistro": TS,
		}
		canonical = ISSUANCE_CHAIN_1.replace("NumSerieFactura=2026-001", "NumSerieFactura=2026-003")
		expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
		self.assertEqual(compute_issuance_hash(record), expected)

	def test_cancellation_hash_first_record(self):
		record = {
			"IDEmisorFacturaAnulada": ISSUER,
			"NumSerieFacturaAnulada": SERIES_NUMBER,
			"FechaExpedicionFacturaAnulada": AEAT_DATE,
			"Huella": "",
			"FechaHoraHusoGenRegistro": "2026-02-02T09:00:00+01:00",
		}
		self.assertEqual(compute_cancellation_hash(record), CANCELLATION_HASH_1)

	def test_cancellation_hash_chains(self):
		record = {
			"IDEmisorFacturaAnulada": ISSUER,
			"NumSerieFacturaAnulada": "2026-002",
			"FechaExpedicionFacturaAnulada": AEAT_DATE,
			"Huella": CANCELLATION_HASH_1,
			"FechaHoraHusoGenRegistro": "2026-02-02T09:30:00+01:00",
		}
		self.assertEqual(compute_cancellation_hash(record), CANCELLATION_HASH_2)

	def test_hash_is_uppercase_sha256_hex(self):
		hash_value = compute_issuance_hash(
			{
				"IDEmisorFactura": ISSUER,
				"NumSerieFactura": SERIES_NUMBER,
				"FechaExpedicionFactura": AEAT_DATE,
				"TipoFactura": "F1",
				"CuotaTotal": 211.05,
				"ImporteTotal": 1211.05,
				"Huella": "",
				"FechaHoraHusoGenRegistro": TS,
			}
		)
		self.assertEqual(hash_value, hash_value.upper())
		self.assertEqual(len(hash_value), 64)
		int(hash_value, 16)  # hex válido


class TestChainOf3(unittest.TestCase):
	"""Encadenamiento: 3 registros, huellas todas distintas, sensibilidad 1 byte."""

	def _record(self, series_number: str, previous_hash: str) -> dict:
		return {
			"IDEmisorFactura": ISSUER,
			"NumSerieFactura": series_number,
			"FechaExpedicionFactura": AEAT_DATE,
			"TipoFactura": "F1",
			"CuotaTotal": 21.0,
			"ImporteTotal": 121.0,
			"Huella": previous_hash,
			"FechaHoraHusoGenRegistro": TS,
		}

	def test_chain_of_3_and_sensitivity(self):
		hash_1 = compute_issuance_hash(self._record("2026-001", ""))
		hash_2 = compute_issuance_hash(self._record("2026-002", hash_1))
		hash_3 = compute_issuance_hash(self._record("2026-003", hash_2))

		self.assertTrue(all(h != "" for h in (hash_1, hash_2, hash_3)))
		self.assertEqual(len({hash_1, hash_2, hash_3}), 3)

		# Cambiar UN byte de entrada cambia la huella.
		record_1b = self._record("2026-002", hash_1)
		record_1b["TipoFactura"] = "F2"
		self.assertNotEqual(compute_issuance_hash(record_1b), hash_2)

		record_1b = self._record("2026-002", hash_1)
		record_1b["ImporteTotal"] = 121.5
		self.assertNotEqual(compute_issuance_hash(record_1b), hash_2)

		record_1b = self._record("2026-002", hash_1)
		record_1b["FechaHoraHusoGenRegistro"] = TS.replace("13:", "14:")
		self.assertNotEqual(compute_issuance_hash(record_1b), hash_2)

		# La huella intermedia alterada cambia la siguiente de la cadena.
		fake_record_3 = self._record("2026-003", "00" * 32)
		self.assertNotEqual(compute_issuance_hash(fake_record_3), hash_3)


class TestAmountFormat(unittest.TestCase):
	"""La referencia usa str() del float ERPNext: 1210.0 -> "1210.0", 0.5 ->
	"0.5" — PUNTO decimal, sin coma española, sin relleno a 2 decimales."""

	def _hash_with_amounts(self, cuota, importe) -> str:
		return compute_issuance_hash(
			{
				"IDEmisorFactura": ISSUER,
				"NumSerieFactura": SERIES_NUMBER,
				"FechaExpedicionFactura": AEAT_DATE,
				"TipoFactura": "F1",
				"CuotaTotal": cuota,
				"ImporteTotal": importe,
				"Huella": "",
				"FechaHoraHusoGenRegistro": TS,
			}
		)

	def test_vector_1210_0(self):
		canonical = (
			f"IDEmisorFactura={ISSUER}&NumSerieFactura={SERIES_NUMBER}"
			f"&FechaExpedicionFactura={AEAT_DATE}&TipoFactura=F1"
			"&CuotaTotal=1210.0&ImporteTotal=2210.0&Huella="
			f"&FechaHoraHusoGenRegistro={TS}"
		)
		expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
		self.assertEqual(self._hash_with_amounts(1210.0, 2210.0), expected)

	def test_vector_0_5(self):
		canonical = (
			f"IDEmisorFactura={ISSUER}&NumSerieFactura={SERIES_NUMBER}"
			f"&FechaExpedicionFactura={AEAT_DATE}&TipoFactura=F1"
			"&CuotaTotal=0.5&ImporteTotal=100.5&Huella="
			f"&FechaHoraHusoGenRegistro={TS}"
		)
		expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
		self.assertEqual(self._hash_with_amounts(0.5, 100.5), expected)

	def test_decimal_normalizes_to_float(self):
		# Decimal("1210.00") y float 1210.0 producen la MISMA cadena "1210.0".
		self.assertEqual(
			self._hash_with_amounts(Decimal("1210.00"), Decimal("2210.00")),
			self._hash_with_amounts(1210.0, 2210.0),
		)

	def test_build_stores_floats(self):
		record = build_issuance_record(
			_issuance_data(total_tax=Decimal("1210.00"), total_amount=Decimal("2210.00"))
		)
		self.assertIsInstance(record["CuotaTotal"], float)
		self.assertEqual(record["CuotaTotal"], 1210.0)
		self.assertIsInstance(record["ImporteTotal"], float)
		self.assertEqual(record["ImporteTotal"], 2210.0)


class TestBuildIssuanceRecord(unittest.TestCase):
	def test_complete_record(self):
		record = build_issuance_record(_issuance_data())

		self.assertEqual(record["IDEmisorFactura"], ISSUER)
		self.assertEqual(record["NumSerieFactura"], SERIES_NUMBER)
		self.assertEqual(record["FechaExpedicionFactura"], AEAT_DATE)
		self.assertEqual(record["TipoFactura"], "F1")
		self.assertEqual(record["CuotaTotal"], 211.05)
		self.assertEqual(record["ImporteTotal"], 1211.05)
		self.assertEqual(record["FechaHoraHusoGenRegistro"], TS)
		self.assertEqual(record["TipoHuella"], "01")
		self.assertEqual(record["IDVersion"], "1.0")
		self.assertEqual(record["PrimerRegistro"], "S")
		self.assertEqual(record["Huella"], HASH_1)

		# Sin opcionales vacíos: TipoRectificativa y FacturasRectificadas omitidos.
		self.assertNotIn("TipoRectificativa", record)
		self.assertNotIn("FacturasRectificadas", record)

		# Desglose presente con la forma AEAT exacta de la referencia.
		detail = record["Desglose"]["DetalleDesglose"]
		self.assertEqual(len(detail), 1)
		self.assertEqual(detail[0]["Impuesto"], "01")
		self.assertEqual(detail[0]["TipoImpositivo"], "21")
		self.assertEqual(detail[0]["BaseImponibleOimporteNoSujeto"], 1000.0)
		self.assertEqual(detail[0]["CuotaRepercutida"], 211.05)
		self.assertEqual(detail[0]["CalificacionOperacion"], "S1")
		self.assertEqual(detail[0]["ClaveRegimen"], "01")
		self.assertNotIn("CausaExenta", detail[0])

	def test_date_str_passes_through(self):
		record = build_issuance_record(_issuance_data(issue_date=AEAT_DATE))
		self.assertEqual(record["FechaExpedicionFactura"], AEAT_DATE)

	def test_first_record(self):
		primer = build_issuance_record(_issuance_data())
		self.assertEqual(primer["PrimerRegistro"], "S")
		segundo = build_issuance_record(
			_issuance_data(
				series_number="2026-002",
				total_tax=0.5,
				total_amount=500.5,
				previous_hash=HASH_1,
				generation_timestamp="2026-02-01T14:00:00+01:00",
			)
		)
		self.assertEqual(segundo["PrimerRegistro"], "N")
		self.assertEqual(segundo["Huella"], HASH_2)

	def test_rectification(self):
		rectificada = {
			"issuer_nif": ISSUER,
			"series_number": "2025-100",
			"issue_date": date(2025, 12, 31),
		}
		record = build_issuance_record(
			_issuance_data(
				invoice_type_code="R1",
				rectified_invoices=[rectificada],
				tax_breakdown=[
					{
						"tax_type": "IVA",
						"tax_rate": "21",
						"taxable_base": -1000.0,
						"tax_amount": -211.05,
						"operation_classification": "S1",
						"regime_key": "01",
						"exemption_cause": None,
						"recipients": None,
					}
				],
				total_tax=-211.05,
				total_amount=-1211.05,
				previous_hash=HASH_1,
			)
		)
		self.assertEqual(record["TipoRectificativa"], "I")
		self.assertEqual(record["PrimerRegistro"], "N")
		rectified_list = record["FacturasRectificadas"]["IDFacturaRectificada"]
		self.assertEqual(len(rectified_list), 1)
		self.assertEqual(rectified_list[0]["IDEmisorFactura"], ISSUER)
		self.assertEqual(rectified_list[0]["NumSerieFactura"], "2025-100")
		self.assertEqual(rectified_list[0]["FechaExpedicionFactura"], "31-12-2025")

	def test_explicit_rectification_type_prevails(self):
		record = build_issuance_record(_issuance_data(invoice_type_code="R1", rectification_type="S"))
		self.assertEqual(record["TipoRectificativa"], "S")


class TestIsoDateStringVectors(unittest.TestCase):
	"""Vectores del fix de emisión (lote 4c): frappe entrega los Date como
	str ISO-8601 «YYYY-MM-DD» en el doc en memoria (p. ej. posting_date
	fijado por un hook) — el adaptador la NORMALIZA al formato congelado
	dd-mm-aaaa en el registro Y en la cadena canónica de la huella (alta,
	anulación y FacturasRectificadas comparten _format_date). Las fechas ya
	dd-mm-aaaa siguen pasando tal cual (los vectores del 4a quedan intactos)."""

	ISO_DATE = "2026-08-31"
	AEAT_DATE_STR = "31-08-2026"

	def test_alta_iso_in_record_and_hash(self):
		canonical = (
			f"IDEmisorFactura={ISSUER}&NumSerieFactura={SERIES_NUMBER}"
			f"&FechaExpedicionFactura={self.AEAT_DATE_STR}&TipoFactura=F1"
			"&CuotaTotal=211.05&ImporteTotal=1211.05&Huella="
			f"&FechaHoraHusoGenRegistro={TS}"
		)
		expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
		record = build_issuance_record(_issuance_data(issue_date=self.ISO_DATE))
		self.assertEqual(record["FechaExpedicionFactura"], self.AEAT_DATE_STR)
		self.assertEqual(record["Huella"], expected)

	def test_anulacion_iso_in_record_and_hash(self):
		canonical = (
			f"IDEmisorFacturaAnulada={ISSUER}&NumSerieFacturaAnulada={SERIES_NUMBER}"
			f"&FechaExpedicionFacturaAnulada={self.AEAT_DATE_STR}&Huella="
			"&FechaHoraHusoGenRegistro=2026-02-02T09:00:00+01:00"
		)
		expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest().upper()
		record = build_cancellation_record(
			{
				"issuer_nif": ISSUER,
				"series_number": SERIES_NUMBER,
				"issue_date": self.ISO_DATE,
				"previous_hash": "",
				"generation_timestamp": "2026-02-02T09:00:00+01:00",
			}
		)
		self.assertEqual(record["FechaExpedicionFacturaAnulada"], self.AEAT_DATE_STR)
		self.assertEqual(record["Huella"], expected)

	def test_iso_in_rectified_invoices(self):
		record = build_issuance_record(
			_issuance_data(
				invoice_type_code="R1",
				rectified_invoices=[
					{
						"issuer_nif": "87654321Z",
						"series_number": "EXT-2026-001",
						"issue_date": "2026-05-10",
					}
				],
			)
		)
		rectificada = record["FacturasRectificadas"]["IDFacturaRectificada"][0]
		self.assertEqual(rectificada["FechaExpedicionFactura"], "10-05-2026")


class TestBuildCancellationRecord(unittest.TestCase):
	def test_cancellation_record_shape(self):
		record = build_cancellation_record(
			{
				"issuer_nif": ISSUER,
				"series_number": SERIES_NUMBER,
				"issue_date": ISSUE_DATE,
				"previous_hash": "",
				"generation_timestamp": "2026-02-02T09:00:00+01:00",
			}
		)
		self.assertEqual(record["IDEmisorFacturaAnulada"], ISSUER)
		self.assertEqual(record["NumSerieFacturaAnulada"], SERIES_NUMBER)
		self.assertEqual(record["FechaExpedicionFacturaAnulada"], AEAT_DATE)
		self.assertEqual(record["FechaHoraHusoGenRegistro"], "2026-02-02T09:00:00+01:00")
		self.assertEqual(record["TipoHuella"], "01")
		self.assertEqual(record["IDVersion"], "1.0")
		self.assertEqual(record["PrimerRegistro"], "S")
		self.assertEqual(record["Huella"], CANCELLATION_HASH_1)

	def test_cancellation_chains_not_first_record(self):
		record = build_cancellation_record(
			{
				"issuer_nif": ISSUER,
				"series_number": "2026-002",
				"issue_date": ISSUE_DATE,
				"previous_hash": CANCELLATION_HASH_1,
				"generation_timestamp": "2026-02-02T09:30:00+01:00",
			}
		)
		self.assertEqual(record["PrimerRegistro"], "N")
		self.assertEqual(record["Huella"], CANCELLATION_HASH_2)


class TestBuildTaxBreakdown(unittest.TestCase):
	def test_aggregates_two_rates(self):
		rows = [
			{
				"tax_type": "IVA",
				"tax_rate": "21",
				"taxable_base": 100.0,
				"tax_amount": 21.0,
				"operation_classification": "S1",
				"regime_key": "01",
				"exemption_cause": None,
				"recipients": None,
			},
			{
				"tax_type": "IVA",
				"tax_rate": "21",
				"taxable_base": 200.0,
				"tax_amount": 42.0,
				"operation_classification": "S1",
				"regime_key": "01",
				"exemption_cause": None,
				"recipients": None,
			},
			{
				"tax_type": "IVA",
				"tax_rate": "10",
				"taxable_base": 100.0,
				"tax_amount": 10.0,
				"operation_classification": "S1",
				"regime_key": "01",
				"exemption_cause": None,
				"recipients": None,
			},
		]
		detail = build_tax_breakdown(rows)
		self.assertEqual(len(detail), 2)
		by_rate = {row["TipoImpositivo"]: row for row in detail}
		self.assertEqual(by_rate["21"]["BaseImponibleOimporteNoSujeto"], 300.0)
		self.assertEqual(by_rate["21"]["CuotaRepercutida"], 63.0)
		self.assertEqual(by_rate["10"]["BaseImponibleOimporteNoSujeto"], 100.0)
		self.assertEqual(by_rate["10"]["CuotaRepercutida"], 10.0)

	def test_round_half_up(self):
		detail = build_tax_breakdown(
			[
				{
					"tax_type": "IVA",
					"tax_rate": "21",
					"taxable_base": Decimal("100.005"),
					"tax_amount": Decimal("21.005"),
					"operation_classification": "S1",
					"regime_key": "01",
					"exemption_cause": None,
					"recipients": None,
				}
			]
		)
		self.assertEqual(detail[0]["BaseImponibleOimporteNoSujeto"], 100.01)
		self.assertEqual(detail[0]["CuotaRepercutida"], 21.01)

	def test_exemption_cause_only_when_defined(self):
		base_row = {
			"tax_type": "IVA",
			"tax_rate": "21",
			"taxable_base": 100.0,
			"tax_amount": 0.0,
			"operation_classification": "S2",
			"regime_key": "01",
			"recipients": None,
		}
		con_causa = build_tax_breakdown([{**base_row, "exemption_cause": "E2"}])
		# DetalleType vigente (SuministroInformacion.xsd): CHOICE — la causa
		# viaja como OperacionExenta (string E1-E8) y la calificación NO acompaña
		self.assertEqual(con_causa[0]["OperacionExenta"], "E2")
		self.assertNotIn("CausaExenta", con_causa[0])
		self.assertNotIn("CalificacionOperacion", con_causa[0])
		# Regla 1238 (AEAT, verificada en vivo): operación exenta → SIN
		# TipoImpositivo ni CuotaRepercutida — solo la base
		self.assertNotIn("TipoImpositivo", con_causa[0])
		self.assertNotIn("CuotaRepercutida", con_causa[0])
		sin_causa = build_tax_breakdown([{**base_row, "exemption_cause": None}])
		# sin exención: la calificación sí viaja, OperacionExenta no, y las
		# claves de tasa/cuota SÍ (la regla 1238 es solo para exentas)
		self.assertEqual(sin_causa[0]["CalificacionOperacion"], "S2")
		self.assertIn("TipoImpositivo", sin_causa[0])
		self.assertIn("CuotaRepercutida", sin_causa[0])
		self.assertNotIn("OperacionExenta", sin_causa[0])
		self.assertNotIn("CausaExenta", sin_causa[0])

	def test_unknown_tax_fails(self):
		with self.assertRaises(ValueError):
			build_tax_breakdown(
				[
					{
						"tax_type": "IRPF",
						"tax_rate": "19",
						"taxable_base": 100.0,
						"tax_amount": 19.0,
						"operation_classification": "S1",
						"regime_key": "01",
						"exemption_cause": None,
						"recipients": None,
					}
				]
			)

	def test_empty_returns_empty(self):
		self.assertEqual(build_tax_breakdown([]), [])


class TestGetRectificationType(unittest.TestCase):
	"""Tabla de la referencia: R1..R5 -> "I" (por diferencias); el resto -> ""."""

	def test_table(self):
		for code in ("R1", "R2", "R3", "R4", "R5"):
			self.assertEqual(get_rectification_type(code), "I", code)
		for code in ("F1", "F2", "F3", "", "XX", "r1"):
			self.assertEqual(get_rectification_type(code), "", code)


class TestFullInterior(unittest.TestCase):
	"""Interior COMPLETO del RegistroAlta/RegistroAnulacion (fix del drenaje
	en vivo: al WSDL de la AEAT le faltaban NombreRazonEmisor y el bloque
	SistemaInformatico, forma de la referencia aeat_data_adapter). Las
	claves nuevas viajan al record con la forma exacta; AUSENTES de la
	entrada → omitidas (retrocompatibilidad con el record_json del formato
	anterior); la HUELLA NO las incluye (cadena canónica congelada)."""

	SIF: ClassVar[dict[str, str]] = {
		"NombreRazon": "Productor del Software SL",
		"NIF": "B12345678",
		"NombreSistemaInformatico": "ES Erp",
		"IdSistemaInformatico": "128",
		"Version": "1.0",
		"NumeroInstalacion": "NOI-TEST",
		"TipoUsoPosibleSoloVerifactu": "S",
		"TipoUsoPosibleMultiOT": "N",
		"IndicadorMultiplesOT": "N",
	}

	def test_alta_full_interior(self):
		record = build_issuance_record(
			_issuance_data(
				issuer_name="Emisor SL",
				operation_description="Factura 2026-001 por cantidad 1000.0",
				correction="N",
				prior_rejection="X",
				recipient={"NombreRazon": "Cliente SL", "NIF": "87654321Z"},
				sif_info=self.SIF,
			)
		)
		self.assertEqual(record["NombreRazonEmisor"], "Emisor SL")
		self.assertEqual(record["DescripcionOperacion"], "Factura 2026-001 por cantidad 1000.0")
		self.assertEqual(record["Subsanacion"], "N")
		self.assertEqual(record["RechazoPrevio"], "X")
		# SinRegistroPrevio es campo del tipo ANULACIÓN — en el Alta JAMÁS
		# viaja (zeep lo rechaza: unexpected keyword, verificado en vivo).
		self.assertNotIn("SinRegistroPrevio", record)
		self.assertEqual(
			record["Destinatarios"],
			{"IDDestinatario": [{"NombreRazon": "Cliente SL", "NIF": "87654321Z"}]},
		)
		self.assertEqual(record["SistemaInformatico"], self.SIF)

	def test_alta_full_interior_frozen_hash(self):
		"""Las claves nuevas NO entran a la cadena canónica: el vector del
		lote 4a se mantiene byte-exacto con o sin ellas."""
		con_interior = build_issuance_record(
			_issuance_data(
				issuer_name="Emisor SL",
				operation_description="Factura 2026-001 por cantidad 1000.0",
				correction="N",
				prior_rejection="X",
				recipient={"NombreRazon": "Cliente SL", "NIF": "87654321Z"},
				sif_info=self.SIF,
			)
		)
		self.assertEqual(con_interior["Huella"], HASH_1)

	def test_alta_recipient_none_omits_block(self):
		"""POS (sin destinatario): el bloque Destinatarios NO viaja."""
		record = build_issuance_record(_issuance_data(recipient=None))
		self.assertNotIn("Destinatarios", record)

	def test_alta_omission_backward_compatible(self):
		"""Sin las claves nuevas (entrada del formato anterior) NADA se
		añade: el registro viejo sigue siendo válido — el driver enriquece
		el wire, no el adaptador."""
		record = build_issuance_record(_issuance_data())
		for clave in (
			"DescripcionOperacion",
			"NombreRazonEmisor",
			"Subsanacion",
			"RechazoPrevio",
			"SinRegistroPrevio",
			"Destinatarios",
			"SistemaInformatico",
		):
			self.assertNotIn(clave, record)
		self.assertEqual(record["Huella"], HASH_1)

	def test_anulacion_full_interior(self):
		record = build_cancellation_record(
			{
				"issuer_nif": ISSUER,
				"series_number": SERIES_NUMBER,
				"issue_date": ISSUE_DATE,
				"previous_hash": "",
				"generation_timestamp": "2026-02-02T09:00:00+01:00",
				"prior_rejection": "N",
				"no_prior_record": "N",
				"sif_info": self.SIF,
			}
		)
		self.assertEqual(record["RechazoPrevio"], "N")
		self.assertEqual(record["SinRegistroPrevio"], "N")
		self.assertEqual(record["SistemaInformatico"], self.SIF)
		# la anulación NO lleva emisor/destinatario/desglose/montos
		for clave in (
			"NombreRazonEmisor",
			"Destinatarios",
			"Desglose",
			"CuotaTotal",
			"ImporteTotal",
			"Subsanacion",
		):
			self.assertNotIn(clave, record)
		# huella congelada: mismo vector del lote 4a
		self.assertEqual(record["Huella"], CANCELLATION_HASH_1)

	def test_anulacion_omission_backward_compatible(self):
		record = build_cancellation_record(
			{
				"issuer_nif": ISSUER,
				"series_number": SERIES_NUMBER,
				"issue_date": ISSUE_DATE,
				"previous_hash": "",
				"generation_timestamp": "2026-02-02T09:00:00+01:00",
			}
		)
		for clave in ("RechazoPrevio", "SinRegistroPrevio", "SistemaInformatico"):
			self.assertNotIn(clave, record)
		self.assertEqual(record["Huella"], CANCELLATION_HASH_1)


class TestGetSpainTaxBreakupStub(unittest.TestCase):
	"""STUB CONTRATO 07: duck-typed, una fila «IVA - 21» -> una fila tipo 21."""

	def test_stub_iva_21(self):
		invoice = SimpleNamespace(
			taxes=[
				SimpleNamespace(
					description="IVA - 21",
					net_amount=1000.0,
					tax_amount=211.05,
				)
			]
		)
		rows = get_spain_tax_breakup(invoice)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_type"], "IVA")
		self.assertEqual(rows[0]["tax_rate"], "21")
		self.assertEqual(rows[0]["taxable_base"], 1000.0)
		self.assertEqual(rows[0]["tax_amount"], 211.05)
		self.assertEqual(rows[0]["operation_classification"], "S1")
		self.assertEqual(rows[0]["regime_key"], "01")
		self.assertIsNone(rows[0]["exemption_cause"])
		self.assertIsNone(rows[0]["recipients"])

	def test_stub_escape_hatches(self):
		invoice = SimpleNamespace(
			taxes=[
				SimpleNamespace(
					description="IVA - 21",
					net_amount=1000.0,
					tax_amount=0.0,
				)
			],
			es_verifactu_exempt_cause="E6",
			es_verifactu_regime_key="02",
		)
		rows = get_spain_tax_breakup(invoice)
		self.assertEqual(rows[0]["exemption_cause"], "E6")
		self.assertEqual(rows[0]["operation_classification"], "S2")
		self.assertEqual(rows[0]["regime_key"], "02")

	def test_stub_unknown_fails(self):
		invoice = SimpleNamespace(
			taxes=[SimpleNamespace(description="IRPF - 19", net_amount=100.0, tax_amount=19.0)]
		)
		with self.assertRaises(ValueError):
			get_spain_tax_breakup(invoice)

	def test_stub_exempt_operation_without_taxes(self):
		"""Operación exenta (L10) sin filas de impuesto: el WSDL exige
		≥1 DetalleDesglose SIEMPRE (minOccurs=1, verificado en vivo) →
		una fila sintética S2 con la base íntegra y cuota 0 — el
		OperacionExenta TODO que la referencia nunca implementó."""
		invoice = SimpleNamespace(
			taxes=[],
			es_verifactu_exempt_cause="E1",
			net_total=800.0,
		)
		rows = get_spain_tax_breakup(invoice)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["tax_type"], "IVA")
		self.assertEqual(rows[0]["tax_rate"], "0")
		self.assertEqual(rows[0]["taxable_base"], 800.0)
		self.assertEqual(rows[0]["tax_amount"], 0.0)
		self.assertEqual(rows[0]["operation_classification"], "S2")
		self.assertEqual(rows[0]["exemption_cause"], "E1")

		# sin causa de exención y sin impuestos: vacía de verdad
		# (la compuerta de validate la bloquea en la factura real)
		invoice_sin_causa = SimpleNamespace(taxes=[], net_total=100.0)
		self.assertEqual(get_spain_tax_breakup(invoice_sin_causa), [])


if __name__ == "__main__":
	unittest.main()
