# 05 — Facturación

Fase 3 · Depende de: 01, 02, 03 · Relacionada con: Verifactu (código base), 06, 14

## Objetivo

Numeración y series conformes con el Reglamento de facturación (RD 1619/2012), rectificativas con los datos que piden Verifactu y SII, situación de cobro con sus asientos PGC, y un formato de factura con el contenido obligatorio. Todo con `doc_events` y hooks documentados (sin extensión de la clase de Sales Invoice, R2).

**Punto de partida**: el código base ya implementa, dentro de Verifactu, la numeración al emitir, las series por tipo de factura y los tipos F1–F3 y R1–R5 (spec 04 del repo). Esta spec la **generaliza** a toda compañía española, la corrige (H1, H2) y añade lo que falta.

## Alcance

1. Numeración fiscal al emitir, con Verifactu o sin él.
2. Rectificativas.
3. Correlatividad.
4. Situación de cobro (dudoso cobro y pérdida).
5. Formato de impresión.

Fuera de alcance: el registro y envío de Verifactu (código base), facturación masiva desde albaranes (spec 07).

## 1. Numeración fiscal al emitir

**Lo que ya hace el código base** (módulo `es_verifactu`):

- Los borradores de Sales Invoice reciben un nombre temporal (`BORRADOR-…` o el patrón de borrador de la compañía, `es_verifactu_draft_series`) y **no consumen número fiscal**.
- Al validar (`before_submit`), y dentro de un cerrojo por empresa, el borrador se renombra a la serie fiscal que corresponde a su tipo de factura, según la tabla hija por empresa `ES Verifactu Series` (`series` + `invoice_type`, enlazada a `ES Verifactu Invoice Type`, que siembra F1, F2, F3 y R1–R5). La fecha de la factura se mantiene en la de hoy.
- Si la validación falla, la transacción entera se revierte y el número no se pierde. Hay índices de rendimiento para el renombrado y un test por cada caso.

**Cambios** (spec 01 §8):

- **Activación independiente de Verifactu**: la numeración al emitir se activa con el ajuste de empresa `numeracion_fiscal` (spec 01 §5), no con `es_verifactu_enabled`. La necesitan también las compañías que aún no tienen Verifactu y las que llevan sus libros por el SII (spec 14). Las tablas de series y tipos de factura dejan de ser "de Verifactu" y pasan a un módulo común de facturación (doctypes `ES Invoice Series` y `ES Invoice Type` y custom fields `es_invoice_series`, `es_draft_series`, `es_invoice_type` y `es_external_rectified_*`; el renombrado se hace ya en la fase 0, spec 01 §1, sin datos que migrar, maestro D3).
- **Sin numeración fiscal**: el `autoname` no asigna nombre y Frappe aplica la `naming_series` normal (H1).
- **Sin extensión de clase**: el `autoname` pasa a `doc_events` (H2).
- **Integraciones**: el nombre de un borrador no es estable a través de la validación. Se documenta en la guía de integración (ya lo advierte la spec del repo).

**Series recomendadas**: v16 trae la variable `ABBR` (abreviatura de la compañía) **[verificado v16]**, que sirve para series como `F-.ABBR.-.YY.-.#####` y `R-.ABBR.-.YY.-.#####` en `ES Invoice Series`. Las variables con llaves (`{campo}`) se resuelven contra campos del documento, no contra hooks; usar la forma con puntos.

## 2. Rectificativas

- **Serie**: la rectificativa toma la serie de su tipo (R1–R5) de `ES Invoice Series`. Desaparece la propuesta anterior de un `before_naming` con una serie de rectificativas por compañía.
- **Tipo**: ya existe en el código base (`es_invoice_type` en Sales Invoice, hoy `sc_verifactu_invoice_type`, con los tipos sembrados y la validación de coherencia F2/R5 con POS).
- **Rectificada**: `return_against` (nativo) o, para facturas de fuera del sistema, el trío de rectificada externa que ya existe (`es_external_rectified_nif`, `_number`, `_date`).
- **Nuevos campos** (custom fields en Sales Invoice, visibles en rectificativas):

| Campo | Valores |
|---|---|
| `metodo_rectificacion` | Por diferencias · Por sustitución **[verificar si el código base ya lo cubre en el registro Verifactu]** |
| `motivo_rectificacion` | Texto, obligatorio en rectificativas |

- El código base bloquea el *amend* de facturas con Verifactu (la corrección en España es siempre una rectificativa). Se extiende a toda compañía con `numeracion_fiscal`.

## 3. Correlatividad

Con la numeración al emitir y la fecha de la factura fijada en la de hoy, la correlatividad dentro de cada serie queda **garantizada por construcción**: el número se asigna en el orden de emisión y no hay borradores que reserven números. Por eso **se elimina** el control de la versión anterior de esta spec (comparar número y fecha entre facturas, campo `contador_serie`) y la decisión A2.

Queda un control: en compañías con `numeracion_fiscal`, una factura que se valida con una fecha distinta de la de hoy (p. ej. facturas creadas por importación o por API con fecha anterior) debe ser una decisión explícita. El código base ya mantiene la fecha de hoy al emitir y tiene una duda abierta sobre el bloqueo de fecha; se resuelve con el asesor.

## 4. Situación de cobro

No se toca el campo `status` nativo. Custom field `situacion_cobro` en Sales Invoice: Normal · Dudoso cobro · Pérdida.

Acciones (botones en la factura validada con saldo pendiente, rol Accounts Manager):

| Acción | Asiento (Journal Entry nativo, con tercero y dimensiones) — **esquema a validar por contable** |
|---|---|
| Pasar a dudoso cobro | 436 a 430 por el pendiente. |
| Dotar deterioro | 694 a 490. |
| Declarar pérdida definitiva | 650 a 436; y revertir el deterioro: 490 a 794. |
| Recuperar (cobro posterior) | Revertir según el estado. |

- Cada asiento enlaza la factura (campo de referencia en el Journal Entry) y la acción actualiza `situacion_cobro`.
- Job diario opcional: con `Company.meses_dudoso_cobro > 0`, **marca candidatas y avisa**; no contabiliza solo.
- Los cobros sobre facturas en dudoso cobro deben cancelar contra la 436: diseñar con el `party_account` del Journal Entry de reclasificación **[verificar el comportamiento de la conciliación de pagos de ERPNext con el saldo trasladado]**.

## 5. Formato de impresión

El código base ya tiene el formato "Factura España VeriFactu" (Jinja, predeterminado con Property Setter), con el QR y la leyenda de Verifactu y métodos Jinja propios (`get_verifactu_qr_code`, `get_verifactu_breakup`, `get_sc_display_name`). Se convierte en el formato español único:

- Se muestra el QR solo si la factura tiene registro Verifactu; sin Verifactu (p. ej. compañías en el SII) el resto del formato sirve igual.
- El desglose de impuestos sale de la clasificación y del Registro Fiscal IVA (specs 03 y 06), no de la descripción de la fila.
- Contenido mínimo del art. 6 RD 1619/2012 a comprobar en el formato: número y serie; fechas de expedición y de operación si difiere; nombre, NIF y domicilio de emisor y destinatario; descripción; base imponible por tipo, tipo y cuota; total; retenciones (spec 08).
- Menciones según la clasificación (spec 03): "Exenta" con el artículo, "Inversión del sujeto pasivo", "Entrega intracomunitaria exenta", etc.
- Rectificativas: referencia a la factura rectificada y motivo.
- Al desinstalar se borra el Property Setter del formato predeterminado (H5).

## Criterios de aceptación

1. Compañía con `numeracion_fiscal` y sin Verifactu: el borrador lleva nombre temporal y al validar recibe el siguiente número de la serie de su tipo; los tests existentes de naming pasan igual que con Verifactu.
2. Compañía sin `numeracion_fiscal`: la factura usa su `naming_series` desde el borrador (H1).
3. Una rectificativa R1 recibe la serie de R1; no se puede validar sin tipo ni `motivo_rectificacion`.
4. El *amend* está bloqueado en compañías con `numeracion_fiscal`, con mensaje que indica emitir una rectificativa.
5. Dos facturas validadas el mismo día en la misma serie llevan números consecutivos en el orden de validación; un fallo en la validación de la segunda no consume número.
6. Las cuatro acciones de cobro generan los asientos de la tabla y el saldo del cliente queda correcto en el informe Accounts Receivable.
7. El formato de impresión es el predeterminado tras instalar, muestra el QR solo con registro Verifactu y el Property Setter desaparece al desinstalar.
8. En una compañía no PGC no cambia nada.

## Pendiente de verificar o decidir

- Bloqueo de fechas distintas de la de hoy al emitir (asesor).
- Si el registro Verifactu del código base ya recoge el método de rectificación.
- Esquema contable de dudoso cobro y pérdida (contable).
- Conciliación de pagos tras reclasificar a 436.
