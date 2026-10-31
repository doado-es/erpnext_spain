# 11 — SEPA: órdenes de pago y de cobro

Fase 4 · Depende de: 02, 09 · Relacionada con: 12 (confirming), 13 (conciliación)

> **Estado (31/10/2026): implementado** en el módulo ES Sepa: `pain.001.001.09` desde la Payment Order nativa, remesas de adeudos `pain.008.001.08` (`ES Sepa Direct Debit Batch`) con mandatos (`ES Sepa Mandate`), importación de `pain.002`, devoluciones con gastos. Los ficheros se validan contra los XSD oficiales (`erpnext_spain/schemas/iso20022`). Tests en `es_sepa/tests/test_sepa.py` (criterios 1-8). Pendiente: verificación previa del beneficiario (§7), versiones anteriores de los mensajes y plazos de cada banco.

## Objetivo

Generar los ficheros SEPA que la compañía envía a su banco:

- **Transferencias** a proveedores, acreedores y empleados (ISO 20022 `pain.001`).
- **Adeudos directos** a clientes, esquemas CORE y B2B (`pain.008`), con gestión de mandatos.

Y procesar las respuestas y devoluciones, dejando la contabilidad cuadrada con lo que luego llega en el extracto (spec 13).

## Estado normativo — **verificar con cada banco antes de implementar**

| Elemento | Situación |
|---|---|
| Versiones de mensaje | Las guías de implementación EPC de 2025 (en vigor desde el 05/10/2025) usan las versiones ISO 20022 de 2019: `pain.008.001.08` para adeudos **[verificado en la guía EPC SDD Core C2PSP 2025]** y, en el mismo paquete, `pain.001.001.09` para transferencias **[verificar en la guía SCT C2PSP]**. Algunos bancos españoles siguen aceptando las versiones anteriores (`pain.001.001.03`, `pain.008.001.02`) **[verificar banco a banco]**. |
| Direcciones postales | Desde el **22/11/2026** solo se admiten direcciones estructuradas o híbridas; las no estructuradas dejan de estar permitidas **[verificado en la guía EPC SDD Core C2PSP 2025]**. |
| Verificación del beneficiario (VoP) | Obligatoria desde octubre de 2025 por el Reglamento (UE) 2024/886. Para ficheros, los bancos ofrecen una verificación previa por lotes con un `pain.001` marcado y respuesta en `pain.002`, bajo acuerdo bilateral (p. ej. el apéndice de CaixaBank, vigente desde el 05/10/2025). |
| Guías AEB | Los bancos españoles publican sus adaptaciones a ISO 20022 (antiguos cuadernos 34, 19.14 y 19.44). Se toman como referencia de campos obligatorios y del identificador de presentador (NIF + sufijo). |

## Alcance

1. Datos bancarios de terceros y de la compañía.
2. Mandatos de adeudo.
3. Remesas de transferencias sobre la Payment Order nativa.
4. Remesas de adeudos (doctype propio).
5. Generación, validación y descarga de ficheros.
6. Respuestas (`pain.002`), devoluciones y rechazos.
7. Verificación previa del beneficiario por lotes.

Fuera de alcance: envío automático al banco (EBICS o API de pagos). Primera versión: descarga del fichero y subida a la banca electrónica.

## 1. Qué trae ERPNext v16 [verificado v16]

- `Bank Account` con IBAN, banco, compañía o tercero, y `integration_id`.
- `Payment Order`: solo para proveedores (`party: Supplier`), tipo Payment Request o Payment Entry, cuenta bancaria de la compañía y tabla de referencias (documento, importe, proveedor, modo de pago, cuenta bancaria). **No genera ningún fichero.**
- `Payment Request` y `Payment Entry`.
- No hay mandatos de adeudo ni remesas de cobro.

## 2. Datos bancarios

- IBAN validado (dígitos de control) al guardar `Bank Account`; BIC opcional dentro de SEPA.
- **Dirección estructurada** del tercero (calle, número, código postal, municipio, país) obligatoria para generar ficheros desde el 22/11/2026. Validación al generar la remesa, con la lista de terceros incompletos.
- Compañía: identificador de presentador (NIF + sufijo) por cuenta bancaria; para adeudos, el **identificador de acreedor SEPA** (ES + dígitos de control + sufijo + NIF).

## 3. Mandatos

Doctype "Mandato SEPA" (módulo ES Sepa, nombre final `ES Sepa Mandate`, por compañía, en `company_data_to_be_ignored` porque es un dato maestro que no debe borrarse con las transacciones, R8):

| Campo | Contenido |
|---|---|
| `referencia_mandato` | Única por acreedor (máx. 35 caracteres) |
| `customer`, `bank_account` | Deudor y su IBAN |
| `esquema` | CORE / B2B |
| `tipo` | Recurrente / Único |
| `fecha_firma`, `documento_firmado` | Fecha y PDF firmado |
| `estado` | Activo / Cancelado / Caducado |
| `fecha_ultimo_adeudo` | Para la caducidad (un mandato sin uso durante 36 meses caduca **[verificar]**) |
| `secuencia` | Primer adeudo (FRST) o recurrente (RCUR), según el esquema y el banco **[verificar si las guías 2025 aún exigen distinguirlos]** |

En el Customer: modo de pago "Domiciliación bancaria" y mandato por defecto.

## 4. Remesas de transferencias (pagos)

- Se usa la **Payment Order** nativa: selección de facturas de compra pendientes o Payment Entries en borrador, con la cuenta de la compañía.
- La app añade a Payment Order (custom fields): fecha de ejecución solicitada, `formato_sepa` (versión de `pain.001`), prioridad (normal / urgente), indicador de pago instantáneo **[verificar soporte en ficheros de cada banco]**.
- Acción "Generar fichero SEPA" (endpoint con rol, R6): valida IBAN y dirección de cada beneficiario, agrupa por fecha y genera el XML. Un `EndToEndId` estable por pago, guardado en la referencia, para enlazar después la respuesta, la verificación previa y el apunte del extracto.
- Contabilidad: los Payment Entries se crean (o se validan) con la fecha de ejecución. La conciliación con el extracto (spec 13) los casa por importe, fecha e `EndToEndId` o concepto.
- Las nóminas no se pagan desde aquí en esta versión (HRMS, R11).

## 5. Remesas de adeudos (cobros)

Doctype propio "Remesa de Adeudos" (módulo ES Sepa; nombre final `ES Sepa Direct Debit Batch`; submittable), porque ERPNext no tiene un equivalente para cobros:

- Cabecera: compañía, cuenta bancaria de abono, esquema (CORE/B2B), fecha de cobro solicitada, formato `pain.008`.
- Líneas: factura de venta, cliente, mandato, importe pendiente, `EndToEndId`, secuencia.
- Selección asistida: facturas validadas con modo de pago "Domiciliación bancaria", vencimiento en el rango y mandato activo.
- Validaciones: mandato activo y del mismo esquema, IBAN, dirección estructurada, plazos mínimos de presentación del banco **[verificar]**.
- Al validar: genera el XML y crea los Payment Entries con la fecha de cobro (o los deja en borrador, según ajuste de la compañía). Actualiza `fecha_ultimo_adeudo` de cada mandato.

## 6. Respuestas, devoluciones y rechazos

- Importación de `pain.002` (estado del fichero y de cada operación): marca en la remesa las operaciones rechazadas con su código de motivo.
- Devoluciones de adeudos posteriores al cobro (llegan en el extracto, spec 13, o como fichero de devoluciones del banco **[verificar formato que entrega cada banco]**): acción "Registrar devolución" que cancela o revierte el cobro, reabre la factura y anota los gastos de devolución (626 o 669 según contable).
- El historial de cada operación (enviada, rechazada, devuelta) queda en la línea de la remesa.

## 7. Verificación previa del beneficiario (opcional)

- Acción en la Payment Order: "Generar fichero de verificación", con el marcado que pida el banco (p. ej. instrumento local propietario `VoP` a nivel de bloque, en CaixaBank).
- Importación del `pain.002` de respuesta: coincidencia, coincidencia aproximada (con el nombre que devuelve el banco) o no coincidencia, por beneficiario. La orden no se puede generar en firme con no coincidencias sin confirmación explícita.
- Depende del acuerdo bilateral con cada banco; se activa por cuenta bancaria.

## Criterios de aceptación

1. Una Payment Order con tres facturas de dos proveedores genera un `pain.001.001.09` que valida contra el XSD oficial y contra las reglas de la guía EPC.
2. Una remesa de adeudos CORE genera un `pain.008.001.08` válido, con identificador de acreedor y referencia de mandato en cada operación.
3. Un tercero con dirección no estructurada bloquea la generación con un mensaje que lo identifica.
4. Un mandato cancelado o de otro esquema no se puede incluir en una remesa.
5. Un `pain.002` con una operación rechazada la marca en la remesa y deja la factura pendiente.
6. Una devolución reabre la factura y anota los gastos.
7. El `EndToEndId` de cada pago aparece en el fichero, en el Payment Entry y en la respuesta.
8. Sin rol, ningún endpoint genera ficheros.

## Pendiente de verificar o decidir

- Versiones aceptadas por cada banco con el que trabajen los clientes.
- Exigencia actual de FRST/RCUR y plazos de presentación.
- Caducidad de mandatos.
- Formato de los ficheros de devoluciones de cada banco.
- Envío automático (EBICS o API de pagos) para una versión posterior.
