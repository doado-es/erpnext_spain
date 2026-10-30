# 03 — Impuestos: clasificación y plantillas

Fase 1 · Depende de: 01, 02 · Bloquea: 05, 06

## Objetivo

Que cada línea de impuesto de una factura lleve una clasificación fiscal estable (de la que salen el registro de IVA, los modelos, el SII y Verifactu), y que una compañía PGC arranque con las plantillas de impuestos españolas ya creadas.

## Alcance

1. Campos de clasificación fiscal.
2. Cuentas de impuestos del plan.
3. Plantillas de impuestos de venta, compra y de artículo.
4. Categorías y reglas de impuestos para la selección automática.
5. Validación de la clasificación.

Fuera de alcance: IGIC e IPSI (decisión A5), modelos (spec 07), registro fiscal (spec 06).

## 1. Clasificación fiscal

Custom fields en **Sales Taxes and Charges** y **Purchase Taxes and Charges** (filas de factura y de plantilla, que comparten doctype hijo), y en **Item Tax Template**:

| Campo | Valores | Uso |
|---|---|---|
| `tipo_impuesto` | IVA · Recargo de equivalencia · Retención IRPF · Otro | Qué es la línea. |
| `calificacion_iva` | S1 sujeta no exenta · S2 sujeta con inversión del sujeto pasivo · N1 no sujeta (arts. 7, 14 y otros) · N2 no sujeta por localización · E1–E6 exenta por artículo | Códigos alineados con Verifactu y SII **[verificar contra el diseño de registro vigente de la AEAT]**. |
| `tipo_operacion` | Interior · Entrega intracomunitaria · Adquisición intracomunitaria de bienes · Adquisición intracomunitaria de servicios · Importación · Exportación · Servicios a/desde fuera de la UE | Lo que necesitan 303, 349 y 390 y no cubre la calificación. |
| `deducibilidad` | Corriente · Bien de inversión · No deducible | Solo compras de IVA y RE. |
| `clave_regimen` | Clave de régimen especial o trascendencia (01 general, 02 exportación, …) **[verificar lista vigente]** | La exigen el SII (spec 14) y Verifactu (spec 07). Valor por defecto por plantilla. |
| `clave_retencion` | Trabajo · Actividades profesionales · Arrendamiento de inmuebles · Capital mobiliario · Otras | Solo retenciones. En compras se rellena sola desde la Tax Withholding Category (spec 08); en ventas viene de la plantilla. |

En Item Tax Template, `calificacion_iva` y `tipo_operacion` sustituyen a las de la fila cuando la factura mezcla operaciones (p. ej. sujeta y exenta).

Los valores se guardan con su código estable; la etiqueta legible es solo de interfaz. Los códigos viven en un único módulo Python (`es_impuestos/codes.py`) que usan todas las specs.

**Relación con el código base.** Verifactu ya tiene catálogos de claves de régimen y causas de exención (pendientes de completar según su TODO: listas L8A y L10) y dos campos a nivel de factura, `es_verifactu_regime_key` y `es_verifactu_exempt_cause`, que su adaptador usa como valor por defecto de toda la factura. Con esta spec:

- Los catálogos pasan a `es_impuestos/codes.py` y los usan Verifactu, SII y los modelos.
- La clasificación vive en la fila de impuesto (y en el Item Tax Template). Los dos campos de factura se conservan como valor por defecto cuando la fila no lo informa.

## 2. Cuentas de impuestos — propuesta

| Concepto | Cuenta |
|---|---|
| IVA soportado | 4720 (subcuentas por tipo opcionales) |
| IVA repercutido | 4770 |
| Recargo de equivalencia repercutido | 4771 (separada, el 303 la pide aparte) |
| Retenciones practicadas (IRPF que retiene la empresa) | 4751 |
| Retenciones soportadas (IRPF que le retienen a la empresa) | 473 |
| Autorrepercusión ISP e intracomunitarias | 4720 / 4770, diferenciadas por clasificación, no por cuenta |

El registro fiscal (spec 06) se basa en la clasificación, no en la cuenta, así que el número de subcuentas es decisión contable, no técnica.

## 3. Plantillas

Se crean por código en "Aplicar plan PGC" (spec 02), idempotentes, siguiendo las reglas de creación y actualización de la spec 09. **Los tipos se verifican contra la normativa vigente al implementar.**

**Venta** (Sales Taxes and Charges Template):

- IVA 21 %, 10 %, 4 % (S1, Interior).
- IVA 21 % + RE 5,2 %; IVA 10 % + RE 1,4 %; IVA 4 % + RE 0,5 %.
- Exenta (E1 por defecto; el usuario cambia el artículo).
- Entrega intracomunitaria (E5, sin cuota).
- Exportación (E2, sin cuota).
- Inversión del sujeto pasivo (S2, sin cuota; la factura debe llevar la mención, spec 05).
- No sujeta por localización (N2).
- IVA 21 % con retención IRPF 15 % y con 7 % (profesionales): fila de retención con **tipo negativo** `On Net Total` y cuenta 473. `Sales Taxes and Charges` no tiene `add_deduct_tax` **[verificado v16]**. Diseño completo en la spec 08.

**Compra** (Purchase Taxes and Charges Template):

- IVA 21 %, 10 %, 4 % deducible corriente; ídem bien de inversión; ídem no deducible.
- Adquisición intracomunitaria de bienes / de servicios (sin cuota en la factura; la autorrepercusión la genera la spec 06).
- Inversión del sujeto pasivo recibida (S2; ídem).
- Importación con DUA (la cuota viene del DUA, no del proveedor; diseño en spec 06).
- Las retenciones de compras **no van en plantillas**: usan el mecanismo nativo de ERPNext (Tax Withholding Category en el proveedor y en la línea), que crea la fila `Deduct` a 4751. Diseño en la spec 08.

**Item Tax Template**: IVA 10 %, IVA 4 %, IVA 0 % / exento, para asignar en artículos y grupos de artículos.

## 4. Selección automática

Usar lo nativo de ERPNext:

- **Tax Category**: las de la spec 09 §2, que es el inventario único: Nacional · Nacional con recargo de equivalencia · Nacional con retención (spec 08 §4) · Intracomunitario · Extracomunitario · Canarias, Ceuta y Melilla.
- **Tax Rule** por categoría del tercero y país de facturación, apuntando a las plantillas del §3.
- Campo en Customer: régimen del cliente (General / Recargo de equivalencia) que asigna la Tax Category.

## 5. Validación de la clasificación

- Al guardar una factura: si la fila está vacía y hay plantilla, se copia la clasificación de la fila equivalente de la plantilla (misma cuenta y tipo). Nunca se pisa lo ya informado.
- Si `exigir_clasificacion_fiscal` está activo en la compañía, la validación de la factura falla cuando una fila de IVA o RE no tiene `calificacion_iva`, `tipo_operacion` y, en compras, `deducibilidad`; o una retención no tiene `clave_retencion`.
- Punto de extensión: regional override de **`validate_regional`** de `accounts_controller` **[verificado v16]**. ERPNext lo llama en la validación de facturas con la compañía fijada en `frappe.flags.company`, por lo que la región se resuelve por el país de la compañía. Aun así, la función empieza por `is_pgc_company(doc.company)`.
- Rendimiento (R4): las plantillas se leen con `frappe.get_cached_doc`; nada de consultas por línea de artículo.

## Criterios de aceptación

> **Estado (30/10/2026): implementados §1, §3 y §4** (`es_impuestos/codes.py`, `setup.py`, `initial_data.py`). Decisiones tomadas al implementar:
> - Códigos verificados contra el esquema de VeriFactu de la AEAT (`SuministroInformacion.xsd`, versionado en el repo): calificación S1, S2, N1, N2 y exención E1–E6 en un solo campo `es_vat_classification` (en el esquema son elementos excluyentes `CalificacionOperacion` y `OperacionExenta`). El esquema admite también E7, E8 y la clave de régimen 21, sin descripción en el XSD: no se ofrecen hasta verificarlos.
> - ERPNext admite **una sola plantilla por categoría fiscal y compañía** **[verificado v16]**: solo llevan categoría las plantillas a las que apuntan las reglas.
> - El recargo de equivalencia repercutido va a la **4771**, que la app añade bajo la 477 al crear los datos iniciales.
> - Item Tax Template con las cuentas de venta y de compra (4770, 4771, 4720): ERPNext solo añade filas desde la plantilla de artículo cuando la factura no tiene impuestos **[verificado v16]**; con la plantilla de la factura aplicada, el tipo del artículo sustituye al de las filas existentes.
> - IVA no deducible a la 6310 (mayor gasto) **[revisión contable]**.
> - Pendiente: §5 (copia y exigencia de la clasificación al validar la factura). Al elegir la plantilla en el formulario, ERPNext ya copia los campos de clasificación a las filas de la factura **[verificado v16]**.

1. Tras "Aplicar plan PGC", existen todas las plantillas del §3 con la clasificación rellena y apuntando a las cuentas del §2.
2. Una factura de venta a un cliente de otro país de la UE con Tax Category Intracomunitario recibe la plantilla de entrega intracomunitaria sin intervención.
3. Una factura de venta con la plantilla "IVA 21 % con retención 15 %" calcula base, IVA y retención correctamente y la retención carga la 473 (las retenciones de compras se prueban en la spec 08).
4. Con `exigir_clasificacion_fiscal`, una factura con una fila de IVA sin clasificar no se puede validar (el borrador sí se guarda).
5. Una factura con artículos al 21 % y al 10 % (Item Tax Template) clasifica cada parte con su tipo.
6. En una compañía no PGC, la validación no exige nada.

## Pendiente de verificar o decidir

- Tipos impositivos y de retención vigentes al implementar.
- Códigos exactos de calificación y exención en el diseño de registro de Verifactu/SII.
- Subcuentas de IVA por tipo: decisión contable.
