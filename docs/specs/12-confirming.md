# 12 — Confirming (formato estándar de la AEF)

Fase 4 · Depende de: 11 · Relacionada con: 13

> **Estado (31/10/2026): implementado** con el PDF oficial de la AEF v.03.26 (registros 1-7 de 250 posiciones): norma «Confirming» en la cuenta bancaria de la compañía (revisión del 31/10/2026, sustituye a `ES Confirming Contract`), `ES Confirming Batch` (doctype propio en lugar de la Payment Order, que solo admite Payment Entry y Payment Request), opciones contables A y B, cargo al vencimiento casado con el extracto por la referencia de la remesa. Tests en `es_sepa/tests/test_confirming.py` (criterios 1-6). Pendiente: ficheros de respuesta (el estándar no los define), validación con una entidad.

## Objetivo

Enviar a las entidades financieras las órdenes de pago a proveedores por confirming en el **formato estándar de la Asociación Española de Factoring (AEF)**, y llevar la contabilidad y el seguimiento hasta el cargo en cuenta al vencimiento.

## Estado del estándar — **leer el PDF oficial antes de implementar**

- La AEF publica un **"Formato Estándar de Confirming"** de uso voluntario en su web (ficheros normalizados), en español e inglés. La versión publicada se identifica como **v.03.26** (`Formato-Unico-DEFINITIVO-v.03.26.pdf`). También publica un formato estándar de factoring (v2).
- Entidades que lo soportan según fuentes del sector: CaixaBank, Banco Sabadell, ABANCA, Santander, Laboral Kutxa, entre otras **[verificar con cada entidad]**.
- **No he podido leer el PDF**: la estructura exacta (registros, longitudes, ficheros de respuesta) queda pendiente. Lo que sigue se basa en la documentación de un fabricante que lo implementa y debe contrastarse.

**Datos que recoge el formato** (según esa documentación):

| Bloque | Datos |
|---|---|
| Remesa | Número de contrato de confirming y sufijo, nombre y NIF del ordenante, fecha de remesa, IBAN de cargo (recomendado), divisa (EUR por defecto), tipo de remesa (1 estándar, 2 pronto pago, 3 otros), referencia del fichero (hasta 30 caracteres), domicilio opcional |
| Proveedor | Nombre (70), domicilio (65), población (40), código postal (obligatorio en nacionales), email (50), forma de pago (T transferencia / C cheque), IBAN (obligatorio en transferencias SEPA), BIC (internacionales), país del banco (fuera de SEPA), identificador (NIF, hasta 20) |
| Factura | Número de factura o abono (20, obligatorio), importe (admite negativos para abonos), fecha de emisión, fecha de vencimiento (obligatoria), fecha de prórroga (opcional), referencia de pago del cliente (16, útil para conciliar) |

## Alcance

1. Contratos de confirming por compañía y entidad.
2. Remesas de confirming desde facturas de compra pendientes.
3. Generación del fichero AEF.
4. Contabilidad de la remesa y del vencimiento.
5. Seguimiento de estados y respuestas de la entidad.

Fuera de alcance: factoring (cesión de facturas de venta), que puede usar el formato estándar de factoring de la AEF en una versión posterior.

## 1. Contratos

El contrato es una fila «Confirming» de la tabla **Normas bancarias** de la cuenta bancaria de la compañía (`ES Bank Account Norm`): número de contrato y sufijo, límite, tipo de remesa por defecto, opción contable y cuenta de la deuda con la entidad si se reclasifica (ver §3). La cuenta es la de cargo y la entidad es su banco; una cuenta tiene como mucho un contrato. La remesa (`ES Confirming Batch`) elige la cuenta (`bank_account`) en lugar del contrato.

## 2. Remesas

- Se reutiliza la **Payment Order** nativa de la spec 11 con un tipo propio "Confirming" (custom field) y el contrato. Así las órdenes de pago a proveedores, sean transferencias SEPA o confirming, viven en el mismo doctype.
- Selección: facturas de compra validadas, pendientes, con modo de pago "Confirming" y vencimiento en el rango. Los abonos del mismo proveedor pendientes de compensar entran con importe negativo.
- Validaciones: datos obligatorios del proveedor (dirección, código postal, IBAN si es transferencia, email), vencimiento informado y no anterior a la fecha de la remesa, límite del contrato.
- Generación del fichero en el formato AEF (endpoint con rol, R6). Referencia de pago estable por factura, guardada en la línea, para conciliar después.

## 3. Contabilidad — **esquema a validar por contable**

En el confirming la compañía sigue debiendo al vencimiento, pero ahora a través de la entidad. Dos opciones:

| Opción | Remesa | Vencimiento (cargo en cuenta) |
|---|---|---|
| A. Sin reclasificar (más simple) | Solo se marca la factura como remesada | Payment Entry 400 a 572 con la fecha de cargo |
| B. Reclasificar la deuda | Journal Entry 400 (proveedor) a cuenta de la entidad de confirming (p. ej. 5208 u otra que decida el contable) | Journal Entry de esa cuenta a 572 |

Propuesta: opción A por defecto, configurable por contrato. En los dos casos, el anticipo que el proveedor pida a la entidad no afecta a la contabilidad de la compañía.

El cargo al vencimiento se casa con el extracto (spec 13) por importe, fecha y referencia de la remesa.

## 4. Estados

En la línea de la remesa: generada · enviada · aceptada por la entidad · rechazada (con motivo) · anticipada al proveedor (informativo) · pagada al vencimiento. Se actualizan a mano o importando el fichero de respuesta de la entidad si el estándar lo define **[verificar en el PDF]**.

## Criterios de aceptación

1. Una remesa con facturas y un abono de dos proveedores genera un fichero que cumple el formato estándar AEF (validación contra la especificación y, si es posible, contra el validador de una entidad).
2. Un proveedor sin código postal o sin IBAN en pago por transferencia bloquea la generación con un mensaje que lo identifica.
3. Una factura con vencimiento anterior a la remesa no se puede incluir.
4. Con la opción A, el cargo al vencimiento importado del extracto se casa con los pagos de la remesa y deja las facturas pagadas.
5. Con la opción B, los asientos de remesa y de vencimiento cuadran y llevan dimensiones (R9).
6. Sin rol, el endpoint de generación no responde.

## Pendiente de verificar o decidir

- **Leer el PDF oficial v.03.26** y fijar estructura de registros, longitudes, codificación y ficheros de respuesta.
- Entidades con las que trabajen los clientes y sus variaciones sobre el estándar.
- Opción contable por defecto (contable).
