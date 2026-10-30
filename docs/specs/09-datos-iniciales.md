# 09 — Datos iniciales (registros de arranque)

Fase 1 · Depende de: 01, 02 · Lo usan: 03, 05, 08, 10, 11, 12, 13, 14

## Objetivo

Que un sitio con la app y una compañía con el plan PGC aplicado tengan, sin configuración manual, los registros españoles de partida: tipos de IVA y recargo, plantillas, categorías y reglas de impuestos, retenciones, modos de pago, condiciones de pago y formato de dirección. Y que se puedan **actualizar cuando cambie la normativa** sin pisar lo que haya tocado el usuario.

Hasta ahora estos registros estaban repartidos entre las specs 03 y 08. Esta spec es el inventario único y fija las reglas comunes; las specs de cada funcionalidad definen el contenido fiscal de cada registro.

## 1. Reglas

| Id | Regla |
|---|---|
| S1 | **Datos versionados en la app**, no fixtures. Ficheros en `setup/data/` de cada módulo (p. ej. `es_impuestos/setup/data/`) (JSON o Python). Los fixtures se reimportan en cada `migrate` y pisan los cambios del usuario; para custom fields están prohibidos (R3). |
| S2 | **Funciones `ensure_*` idempotentes**: crean lo que falta, identificándolo por un nombre estable, y no modifican ni borran lo que existe. Ejecutarlas dos veces no cambia nada. |
| S3 | **Dos niveles.** Los registros globales del sitio se crean en `after_install` y `after_migrate`. Los registros de compañía se crean en la acción "Aplicar plan PGC" (spec 02), **después** de `unset_existing_data`, que borra las plantillas de impuestos de venta y compra, las cuentas de los modos de pago y las cuentas de retención de la compañía **[verificado v16]**; los Item Tax Template y las Tax Rule los borra antes la propia acción (spec 02, pendientes). |
| S4 | **Los cambios normativos no editan registros existentes**: añaden registros o filas con fecha, mediante un patch idempotente. Se usan las fechas que ya trae ERPNext: `from_date`/`to_date` en Tax Withholding Rate y en Tax Rule, y `valid_from` en los impuestos del artículo **[verificado v16]**. |
| S5 | **Versión de los datos por compañía**: custom field `version_datos_iniciales` en Company. Cada patch que añade datos de compañía la sube; así se sabe qué compañías están al día. |
| S6 | **Desinstalar no borra estos registros**: son datos del usuario y pueden tener transacciones. Solo se eliminan custom fields y property setters (R3). |
| S7 | **Reutilizar lo que crea ERPNext** cuando ya existe (p. ej. modos de pago), en lugar de duplicarlo. |

## 2. Inventario: registros globales del sitio

| Registro | Contenido | Spec |
|---|---|---|
| Tax Category | Nacional · Nacional con recargo de equivalencia · Nacional con retención · Intracomunitario · Extracomunitario · Canarias, Ceuta y Melilla | 03 §4 |
| Tax Withholding Group | Inicio de actividad · Reducción art. 68.4 LIRPF · Entidad con cifra de negocios < 100.000 € | 08 §3 |
| Tax Withholding Category | Las siete categorías con sus filas de tipo por grupo y fecha, base neta y umbrales desactivados. Sin filas de cuenta (son por compañía). | 08 §3 |
| Mode of Payment | Reutilizar los que crea ERPNext (efectivo, tarjeta, transferencia, giro **[verificado v16]**) y añadir los que falten: Domiciliación bancaria (SEPA), Confirming y Bizum. | 11, 12 |
| Holiday List "Festivos nacionales España" | Festivos nacionales por año, para calcular los plazos en días hábiles del SII y de los estados de la factura electrónica. Se añade cada año por patch. | 10, 14 |
| Payment Terms Template | Contado · 30 días · 60 días · 30-60 días · 30-60-90 días. Plazos sujetos a los máximos de la Ley 3/2004 de morosidad **[verificar límites vigentes]**. | — |
| Address Template | Formato español (dirección, código postal, municipio, provincia) para el país Spain. ERPNext no trae plantilla de dirección para España **[verificado v16]**. | — |
| ES Invoice Type | Tipos de factura F1, F2, F3 y R1–R5. **Ya los siembra el código base** (`seed_invoice_types`, hoy como `SC Verifactu Invoice Type`). | 05 |
| Property Setters | Formato de impresión predeterminado de Sales Invoice (spec 05 §5). | 05 |

La provincia que piden los modelos 190 y 180 se deriva de los dos primeros dígitos del código postal; no hace falta cargar una tabla de provincias como territorios.

## 3. Inventario: registros de compañía ("Aplicar plan PGC")

Orden dentro de la acción, después de crear el plan y fijar las cuentas por defecto (spec 02 §2):

| Paso | Registro | Contenido | Spec |
|---|---|---|---|
| a | Sales Taxes and Charges Template | IVA 21/10/4 %, combinaciones con RE, exenta, entrega intracomunitaria, exportación, ISP, no sujeta, IVA con retención 15 % y 7 %. Con clasificación fiscal y Tax Category. "IVA 21 %" como predeterminada (`is_default`). | 03 §3, 08 §4 |
| b | Purchase Taxes and Charges Template | IVA deducible corriente, bien de inversión y no deducible; intracomunitarias; ISP; importación. | 03 §3 |
| c | Item Tax Template | IVA 10 %, IVA 4 %, IVA 0 %, exento, y "Sin retención" (tipo 0 para la 473, para suplidos en ventas). Son por compañía **[verificado v16]**. | 03 §3, 08 §4 |
| d | Tax Rule | Una por Tax Category y tipo (venta/compra), con `from_date` y prioridad, apuntando a las plantillas de a y b. Son por compañía **[verificado v16]**. | 03 §4 |
| e | Tax Withholding Account | Fila de la compañía con la cuenta 4751 en cada Tax Withholding Category. | 08 §3 |
| f | Mode of Payment Account | Cuenta por defecto de la compañía en cada modo de pago: efectivo → 5700; transferencia, domiciliación, tarjeta y Bizum → 5720. | — |
| g | Bank Transaction Rule | Reglas de partida, desactivables: comisiones e intereses (concepto común 17 de Norma 43) a sus cuentas. Son por compañía **[verificado v16]**. | 13 |
| h | Company | `version_datos_iniciales` y los valores por defecto de la sección España (spec 01 §5). | 01 |

La plantilla genérica "Spain Tax" (IVA 21 %) que crea el asistente de configuración de ERPNext a partir de `country_wise_tax.json` **[verificado v16]** desaparece en el paso de `unset_existing_data`; no hay que borrarla aparte.

## 4. Valores fiscales de partida — **verificar contra la normativa vigente al implementar**

| Concepto | Valores |
|---|---|
| IVA | 21 % general, 10 % reducido, 4 % superreducido, 0 % y exenciones por artículo |
| Recargo de equivalencia | 5,2 % (con 21 %), 1,4 % (con 10 %), 0,5 % (con 4 %); 1,75 % tabaco |
| Retenciones IRPF | Cuadro AEAT 2026 recogido en la spec 08 §2 |

Si la normativa introduce un tipo temporal (como las rebajas de IVA en alimentos de años anteriores), se modela con plantillas nuevas y `valid_from` en los impuestos del artículo, o con Tax Rule fechadas, no editando las plantillas existentes (S4).

## 5. Actualizaciones posteriores

- Un patch por cambio normativo en `patches/`, idempotente:
  - globales: añade filas de tipo con fecha o registros nuevos;
  - de compañía: recorre las compañías con `pgc_aplicado`, añade lo que falte y sube `version_datos_iniciales`.
- El patch nunca modifica un registro que el usuario haya cambiado. Si el cambio legal exige tocar uno existente (p. ej. cerrar la fila vigente de un tipo de retención con `to_date`), se hace solo si el registro conserva los valores originales; si no, se deja y se avisa en el Error Log y en las notas de la versión.
- Las notas de versión de la app listan los cambios de datos y si requieren acción del usuario.

## Criterios de aceptación

> **Estado (30/10/2026)**: implementados los registros de impuestos: Tax Category (global), plantillas de venta y compra, Item Tax Template, Tax Rule y cuentas de los modos de pago (§3 a, b, c, d, f y h) en `es_impuestos/initial_data.py`, conectados a "Aplicar plan PGC" (`COMPANY_SETUP_STEPS`). Para compañías con el plan ya aplicado, botón "Plan de cuentas → Crear impuestos que faltan" en Company (`create_missing_company_records`). Pendientes: Tax Withholding Group y Category (spec 08), Holiday List, Payment Terms, Address Template, cuentas de retención (§3 e) y reglas bancarias (§3 g).

1. Sitio nuevo con la app: existen todos los registros globales del §2. Un segundo `migrate` no crea ni cambia nada.
2. Compañía nueva + "Aplicar plan PGC": existen todos los registros del §3, enlazados a cuentas del plan, y no queda la plantilla "Spain Tax".
3. Segunda compañía en el mismo sitio: recibe sus registros de compañía sin duplicar los globales.
4. Si el usuario renombra una Tax Category o cambia el tipo de una plantilla, el siguiente `migrate` no lo revierte.
5. Patch de prueba que cambia un tipo de retención con fecha: las facturas anteriores a la fecha siguen con el tipo antiguo y las posteriores toman el nuevo; `version_datos_iniciales` sube en las compañías PGC.
6. Desinstalar la app deja los registros y quita los custom fields.
7. Una compañía no PGC del mismo sitio no recibe ningún registro de compañía.

## Pendiente de verificar o decidir

- Límites vigentes de plazos de pago (Ley 3/2004).
- Si se incluyen más modos de pago (pagaré) o condiciones con días fijos de pago.
- Valores fiscales vigentes (§4).
