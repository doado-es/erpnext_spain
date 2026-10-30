# Contrato wire contra el WSDL REAL de la AEAT (SistemaFacturacion.wsdl,
# tikeV1.0, descargado del entorno de pruebas prewww2 y versionado como
# fixture en tests/data/wsdl/).
#
# Por qué existe: la v1 en vivo contra prewww2 fue un whack-a-mole nivel por
# nivel (NombreRazonEmisor → SinRegistroPrevio → DetalleDesglose minOccurs →
# CausaExenta/OperacionExenta choice) — zeep valida en ORDEN de documento y
# el mock de los tests de remisión NO valida contra el schema. Este test
# serializa NUESTROS payloads con `Client.create_message` (construye el
# envelope SIN enviar) contra el WSDL versionado: cualquier deriva entre
# nuestra forma y el schema revienta AQUÍ, offline, antes del drain.
#
# Si la AEAT actualiza el WSDL: reemplazar los fixtures (WSDL + 5 XSDs del
# mismo directorio) y este test grita exactamente qué cambió.
#
# Los payloads salen de las funciones PURAS del adapter (build_issuance_record
# / build_cancellation_record — el record_json fuente de verdad) envueltos
# por el nesting wire del driver (_wire_record con registro fake: los
# fallbacks de enriquecimiento legado solo tocan la DB cuando faltan claves
# — aquí no faltan).

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace

from lxml import etree
from zeep import Client, Settings

WSDL_PATH = os.path.join(os.path.dirname(__file__), "data", "wsdl", "SistemaFacturacion.wsdl")

SIF = {
	"NombreRazon": "Emisor Test SL",
	"NIF": "B27331230",
	"NombreSistemaInformatico": "DOADOErp",
	"IdSistemaInformatico": "01",  # TextMax2Type (XSD): la AEAT rechaza >2 con código 1100
	"Version": "v1",
	"NumeroInstalacion": "GGU5KP55SR4WAUB2I3ZDZV7OKDPUJDPCBX77CBQBSYYLKVJK64YA",
	"TipoUsoPosibleSoloVerifactu": "S",
	"TipoUsoPosibleMultiOT": "N",
	"IndicadorMultiplesOT": "N",
}


def _local_wsdl_client() -> Client:
	"""Zeep sobre el WSDL versionado. Settings espejo del AEATClient real
	(forbid_entities=False: el XSD de la AEAT declara la ENTITY dsig) y
	force_https=False (fixture local, file://)."""
	return Client(
		"file://" + os.path.abspath(WSDL_PATH),
		settings=Settings(
			strict=True,
			forbid_dtd=False,
			forbid_entities=False,
			forbid_external=True,
			force_https=False,
		),
	)


def _serialize(client: Client, registro_factura: list[dict]) -> str:
	envelope = client.create_message(
		client.service,
		"RegFactuSistemaFacturacion",
		Cabecera={
			"ObligadoEmision": {
				"NombreRazon": "Emisor Test SL",
				"NIF": "B27331230",
			}
		},
		RegistroFactura=registro_factura,
	)
	return etree.tostring(envelope).decode()


def _ledger_record(data: dict, name: str = "VFR-00001", chain: int = 1) -> SimpleNamespace:
	return SimpleNamespace(
		name=name,
		company="Emisor Test SL",
		record_type="RegistroAlta",
		chain_index=chain,
		record_json=json.dumps(data),
		hash=data.get("Huella", ""),
		sales_invoice="FA00001",
	)


class TestWSDLContract(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.client = _local_wsdl_client()
		from erpnext_spain.es_verifactu.driver import VerifactuDriver

		cls.driver = VerifactuDriver()

	def _wire(self, data: dict, predecessors: dict | None = None, chain: int = 1) -> dict:
		from types import SimpleNamespace

		company_conf = SimpleNamespace(company_name="Emisor Test SL", tax_id="B27331230")
		return self.driver._wire_record(
			_ledger_record(data, chain=chain), predecessors or {}, "Emisor Test SL", company_conf
		)

	# --- ALTA: operación exenta (el caso FA00001) ---------------------------

	def test_exempt_issuance_serializes_against_real_wsdl(self):
		from erpnext_spain.es_verifactu.utils.data_adapter import build_issuance_record

		data = build_issuance_record(
			{
				"issuer_nif": "B27331230",
				"series_number": "FA00001",
				"issue_date": "31-08-2026",
				"invoice_type_code": "F1",
				"tax_breakdown": [
					{
						"tax_type": "IVA",
						"tax_rate": "0",
						"taxable_base": 800.0,
						"tax_amount": 0.0,
						"operation_classification": "S2",
						"exemption_cause": "E1",
						"regime_key": "01",
					}
				],
				"total_tax": 0.0,
				"total_amount": 800.0,
				"previous_hash": "",
				"generation_timestamp": "2026-08-31T20:00:00+02:00",
				"issuer_name": "Emisor Test SL",
				"operation_description": "Factura FA00001 por cantidad 800.0",
				"recipient": {"NombreRazon": "Cliente Test", "NIF": "34263831H"},
				"sif_info": SIF,
			}
		)
		xml = _serialize(self.client, [self._wire(data)])
		# el CHOICE del DetalleType: OperacionExenta con el código L10 como valor
		self.assertIn("OperacionExenta", xml)
		self.assertIn(">E1<", xml)
		self.assertNotIn("CausaExenta", xml)
		# sin calificación junto a la exenta (el choice la excluye)
		self.assertNotIn("CalificacionOperacion", xml)

	def test_taxable_issuance_iva21_serializes(self):
		from erpnext_spain.es_verifactu.utils.data_adapter import build_issuance_record

		data = build_issuance_record(
			{
				"issuer_nif": "B27331230",
				"series_number": "FA00002",
				"issue_date": "31-08-2026",
				"invoice_type_code": "F1",
				"tax_breakdown": [
					{
						"tax_type": "IVA",
						"tax_rate": "21",
						"taxable_base": 1000.0,
						"tax_amount": 210.0,
						"operation_classification": "S1",
						"regime_key": "01",
					}
				],
				"total_tax": 210.0,
				"total_amount": 1210.0,
				"previous_hash": "A" * 64,
				"generation_timestamp": "2026-08-31T20:00:00+02:00",
				"issuer_name": "Emisor Test SL",
				"operation_description": "Factura FA00002 por cantidad 1000.0",
				"recipient": {"NombreRazon": "Cliente Test", "NIF": "34263831H"},
				"sif_info": SIF,
			}
		)
		previous = _ledger_record(
			{"IDEmisorFactura": "B27331230", "NumSerieFactura": "FA00001",
			 "FechaExpedicionFactura": "31-08-2026"},
			chain=1,
		)
		previous.record_type = "RegistroAlta"
		previous.hash = "A" * 64
		xml = _serialize(self.client, [self._wire(data, {1: previous}, chain=2)])
		self.assertIn("CalificacionOperacion", xml)
		self.assertIn("RegistroAnterior", xml)  # encadenada: forma plana del XSD
		self.assertNotIn("OperacionExenta", xml)

	# --- ANULACIÓN: nunca enviada en vivo — su tipo se valida AQUÍ ----------

	def test_cancellation_serializes_against_real_wsdl(self):
		from erpnext_spain.es_verifactu.utils.data_adapter import build_cancellation_record

		data = build_cancellation_record(
			{
				"issuer_nif": "B27331230",
				"series_number": "FA00001",
				"issue_date": "31-08-2026",
				"previous_hash": "A" * 64,
				"generation_timestamp": "2026-08-31T20:00:00+02:00",
				"prior_rejection": "N",
				"no_prior_record": "N",
				"sif_info": SIF,
			}
		)
		record = _ledger_record(data, chain=2)
		record.record_type = "RegistroAnulacion"
		previous = _ledger_record(
			{"IDEmisorFactura": "B27331230", "NumSerieFactura": "FA00001",
			 "FechaExpedicionFactura": "31-08-2026"},
			chain=1,
		)
		previous.record_type = "RegistroAlta"
		previous.hash = "A" * 64
		company_conf = SimpleNamespace(company_name="Emisor Test SL", tax_id="B27331230")
		xml = _serialize(
			self.client,
			[self.driver._wire_record(record, {1: previous}, "Emisor Test SL", company_conf)],
		)
		self.assertIn("RegistroAnulacion", xml)
		# SinRegistroPrevio SÍ existe en el tipo Baja (a diferencia del Alta)
		self.assertIn("SinRegistroPrevio", xml)

	# --- Retrocompatibilidad: record_json legado con CausaExenta plano ------

	def test_legacy_flat_causa_desglose_normalized(self):
		from erpnext_spain.es_verifactu.driver import _wire_tax_breakdown

		legacy = {
			"DetalleDesglose": [
				{
					"Impuesto": "01",
					"ClaveRegimen": "01",
					"CalificacionOperacion": "S2",
					"CausaExenta": "E1",
					"TipoImpositivo": "0",
					"BaseImponibleOimporteNoSujeto": 800.0,
					"CuotaRepercutida": 0.0,
				}
			]
		}
		wire = _wire_tax_breakdown(legacy)
		row = wire["DetalleDesglose"][0]
		self.assertEqual(row["OperacionExenta"], "E1")
		self.assertNotIn("CausaExenta", row)
		self.assertNotIn("CalificacionOperacion", row)
		# Regla 1238 (AEAT): la exenta normalizada NO lleva tasa ni cuota
		self.assertNotIn("TipoImpositivo", row)
		self.assertNotIn("CuotaRepercutida", row)
		# el legado normalizado TAMBIÉN serializa contra el WSDL real
		xml = _serialize(
			self.client,
			[{
				"RegistroAlta": {
					"IDVersion": "1.0",
					"IDFactura": {
						"IDEmisorFactura": "B27331230",
						"NumSerieFactura": "FA00001",
						"FechaExpedicionFactura": "31-08-2026",
					},
					"RefExterna": "VFR-LEGACY",
					"NombreRazonEmisor": "Emisor Test SL",
					"TipoFactura": "F1",
					"DescripcionOperacion": "Factura FA00001 por cantidad 800.0",
					"Desglose": wire,
					"CuotaTotal": 0.0,
					"ImporteTotal": 800.0,
					"Encadenamiento": {"PrimerRegistro": "S"},
					"SistemaInformatico": SIF,
					"FechaHoraHusoGenRegistro": "2026-08-31T20:00:00+02:00",
					"TipoHuella": "01",
					"Huella": "A" * 64,
				}
			}],
		)
		self.assertIn("OperacionExenta", xml)


if __name__ == "__main__":
	unittest.main()
