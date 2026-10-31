# 06 — Registro fiscal de IVA

Fase 3 · Depende de: 01, 02, 03, 05 · Bloquea: modelos, SII y Verifactu (07)

> **Estado (31/10/2026): implementado** en el módulo ES Iva (`es_iva/{breakdown,register,books,eu,setup}.py`, doctype `ES Vat Register`, informes `ES Issued Invoices Book`, `ES Received Invoices Book` y `ES VAT Return Draft`); tests en `es_iva/tests/test_vat_register.py` (criterios 1-9 y contrato con VeriFactu). Autorrepercusión con las dos filas de la plantilla (sin regional override). VeriFactu usa el desglose común cuando las filas están clasificadas. Pendiente: importaciones con DUA, criterio de caja, prorrata especial.

## Objetivo

Guardar, al validar cada factura, su desglose fiscal (una fila por calificación, tipo de operación y tipo impositivo) en un doctype propio del que saldrán los libros registro, los modelos, el SII y Verifactu. Incluye las operaciones con devengo especial (ISP, adquisiciones intracomunitarias, importaciones), que es lo que suele fallar.

## Alcance

1. DocType Registro Fiscal IVA.
2. Generación al validar y anulación al cancelar.
3. Autorrepercusión de ISP y adquisiciones intracomunitarias (asientos y registro).
4. Reconstrucción.
5. Libros registro de facturas expedidas y recibidas, y borrador de liquidación.

Fuera de alcance: presentación de modelos y ficheros AEAT (spec 07), IGIC/IPSI (A5), regularización de bienes de inversión en años posteriores.

## 1. DocType "Registro Fiscal IVA" (módulo ES Iva; nombre final del doctype `ES Vat Register`)

No es editable por usuarios (solo lectura para Accounts User y Accounts Manager; lo escribe el sistema). Tiene campo `company` y **no** va en `company_data_to_be_ignored`: el borrado de transacciones debe eliminarlo (R8).

| Grupo | Campos |
|---|---|
| Origen | `company`, `libro` (Expedidas/Recibidas), `voucher_type`, `voucher_no`, `tax_row` |
| Fechas | `fecha_contabilizacion`, `fecha_expedicion` (en compras, `bill_date`), `fecha_operacion`, `ejercicio`, `periodo_trimestre`, `periodo_mes` |
| Tercero | `party_type`, `party`, `party_name`, `nif`, `tipo_identificacion`, `pais` (copiados al validar; no cambian si se edita el tercero). El NIF ya viene validado por el verificador de NIF del código base (módulo `nif`); la denominación sigue su modelo de razón social y nombre comercial (`es_trade_name`). |
| Factura | `tipo_factura` (F1, F2 simplificada, R1–R5), `serie`, `numero`, `numero_proveedor`, `factura_rectificada`, `total_factura` |
| Clasificación | `tipo_impuesto`, `calificacion_iva`, `tipo_operacion`, `deducibilidad`, `clave_retencion` (spec 03) |
| Importes (moneda de la compañía) | `base_imponible`, `tipo_impositivo`, `cuota`, `cuota_deducible`, `prorrata_aplicada` |
| Estado | `autorrepercutida` (check), `anulado` (check), `sin_clasificar` (check) |

Índices: `(company, libro, fecha_contabilizacion)`, `(voucher_type, voucher_no)`.

## 2. Generación

- `doc_events` en Sales Invoice y Purchase Invoice: `on_submit` genera, `on_cancel` marca `anulado = 1` (no borra). Salida temprana con `is_pgc_company` (R4, R7).
- **Desglose por artículo con la tabla nativa de v16 `item_wise_tax_details` (doctype hijo `Item Wise Tax Detail`: `item_row`, `tax_row`, `rate`, `amount`, `taxable_amount`, en moneda de la compañía)** **[verificado v16]**. La base sale de `taxable_amount`, no de dividir la cuota por el tipo. Esto sustituye al JSON `item_wise_tax_detail` de v15.
- Agrupación: por fila de impuesto y, dentro de ella, por (`calificacion_iva`, `tipo_operacion`, `tipo_impositivo`). La clasificación del Item Tax Template del artículo manda sobre la de la fila (spec 03).
- Rectificativas: importes en negativo, `tipo_factura` = tipo de factura R1–R5 de la rectificativa (`es_invoice_type`, spec 05 §2), `factura_rectificada` = `return_against`.
- Compras: `cuota_deducible` = 0 si no deducible; en corriente y bien de inversión, cuota × prorrata general de la compañía (vacía = 100 %).
- Retenciones: se registran con `tipo_impuesto = Retención IRPF` y no entran en los libros de IVA. En ventas, este registro es la fuente de las retenciones soportadas; en compras, la fuente para los modelos es la tabla nativa `Tax Withholding Entry` (spec 08).
- Filas incompletas: `sin_clasificar = 1` y aviso al usuario. Si la compañía exige clasificación, la factura no llega a validarse (spec 03).
- Rendimiento: nada de consultas por artículo; las plantillas y la compañía se leen con caché.

## 3. ISP, adquisiciones intracomunitarias e importaciones

Problema que resolver: en estas compras la factura del proveedor no lleva IVA, pero el comprador debe **devengar** (repercutido) y, si procede, **deducir** (soportado) la misma cuota.

**Asientos.** **Propuesta alternativa implementada en los datos iniciales (spec 09, 30/10/2026), pendiente de confirmar**: las plantillas de compra de adquisición intracomunitaria y de inversión del sujeto pasivo llevan **dos filas**, IVA soportado a la 4720 (`Add`) y el mismo importe devengado a la 4770 (`Deduct`, `es_self_assessed = 1`). El total de la factura no cambia y el asiento de autorrepercusión lo hace ERPNext con la propia factura, sin regional override y sin depender del país del sistema. Si se adopta, el registro fiscal identifica la fila autorrepercutida por `es_self_assessed` y desaparece el requisito del país del sistema para este punto. Diseño original: Regional override de **`make_regional_gl_entries(gl_entries, doc)`** de Purchase Invoice **[verificado v16]**: si alguna fila tiene `calificacion_iva = S2` o `tipo_operacion` de adquisición intracomunitaria, añade a `gl_entries` el cargo a 4720 y el abono a 4770 por la cuota calculada (base × tipo de la plantilla) y los devuelve. Con dimensiones contables (R9).

- La región de un regional override se resuelve por el país de `frappe.flags.company` si está fijado, y si no, por el país del sistema **[verificado v16]**. En el punto donde Purchase Invoice llama a `make_regional_gl_entries` no se fija la compañía (a diferencia de `validate_regional`, que va dentro de `temporary_flag("company", …)`) **[verificado v16 en el punto de llamada]**. Consecuencia: **el override solo se ejecuta en sitios cuyo país del sistema sea España**. Se documenta como requisito de instalación y se abre una issue en `frappe/erpnext` para envolver la llamada con `temporary_flag("company", self.company)`, como ya hace con `validate_regional`. En todo caso, la función empieza con `is_pgc_company(doc.company)`.

**Registro.** Dos filas por cada parte autorrepercutida:

- Libro Recibidas, `autorrepercutida = 1`, cuota devengada (cuenta para el IVA devengado de la liquidación).
- Libro Recibidas, cuota soportada con su `cuota_deducible` según la deducibilidad.

**Importaciones (DUA).** El IVA se paga en aduana, no al proveedor. Propuesta: Purchase Invoice del agente de aduanas o de la AEAT con una línea de IVA de importación (`tipo_operacion = Importación`) cuya base es el valor en aduana del DUA (campo propio en la línea o en la factura). **Diseño a cerrar** en la primera iteración de esta spec.

## 4. Reconstrucción

Endpoint `rebuild_vat_register(company: str, dry_run: bool = True)`, `@frappe.whitelist(methods=["POST"])` porque modifica datos, rol Accounts Manager y `write` sobre la Company (R6):

- `dry_run`: cuenta facturas, filas y pendientes de clasificar, sin escribir.
- Real: job en cola `long`, sustituye las filas vigentes de cada factura validada y marca anuladas las de facturas canceladas. Sin `db.commit()` explícito (R5). Notifica al terminar.
- No modifica las facturas.

## 5. Libros y borrador de liquidación

Script Reports en el módulo ES Iva:

- **Libro registro de facturas expedidas** y **recibidas**: filas del registro filtradas por periodo, con totales por calificación y tipo. Excluye retenciones.
- **Borrador de liquidación de IVA** (no es el modelo 303): IVA devengado = cuotas de expedidas + autorrepercutidas; IVA deducible = `cuota_deducible` de recibidas (incluidas las autorrepercutidas deducibles); resultado. Marcado claramente como borrador.
- Permisos de lectura sobre Registro Fiscal IVA.

## 6. Contrato con Verifactu y SII

El código base construye el desglose de Verifactu con `get_spain_tax_breakup(invoice)` (`es_verifactu/utils/data_adapter.py`), hoy un stub que deduce impuesto y tipo de la descripción de la fila ("IVA - 21"). Las filas que devuelve tienen esta forma: `tax_type`, `tax_rate`, `taxable_base`, `tax_amount`, `operation_classification`, `regime_key`, `exemption_cause`, `recipients`.

- Una **única función pura** en `es_iva` construye el desglose de una factura a partir de su clasificación (spec 03) y de `item_wise_tax_details`. La usan el Registro Fiscal IVA (que la persiste), el adaptador de Verifactu (que sustituye el stub) y el SII (spec 14). Así no depende del orden en que se ejecuten los `on_submit` de cada módulo.
- **Retenciones**: no entran en el desglose de Verifactu (la AEAT las excluye; `CuotaTotal` es solo IVA y RE, e `ImporteTotal` incluye la retención). En el SII van aparte, como `CuotaRetencion` (spec 14). Lo recoge también el TODO del código base.
- **IGIC e IPSI**: el adaptador ya contempla los códigos de la AEAT; siguen fuera de alcance funcional (A5).
- Test de contrato: para cada caso de los criterios de aceptación, el desglose que recibe Verifactu coincide con las filas del Registro Fiscal IVA (excepto retenciones).

## Criterios de aceptación

1. Venta con líneas al 21 % y al 10 %: dos filas con base, tipo y cuota correctos (base = `taxable_amount`).
2. Venta en USD: importes del registro en euros iguales a los del GL.
3. Rectificativa: filas en negativo, tipo R1–R5 y factura rectificada informada.
4. Cancelar: filas anuladas, no borradas; el borrador de liquidación deja de contarlas.
5. **Compra con ISP de 1.000 € al 21 %**: el GL tiene 210 € en 4720 y 210 € en 4770; el registro tiene la fila autorrepercutida y la soportada; el borrador de liquidación da devengado 210, deducible 210 y resultado 0.
6. Igual con una adquisición intracomunitaria de servicios.
7. Compra corriente con prorrata del 60 %: `cuota_deducible` = 60 % de la cuota.
8. Reconstruir en `dry_run` no escribe; la reconstrucción real deja el registro igual que si las facturas se hubieran validado de nuevo.
9. En una compañía no PGC no se crea ninguna fila.

## Pendiente de verificar o decidir

- Si algún punto superior de la pila fija `frappe.flags.company` antes de `make_regional_gl_entries` (no lo hace el punto de llamada directo); comprobarlo en bench con un sitio cuyo país del sistema no sea España.
- Diseño definitivo de importaciones con DUA.
- Tratamiento del criterio de caja (régimen especial): fuera de esta versión salvo que se decida lo contrario.
