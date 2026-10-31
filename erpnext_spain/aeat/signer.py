# Firma del contenido remitido a la AEAT (spec 13 §6).
#
# DECISIÓN DOCUMENTADA (passthrough): la verificación normativa del perfil de
# firma está PENDIENTE (spec 04 §Dudas: ¿TLS mutua suficiente o XAdES del
# registro exigido por la Orden HAC/1177/2024? — la referencia opera con TLS
# mutua contra el entorno de pruebas de la AEAT). Hasta confirmarlo, la
# remisión viaja SIN firma adicional del contenido: la autenticación la aporta
# TLS mutua con la MISMA credencial (ES AEAT Credential) que, si se exige
# XAdES, firmará también aquí — misma credencial autentica y firma (spec 13
# §6), y la pieza sería reutilizable por eFactura/Facturae (spec 06).
#
# SEAM para la implementación XAdES futura: los drivers llaman a `sign()` sobre
# el contenido ANTES de build_payload. Una implementación XAdES solo cambia
# el interior de este módulo — ni el cliente ni el manager ni los drivers se
# tocan. El material de firma (PEM de la credencial) se resuelve con el mismo
# helper que usa el cliente TLS:
# erpnext_spain.aeat.doctype.es_aeat_credential.es_aeat_credential.pem_paths.

from __future__ import annotations

from typing import Any


def sign(company: str, purpose: str, contenido: dict[str, Any]) -> dict[str, Any]:
	"""Firma `contenido` según el perfil exigido por el servicio de `purpose`.

	Implementación actual: passthrough documentado (ver cabecera del módulo) —
	devuelve el contenido sin modificar; la autenticación via TLS mutua con la
	credencial de (empresa, propósito).
	"""
	return contenido
