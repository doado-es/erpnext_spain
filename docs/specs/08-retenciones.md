# 08 — Retenciones de IRPF en compras y ventas

Fase 3 · Depende de: 01, 02, 03 · Bloquea: modelos 111, 115, 180, 190 y 130 (spec 07)

> **Estado (31/10/2026): implementado** (módulo ES Retenciones: `es_retenciones/{codes,setup,withholding}.py`, doctype `ES Leased Property`, informes `ES Withholdings Made` y `ES Withholdings Received`; tests en `es_retenciones/tests/test_withholding.py`, criterios 1-10). Verificado en bench: la fila de tipo negativo en ventas carga la 473, reduce total y pendiente y la rectificativa la invierte. Pendiente: A7 (periodo por fecha de pago), claves y subclaves del 190 y requisitos de exoneración de arrendamientos **[revisar]**.

## Objetivo

Gestionar las retenciones de IRPF en las dos direcciones:

- **Practicadas**: la compañía retiene a sus proveedores (profesionales, arrendadores, módulos, agrícolas, consejeros, cursos) en las facturas de compra.
- **Soportadas**: los clientes retienen a la compañía en sus facturas de venta (compañías o autónomos que facturan servicios profesionales).

Con los datos que necesitarán después los modelos 111, 115, 180, 190 y 130.

## Alcance

1. Configuración de categorías, grupos y tipos.
2. Retenciones practicadas en facturas de compra y anticipos.
3. Retenciones soportadas en facturas de venta.
4. Clasificación de las filas de retención.
5. Informes de retenciones practicadas y soportadas.

Fuera de alcance: retenciones de rendimientos del trabajo (nóminas, HRMS, R11), capital mobiliario (modelos 123/193), generación de los modelos y sus ficheros (spec 07).

## 1. Cómo lo gestiona ERPNext v16 [verificado v16]

**Doctypes**

| Doctype | Contenido |
|---|---|
| `Tax Withholding Category` | Tabla de tipos (`rates`), tabla de cuentas por compañía (`accounts`), base de cálculo (`tax_deduction_basis`: Net Total / Gross Total), umbrales con casillas para desactivarlos (`disable_transaction_threshold`, `disable_cumulative_threshold`), `round_off_tax_amount`, `tax_on_excess_amount`. Es global, no por compañía. |
| `Tax Withholding Rate` (hija) | `tax_withholding_rate`, `single_threshold`, `cumulative_threshold`, `from_date`, `to_date`, `tax_withholding_group`. |
| `Tax Withholding Group` | Solo un nombre. Sirve para tener tipos distintos dentro de una categoría. |
| `Tax Withholding Entry` (hija) | Una fila por retención: tercero, `tax_id`, categoría, tipo, `taxable_amount`, `withholding_amount`, documento y fecha de la base (`taxable_doctype/name/date`), documento y fecha de la retención (`withholding_doctype/name/date`), estado (Settled, Under Withheld, Over Withheld, Duplicate, Cancelled). |

**Dónde se aplica**

| Documento | Comportamiento |
|---|---|
| Purchase Invoice | `apply_tds` en la cabecera y en cada línea, con `tax_withholding_category` por línea; categoría y grupo por defecto desde el Supplier. Se calcula en `validate`, **después** de `super().validate()`. Crea una fila de impuesto con `is_tax_withholding_account = 1`, `charge_type = Actual`, `add_deduct_tax = Deduct` y la cuenta de la categoría para la compañía, y rellena `tax_withholding_entries`. |
| Payment Entry | `apply_tds` para pagos a proveedores, incluidos anticipos. La retención del anticipo se compensa luego con la factura. |
| Journal Entry | Solo en notas de crédito y de débito. |
| Sales Invoice | `SalesTaxWithholding` es la **TCS india** (impuesto recaudado en origen): crea la fila con `Add` y **aumenta** el total de la factura. Es lo contrario de la retención española en ventas, que **reduce** lo que paga el cliente. **No sirve para ventas.** |

**Detalles que condicionan el diseño**

- El tipo se elige buscando la fila de `rates` cuya fecha incluye la de la factura y cuyo grupo es **exactamente** el del documento. Si no la encuentra, ERPNext lanza un error. Cada categoría necesita, por tanto, una fila por cada grupo que puedan usar sus proveedores. La comparación es `cstr(row.tax_withholding_group) == cstr(grupo del documento)` y las fechas no pueden solaparse dentro de un mismo grupo (`TaxWithholdingCategory.get_applicable_tax_row` y `validate_dates`) **[verificado v16.51]**: el grupo **General** de las tablas de abajo es la fila **sin grupo**, que es la que toman los proveedores sin `tax_withholding_group`. No se crea un Tax Withholding Group "General".
- El NIF que guarda es el `tax_id` del tercero.
- Las piezas indias, como el *Lower Deduction Certificate*, quedan sin usar.
- `Sales Taxes and Charges` no tiene el campo `add_deduct_tax`; `Purchase Taxes and Charges` sí.

## 2. Encaje con la normativa española

| Requisito | ERPNext v16 | Decisión |
|---|---|---|
| Base: base imponible, sin IVA ni RE | `tax_deduction_basis = Net Total` | Nativo |
| Tipos que cambian con la fecha | Filas con `from_date`/`to_date` | Nativo |
| Tipos distintos para el mismo concepto (15 % general, 7 % inicio de actividad, reducción del 60 % en Ceuta, Melilla y La Palma) | Grupos | Nativo, generando las combinaciones (§3) |
| Líneas sin retención en la misma factura (suplidos) | `apply_tds` por línea | Nativo |
| Sin umbrales, salvo casos concretos | Umbrales desactivables | Desactivados |
| Anticipos con retención | Payment Entry con `apply_tds` | Nativo |
| La obligación de retener nace al pagar o abonar la renta (art. 78.1 RIRPF) | Retiene en la factura y en los anticipos | Contabilidad en la factura; periodo de los modelos: decisión A7 |
| Retención en ventas (el cliente retiene) | No existe (la TCS va con el signo contrario) | Diseño propio (§4) |
| Datos para 190 y 180 (NIF, clave, subclave, inmueble) | NIF sí; claves e inmueble no | Custom fields (§3) |

**Tipos 2026** según el cuadro de la AEAT (aplicable desde el 10/09/2026): profesionales 15 % (7 % en inicio de actividad, el año de inicio y los dos siguientes, y en recaudadores municipales, mediadores de seguros con auxiliares y delegados comerciales de SELAE); módulos 1 %; agrícolas y ganaderas 2 % (engorde de porcino y avicultura 1 %); forestales 2 %; arrendamiento de inmuebles urbanos 19 %; consejeros y administradores 35 % (19 % si la entidad factura menos de 100.000 €); cursos y conferencias 15 %; propiedad intelectual 15 % o 7 %. Reducción del 60 % para perceptores con la deducción del art. 68.4 LIRPF (Ceuta, Melilla y, desde el 10/09/2026, La Palma, por el RDL 23/2026). **Verificar el cuadro vigente al implementar.**

## 3. Retenciones practicadas (compras)

Se usa el mecanismo nativo de ERPNext, sin overrides (R2).

**Categorías** (creadas por código en `after_install`/`after_migrate`; su fila de cuenta 4751 para la compañía se añade en "Aplicar plan PGC"; reglas de creación y actualización en la spec 09):

| Categoría | Modelo trimestral | Resumen anual | Grupos con fila de tipo |
|---|---|---|---|
| Actividades profesionales | 111 | 190 | General, Inicio de actividad, Reducción 68.4 |
| Actividades profesionales — 7 % por actividad | 111 | 190 | General, Reducción 68.4 |
| Módulos (estimación objetiva) | 111 | 190 | General, Reducción 68.4 |
| Actividades agrícolas, ganaderas y forestales | 111 | 190 | General, Reducción 68.4 |
| Consejeros y administradores | 111 | 190 | General, Entidad < 100.000 € |
| Cursos y conferencias | 111 | 190 | General, Reducción 68.4 |
| Arrendamiento de inmuebles urbanos | 115 | 180 | General, Reducción 68.4 |

- Todas con `tax_deduction_basis = Net Total`, umbrales desactivados y `round_off_tax_amount = 0`.
- Cada combinación de categoría y grupo tiene su fila de tipo con `from_date` y un `to_date` lejano. Un cambio legal se aplica cerrando la fila vigente y añadiendo otra (patch idempotente).
- Custom fields en Tax Withholding Category: `modelo` (111/115), `clave_190` y `subclave_190` **[verificar claves y subclaves en la orden vigente del modelo 190]**.
- `doc_events` → Supplier → `validate`: si el proveedor tiene grupo y categoría y la categoría no tiene fila para ese grupo, error al guardar el proveedor, no al facturar.

**Arrendamientos.** El modelo 180 pide los datos del inmueble. Doctype propio "Inmueble Arrendado" (módulo ES Retenciones; nombre final `ES Leased Property`) (referencia catastral, dirección, situación), enlazado al arrendador, y custom field en Purchase Invoice obligatorio cuando una línea usa la categoría de arrendamientos. Los arrendadores exonerados de retener (por certificado o por los supuestos del reglamento, como rentas anuales al mismo arrendador de hasta 900 € **[verificar el artículo y los requisitos]**) no llevan categoría. No se automatiza el umbral.

**Clasificación de la fila.** `doc_events` → Purchase Invoice y Payment Entry → `validate`, que se ejecuta después del cálculo nativo: en las filas con `is_tax_withholding_account = 1` pone `tipo_impuesto = Retención IRPF` y la `clave_retencion` derivada de la categoría (spec 03). No se puede hacer en `validate_regional` porque ERPNext lo llama antes de crear la fila.

## 4. Retenciones soportadas (ventas)

ERPNext no lo cubre (§1). Se hace con plantillas de impuestos de venta, sin código en el cálculo:

- Filas de `Sales Taxes and Charges Template` con `tipo_impuesto = Retención IRPF`, `charge_type = On Net Total`, **tipo negativo** (−15 %, −7 %, y los que la compañía necesite) y cuenta 473.
- Combinadas con el IVA: p. ej. "IVA 21 % con retención 15 %".
- Selección automática con Tax Category y Tax Rule (spec 03 §4): categoría "Nacional con retención" en los clientes que retienen. Ajuste en Company con el tipo que se le aplica (15 % o 7 %).
- Líneas que no llevan retención (suplidos): Item Tax Template con tipo 0 para la cuenta 473.
- La factura impresa (spec 05) muestra la retención como línea y el total a pagar.

**[verificar en bench]**: que una fila con tipo negativo cargue la 473 (no un abono negativo), reduzca el total y el pendiente de cobro, se invierta en las rectificativas y no rompa el redondeo.

## 5. Interacción con Verifactu y SII

- **Verifactu**: las retenciones no van en el desglose (`DetalleDesglose`); `CuotaTotal` es solo IVA y RE, e `ImporteTotal` es el total de la factura (spec 06 §6). El adaptador identifica la fila de retención por su clasificación (`tipo_impuesto = Retención IRPF`), no por la cuenta ni por la descripción.
- **SII**: la retención se informa aparte del desglose de IVA (spec 14).

## 6. Datos e informes

**Fuente de datos**

- Practicadas: las filas de `Tax Withholding Entry` de facturas de compra, pagos y asientos, excluyendo los estados Cancelled y Duplicate. Ya guardan tercero, NIF, base, retención, documentos y fechas: no se crea un registro propio.
- Soportadas: el Registro Fiscal IVA (spec 06) con `tipo_impuesto = Retención IRPF` en el libro de expedidas.

**Informes** (Script Reports en el módulo ES Retenciones, con permisos de lectura y `frappe.qb`):

- **Retenciones practicadas**: por periodo, modelo, categoría y perceptor (NIF, nombre, provincia del domicilio), con totales de perceptores, bases y retenciones. Es la vista previa de las casillas de 111 y 115 y de los registros de 190 y 180.
- **Retenciones soportadas**: por periodo y cliente, para el modelo 130 y para cuadrar con los certificados de los clientes.

**Decisión A7, periodo de los modelos.** La obligación de retener nace al pagar (art. 78.1 RIRPF), así que el periodo del 111 y el 115 debería salir de la fecha de pago. Propuesta: el informe permite agrupar por fecha de pago (repartiendo según los pagos asignados a la factura) o por fecha de factura, y la compañía elige con su asesor.

## Criterios de aceptación

1. Compra a un profesional de 1.000 € + IVA 21 % con retención del 15 %: total a pagar 1.060 €; abono de 150 € en 4751; fila de `Tax Withholding Entry` con base 1.000, retención 150 y el NIF del proveedor; fila de impuesto clasificada como Retención IRPF.
2. El mismo proveedor con grupo "Inicio de actividad": 7 %.
3. Factura con una línea de suplido sin `apply_tds`: la base de la retención excluye esa línea.
4. Arrendamiento: 19 %, modelo 115, y la factura no se valida sin inmueble.
5. Cambio de tipo por fecha: una factura anterior y otra posterior al cambio toman cada una su tipo.
6. Rectificativa de compra: la retención se revierte.
7. Anticipo con retención y factura posterior: no hay doble retención.
8. Venta con "IVA 21 % con retención 15 %" sobre 1.000 €: total 1.060 €; cargo de 150 € en 473; pendiente de cobro 1.060 €; la rectificativa lo invierte.
9. Un proveedor con un grupo sin fila en su categoría no se puede guardar.
10. En una compañía no PGC, la app no crea filas de cuenta ni clasifica nada.

## Pendiente de verificar o decidir

- **A7**: periodo de 111 y 115 por fecha de pago o de factura (asesor).
- Claves y subclaves del modelo 190 vigente.
- Requisitos de exoneración en arrendamientos.
- Comportamiento de las filas de tipo negativo en ventas (bench).
- Si conviene exigir `apply_tds` siempre que el proveedor tenga categoría, para evitar facturas de profesionales sin retención por olvido.
