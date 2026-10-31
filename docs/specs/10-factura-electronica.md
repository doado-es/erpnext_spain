# 10 — Factura electrónica: B2G (Facturae/FACe) y B2B (RD 238/2026)

Fase 4 · Depende de: 03, 05, 06 · Relacionada con: 11 (estados de pago), 14 (SII), Verifactu (07)

## Objetivo

Emitir y recibir facturas electrónicas estructuradas en los dos marcos vigentes:

- **B2G**: facturas a las Administraciones Públicas en Facturae, firmadas y enviadas a FACe o a los puntos generales de entrada autonómicos.
- **B2B**: la factura electrónica obligatoria entre empresarios y profesionales (Ley 18/2022, "Crea y Crece"), desarrollada por el **RD 238/2026** y la **Orden HAC/1028/2026**, con comunicación de los estados de la factura y del pago.

No es lo mismo que Verifactu (spec 07): Verifactu regula el software que expide la factura y el registro que va a la AEAT; la factura electrónica regula el documento que se intercambia con el cliente. Una compañía puede tener que cumplir las dos cosas.

## Estado normativo — a 30/10/2026, **verificar en el BOE y en la sede de la AEAT antes de implementar**

| Elemento | Situación |
|---|---|
| B2G | Ley 25/2013. Formato Facturae (versión vigente 3.2.x **[verificar]**), firma XAdES, envío a FACe o al punto de entrada de cada comunidad, códigos DIR3 del destinatario (oficina contable, órgano gestor, unidad tramitadora). |
| B2B, norma | RD 238/2026, de 25 de marzo (BOE 31/03/2026, en vigor desde el 20/04/2026). Modifica el Reglamento de facturación (RD 1619/2012). |
| B2B, puesta en marcha | Orden HAC/1028/2026, de 2 de octubre (BOE 05/10/2026, en vigor el 06/10/2026), que regula la **Solución Pública de Facturación Electrónica (SPFE)** de la AEAT y abre los plazos. |
| Calendario de emisión y recepción | 06/10/2027 para volumen de operaciones superior a 8 M€; 06/10/2028 para el resto. |
| Calendario de estados de factura y pago | 06/10/2027 (> 8 M€); 06/10/2028 (personas jurídicas ≤ 8 M€); 06/10/2029 (personas físicas y entidades en atribución de rentas ≤ 8 M€). |
| Formato | Modelo semántico EN 16931 con cuatro sintaxis admitidas: UBL, CII, EDIFACT y Facturae. Según fuentes del sector, la SPFE y las copias que las plataformas privadas le remiten usan UBL **[verificar en la Orden]**. |
| Estados | Aceptación o rechazo de la factura y pago efectivo completo con su fecha, en un plazo máximo de 4 días naturales sin contar sábados, domingos ni festivos nacionales **[verificar artículos 10.3 y 12.3 del RD]**. |
| Documentación técnica de la SPFE | Servicios web, esquemas y entorno de pruebas: **pendiente de revisar en la sede de la AEAT**. |

## Alcance

1. Modelo interno de factura electrónica (EN 16931) construido desde Sales Invoice y el Registro Fiscal IVA.
2. Serialización a Facturae y a UBL (CII y EDIFACT solo si algún destinatario lo exige).
3. Firma electrónica con el certificado de la compañía.
4. B2G: datos DIR3, envío a FACe y seguimiento de estados.
5. B2B: envío y recepción por la SPFE o por una plataforma privada, a través de un adaptador.
6. Comunicación de estados: aceptación o rechazo y pago efectivo.
7. Recepción de facturas de proveedores como borradores de Purchase Invoice.

## 1. Modelo interno

- Una estructura Python intermedia (dataclasses) que sigue EN 16931: emisor, receptor, líneas, desglose de impuestos por calificación y tipo (spec 06), retenciones (spec 08), totales, medios de pago (IBAN, mandato SEPA), referencias (pedido, albarán, factura rectificada, DIR3).
- Se construye **solo desde documentos validados**. La factura electrónica no recalcula importes: los toma de la factura y del Registro Fiscal IVA para que coincidan con el libro de IVA y con Verifactu.
- Cada serializador (Facturae, UBL) transforma esta estructura; añadir una sintaxis no toca el resto.

## 2. Documento propio "Factura Electrónica" (módulo ES Efactura; nombre final `ES E-Invoice`)

| Campo | Contenido |
|---|---|
| `company`, `voucher_type`, `voucher_no` | Factura de origen (Sales Invoice) o destino (Purchase Invoice) |
| `direccion` | Emitida / Recibida |
| `ambito` | B2G / B2B |
| `formato` | Facturae / UBL / CII / EDIFACT |
| `canal` | FACe / Punto autonómico / SPFE / Plataforma privada / Descarga manual |
| `fichero` | XML firmado, privado |
| `huella` | Hash del XML |
| `estado` | Generada · Enviada · Registrada · Aceptada · Rechazada · Pagada · Anulada · Error |
| `identificador_externo` | Número de registro de FACe, de la SPFE o de la plataforma. **Solo lectura**, como pide la guía de Frappe para acuses de la Administración. |
| `historial_estados` | Tabla hija con fecha, estado, origen y mensaje |

Inalterable una vez enviada. Una rectificación se hace con una factura rectificativa (spec 05) y su propia factura electrónica.

## 3. Firma y certificados

- Se reutiliza **`ES AEAT Credential`** del código base (certificado `.p12`/`.pfx`, contraseña cifrada, fechas de validez, aviso diario de caducidad a 30, 7 y 1 días). **Revisión del 31/10/2026**: un único certificado por empresa, sin propósito, que firma Facturae y autentica VeriFactu y el SII; Company ya no tiene un campo de credencial por servicio. Requiere antes la corrección H3 de la clave privada (spec 01 §8).
- Firma XAdES (Facturae) con una librería mantenida **[elegir y verificar: compatible con la política de firma de Facturae]**.
- El aviso de caducidad y la protección de datos (`company_data_to_be_ignored`, `user_data_fields` con la contraseña redactada) ya existen en el código base.

## 4. B2G

- Custom fields en Customer: `es_administracion_publica`, y códigos DIR3 de oficina contable, órgano gestor, unidad tramitadora y, opcional, órgano proponente. Validación de formato del código DIR3.
- Al validar una Sales Invoice de un cliente con `es_administracion_publica`: se genera la Factura Electrónica en Facturae.
- Envío: servicio web de FACe para proveedores **[verificar versión de la API]** o descarga para subida manual. Los puntos autonómicos se cubren por descarga en la primera versión.
- Seguimiento: consulta periódica (job programado) del estado en FACe y actualización de `estado` e `historial_estados`.

## 5. B2B

- **Adaptador de canal** con una interfaz común: `enviar(factura)`, `consultar_estado(id)`, `recibir()`, `comunicar_estado(id, estado, fecha)`. Implementaciones:
  - SPFE de la AEAT, cuando su documentación técnica esté disponible.
  - Plataforma privada (decisión A9): un proveedor concreto, como adaptador intercambiable.
- **Emisión**: al validar una Sales Invoice de un cliente sujeto (empresario o profesional en España), se genera la Factura Electrónica en el formato del canal y se envía en segundo plano, con reintentos.
- **Recepción**: `recibir()` crea un borrador de Purchase Invoice: proveedor por NIF (si no existe, la factura queda en una bandeja de pendientes), líneas, impuestos según plantilla del proveedor y el XML adjunto. Nunca se valida sola.
- **Estados que comunica la compañía** como receptora:
  - Aceptación o rechazo: acción en el borrador de Purchase Invoice (rechazo con motivo).
  - Pago efectivo completo: cuando el pendiente de la Purchase Invoice llega a cero por un Payment Entry o un Journal Entry validados, con la fecha del pago. Se detecta con `doc_events` en Payment Entry y Journal Entry (`on_submit`/`on_cancel`), **no** en Payment Ledger Entry (R4).
- **Estados que recibe** como emisora: se guardan en `historial_estados` de su Factura Electrónica. El pago comunicado por el cliente es solo informativo; la contabilidad del cobro sigue saliendo del banco (spec 13).
- Plazo de 4 días: un job diario lista los estados pendientes de comunicar con su fecha límite y avisa de los que vencen.

## 6. Permisos y seguridad (R6)

- Envío, comunicación de estados y descarga del XML: rol Accounts Manager o un rol propio "Facturación Electrónica".
- Las llamadas a FACe, la SPFE o la plataforma privada solo se hacen desde jobs o endpoints con comprobación de rol.
- Las credenciales de la plataforma privada van en campos `Password` de un doctype de configuración por compañía.

## Criterios de aceptación

> **Estado B2B (31/10/2026)**: UBL 2.1 (EN 16931) desde la factura y el desglose común (`es_efactura/ubl.py`), validado contra los XSD de OASIS (`schemas/oasis/ubl21`) y las reglas aritméticas principales de EN 16931; adaptador de canal (`es_efactura/b2b.py`) con «Descarga manual» y «Simulado»; recepción a borrador de Purchase Invoice o a pendientes de proveedor; aceptación o rechazo; comunicación del pago efectivo completo desde Payment Entry y Journal Entry. Activación en Company (`es_einvoice_b2b`, `es_einvoice_channel`). Tests en `es_efactura/tests/test_b2b.py` (criterios 3-7). Pendiente: SPFE o plataforma privada (A9), Schematron completo y CIUS española, recargo de equivalencia en UBL.

> **Estado (31/10/2026): B2G implementado** en `es_efactura`: Facturae 3.2.2 (esquema oficial versionado en `schemas/`, validación local sin red), firma XAdES-EPES con `signxml` y la política Facturae v3.1 (identificador y huella SHA-1 publicados en facturae.gob.es), certificado de la credencial elegida en Company (`es_einvoice_credential`). Doctype `ES E-Invoice` con XML firmado privado, huella, estado e historial; en Sales Invoice, `es_einvoice` y `es_einvoice_status` de solo lectura y botón "Generar Facturae". Subida manual a FACe y registro manual del número de registro y de los estados. Rectificativas con `es_rectification_reason_code`, `es_correction_method` y `es_rectification_reason` (spec 05 §2). Una factura presentada en FACe no se puede cancelar. Datos nuevos: tipo de persona y nombre y apellidos (Customer, Company), DIR3 (Customer), unidad Facturae (UOM), medio de pago Facturae (Mode of Payment). Limitaciones de esta versión: solo euros, sin redondeo del total y sin descuentos separados (el precio unitario va neto). Pendiente el criterio 1 en su parte manual: validar un XML real con el validador oficial.

1. Una factura a una Administración genera un Facturae que valida contra el XSD oficial y cuya firma verifica la herramienta de validación de la Administración **[identificar la herramienta oficial]**.
2. Los importes del XML coinciden al céntimo con la factura y con el Registro Fiscal IVA, incluidas retenciones y recargo de equivalencia.
3. Una factura B2B genera un UBL que valida contra EN 16931 (reglas Schematron) y contra las reglas españolas que publique la AEAT.
4. Una rectificativa genera su propia factura electrónica con la referencia a la rectificada.
5. Un fichero UBL recibido crea un borrador de Purchase Invoice con el proveedor correcto; con un NIF desconocido queda en pendientes.
6. Pagar por completo una factura recibida genera la comunicación de pago con la fecha del pago; cancelar el pago antes de comunicarlo la anula.
7. Sin rol, ningún endpoint de envío responde.
8. El certificado no aparece en ninguna respuesta de la API.

## Pendiente de verificar o decidir

- **A9**: canal B2B, desarrollo propio contra la SPFE o integración con una plataforma privada.
- Documentación técnica de la SPFE (servicios, esquemas, autenticación, entorno de pruebas).
- Versión vigente de Facturae y de la API de FACe.
- Sintaxis obligatoria para las copias a la SPFE.
- Si la comunicación de pago debe hacerse también por pagos parciales o solo por el pago completo (el RD habla de pago efectivo completo).
