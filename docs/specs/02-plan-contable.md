# 02 — Plan contable PGC nativo

Fase 1 · Depende de: 01 · Bloquea: 03, 04, 05, 06

## Objetivo

Dar a las compañías españolas un plan de cuentas con numeración PGC que ERPNext entienda de serie (cada rama con un único `root_type`), y una acción que lo aplique a una compañía sin movimientos.

## Alcance

1. Dos planes en JSON: **PGC Normal** (RD 1514/2007) y **PGC PYMES** (RD 1515/2007).
2. Acción **"Aplicar plan PGC"**.
3. Cuentas por defecto de la compañía.
4. Validación de cuentas nuevas en compañías PGC.
5. Opcional: subcuentas por tercero (decisión abierta A1).

Fuera de alcance: plantillas de impuestos (spec 03), estados financieros (spec 04), migración de compañías con movimientos (decisión D3).

## 1. Diseño del árbol

Cinco raíces nativas. Dentro de cada una, la jerarquía PGC donde el subgrupo es homogéneo; los subgrupos mixtos se parten entre ramas.

```
Activo (Asset)            Pasivo (Liability)        Patrimonio neto (Equity)
Gastos (Expense)          Ingresos (Income)
```

### Reparto por subgrupo — propuesta, **requiere revisión contable**

Criterio (versión 2 de los datos del plan, 30/10/2026): cada cuenta va a la rama del lado en que la presentan los modelos oficiales de balance del PGC y del PGC PYMES, para que los totales del Balance nativo coincidan con los de las plantillas PGC (spec 04). Las correctoras van en la rama de la partida que corrigen.

| Subgrupo | Rama | Notas |
|---|---|---|
| 10–13 | Patrimonio neto | 1030/1040 y 557 son correctoras de PN; siguen en PN. **1034 y 1044** van a Pasivo: los modelos de balance las presentan en "Otras deudas a corto plazo". |
| 19 | Pasivo | Los modelos de balance presentan 190, 192, 194 en "Otras deudas a corto plazo". |
| 14–18 | Pasivo | |
| 20–29 | Activo | 28 y 29 son correctoras (saldo acreedor) dentro de Activo. |
| 30–39 | Activo | 39 correctora. |
| 40, 41 | Pasivo | **407** (anticipos a proveedores) va a Activo. **406** sigue en Pasivo, como correctora de proveedores (así la presenta el modelo de balance). |
| 43 | Activo (430–437) | **437** sigue en Activo, como correctora de clientes (así la presenta el modelo de balance). **438** va a Pasivo. |
| 44 | Activo | |
| 46 | Activo (460) | 465, 466 a Pasivo. |
| 47 | Activo (470–474) | 475–479 a Pasivo. |
| 48 | Activo (480) | 485 a Pasivo. |
| 49 | Activo (490–493, correctoras) | 499 a Pasivo. |
| 50–52 | Pasivo | |
| 53–54 | Activo | |
| 55 | Ver nota | Cuentas cuyo lado depende del saldo (550–554, 5590): rama nominal Activo, reclasificación por signo en spec 04. **555, 556, 5595 y 5598** Pasivo, 557 Patrimonio neto, 558 Activo. |
| 56 | Pasivo (560, 561, 568, 569) | 565, 566, 567 a Activo. |
| 57 | Activo | 572 en descubierto: reclasificación por signo (spec 04). |
| 58 | Activo (580–584) | 585–589 a Pasivo. |
| 59 | Activo (correctoras) | |
| 6 | Gastos | |
| 7 | Ingresos | |
| 8, 9 | Patrimonio neto | El cierre de ERPNext solo traspasa resultados; el traspaso de 8/9 a 13 es un asiento propio (spec 04 §6). |

### Reglas del JSON

- Formato de plan de ERPNext (`name`, `country_code: "es"`, `tree`), el mismo que acepta `create_charts(company, custom_chart=…)` **[verificado v16]**.
- `root_type` solo en las raíces; los hijos lo heredan.
- **Todas las hojas con `account_number`** del PGC. Los números son únicos por compañía (ERPNext lo valida), así que los grupos y subgrupos partidos entre ramas van **sin número**, una copia en cada rama con la rama entre paréntesis en el nombre (ERPNext exige nombres únicos por compañía): p. ej. "Clientes (Activo)" con 430–436 y "Clientes (Pasivo)" con 437–438.
- **Nivel de las hojas: 4 dígitos (decisión del 30/10/2026, opción B).** Cada cuenta de 3 dígitos sin subcuentas en el PGC pasa a grupo y recibe una subcuenta `xxx0` con el mismo nombre, que es donde se contabiliza (570 → 5700, 572 → 5720, 700 → 7000…). Las subcuentas oficiales de 4 y 5 dígitos se mantienen. Las compañías amplían a 8 dígitos si quieren (p. ej. 5721 para un segundo banco).
- **Fuente**: cuadro de cuentas (4ª parte) del texto consolidado del BOE (BOE-A-2007-19884 y BOE-A-2007-19966), extraído con `extract_boe.py` a `source/boe_pgc_*.json` sin tocar el texto. El generador `generate.py` aplica la partición, la opción B, los `account_type` y estas correcciones:
  - Erratas tipográficas del BOE ("deterioroy", "donacionesy", "activosy", "carácterísticas", "alargo", "acorto", "Gastor").
  - PGC PYMES: las cuentas 232, 233, 237 y 239 aparecen en el BOE como "Propiedad industrial" (error presente también en el texto de 2007). Se usan los nombres del PGC Normal, que coinciden con la 5ª parte del PGC PYMES.
  - PGC Normal: el nombre oficial de la 5993 (138 caracteres) no cabe en el nombre del documento Account de ERPNext ("número - nombre - abreviatura", máximo 140); se abrevia. El generador falla si un nombre no cabe con una abreviatura de compañía de hasta 12 caracteres; la acción del §2 rechaza abreviaturas más largas.
  - Los JSON los genera el generador; un test comprueba que los commiteados coinciden con su salida.
- `account_type` según la tabla del §3.
- `account_category` (v16) solo si se necesita para funciones de ERPNext como ratios; los estados PGC no dependen de él (spec 04).
- Opcional en el JSON: `disable_default_financial_report_template: true`. Solo tiene efecto si algún día el plan se contribuye a la carpeta `verified` de ERPNext **[verificado v16]**: `get_chart` solo lee planes de ERPNext, no de apps.
- Ficheros: `erpnext_spain/es_contabilidad/chart_of_accounts/pgc_normal.json` y `pgc_pymes.json`.

## 2. Acción "Aplicar plan PGC"

Endpoint:

```python
@frappe.whitelist(methods=["POST"])
def apply_pgc_chart(company: str, chart_model: str, dry_run: bool = True) -> dict:
    """chart_model: "Normal" | "PYMES". Con dry_run devuelve el resumen sin escribir."""
```

**Permisos**: `write` sobre la Company y rol Accounts Manager o System Manager.

**Precondiciones** (si falla cualquiera, error sin cambios):

- `country == "Spain"`.
- Sin GL Entry de la compañía (mismo criterio que el importador de planes de ERPNext **[verificado v16]**).
- `pgc_aplicado == 0`.
- La compañía no es dependiente de otra con el plan heredado de la matriz (`parent_company` sin `allow_account_creation_against_child_company`), mismo criterio que el importador de ERPNext **[verificado v16]**.
- Abreviatura de la compañía de 12 caracteres como máximo (§1, longitud de los nombres de cuenta).
- Modelo `Normal` o `PYMES`.

Implementado en `es_contabilidad/pgc.py` (`apply_pgc_chart`). La interfaz es el botón "Plan de cuentas → Aplicar plan PGC" de Company (`es_contabilidad/public/js/company.js`).

**Pasos** (en una transacción; `dry_run` devuelve el resumen sin escribir):

1. `clear_company_chart(company)`: borra los Item Tax Template y las Tax Rule de la compañía (que `unset_existing_data` no borra y bloquean el borrado de cuentas, ver pendientes) y llama a `unset_existing_data(company)` del importador de planes **[verificado v16]**, que vacía las cuentas por defecto de Company y borra las cuentas, cuentas de terceros, cuentas de modos de pago, cuentas de retención y plantillas de impuestos de venta y compra.
2. `create_charts(company, custom_chart=tree)` con el JSON elegido.
3. **Desactivar el inventario permanente** (`enable_perpetual_inventory = 0` en Company; decisión A3). En v16 el valor por defecto es 1 **[verificado v16]**. Sin inventario permanente los movimientos de stock no generan asientos: las compras de existencias se contabilizan en la cuenta de gasto del artículo (grupo 60) y la variación se regulariza al cierre (spec 04 §7). **[verificar en bench]** que Purchase Invoice y Delivery Note no exigen cuentas de stock con el inventario permanente desactivado.
4. **Fijar las cuentas por defecto de Company explícitamente** por número de cuenta (§3). **No** usar `set_default_accounts` del importador: toma la primera cuenta `Receivable` que encuentra, que podría ser la 438, y además crea la plantilla de IVA genérica del 21 % **[verificado v16]**.
5. Ejecutar los pasos registrados en `COMPANY_SETUP_STEPS` (`pgc.py`), que crean los registros de compañía de la spec 09 §3: plantillas de impuestos, Item Tax Templates, Tax Rules, cuentas de retención y cuentas de los modos de pago. Van después del paso 1, porque `unset_existing_data` borra los de la compañía.
6. `sync_financial_report_templates()` (spec 04).
7. Marcar `pgc_aplicado = 1` y `modelo_plan` (los pasos 3, 4 y 7 se guardan juntos con `doc.save()` de Company, para que ERPNext valide tipo, rama y moneda de las cuentas por defecto). Al guardar, ERPNext asigna además la 5700 al modo de pago de efectivo (`set_mode_of_payment_account`) **[verificado v16]**.
8. Registrar en el historial de la compañía (comentario) qué plan, qué versión de los datos del plan y qué fecha de actualización del BOE se aplicaron.

Interfaz: botón en Company (solo si se cumplen las precondiciones) con vista previa del `dry_run` y confirmación explícita, porque borra las cuentas existentes de la compañía.

## 3. Cuentas por defecto — propuesta, **requiere revisión contable**

| Campo de Company | Cuenta PGC | Notas |
|---|---|---|
| `default_receivable_account` | 4300 | |
| `default_payable_account` | 4000 | 4100 para acreedores de servicios, por tercero o grupo. |
| `default_advance_received_account` | 4380 | ERPNext exige Pasivo + `Receivable` **[verificado v16]**. |
| `default_advance_paid_account` | 4070 | ERPNext exige Activo + `Payable` **[verificado v16]**. |
| `default_cash_account` | 5700 | |
| `default_bank_account` | 5720 | |
| `default_income_account` | 7000 | 7050 para empresas de servicios; se cambia en Company. |
| `default_expense_account` | 6000 | 6290 para empresas de servicios; se cambia en Company. |
| `exchange_gain_loss_account` | 6680 | ERPNext usa una sola cuenta para ganancias y pérdidas; la PyG la muestra neta. Propuesta: 6680; la reclasificación de un saldo neto acreedor a la 768 se resuelve en las plantillas de estados (spec 04 §3). |
| `unrealized_exchange_gain_loss_account` | 6680 | Ídem. |
| `round_off_account`, `write_off_account` | 6590 | Otras pérdidas en gestión corriente. Propuesta. |
| `accumulated_depreciation_account` | 2819 | La 2810 no existe en el PGC (la 281 se desglosa en 2811–2819). Propuesta: la 2819 (otro inmovilizado material) como genérica en Company; cada Asset Category usa su 281x. **Pendiente de revisión contable.** |
| `depreciation_expense_account` | 6810 | |
| `disposal_account` | 6710 | Una sola cuenta en ERPNext; mismo tratamiento que las diferencias de cambio (771 por reclasificación en los estados). |
| `capital_work_in_progress_account` | Vacía | Solo la usan las Asset Category con inmovilizado en curso activado; cada una fija su 23x. |
| `asset_received_but_not_billed` | 5230 | |
| `default_provisional_account` | 4009 | Servicios recibidos sin factura. |
| `default_deferred_revenue_account` | 4850 | |
| `default_deferred_expense_account` | 4800 | |
| `default_inventory_account` | 3000 | Inventario administrativo (A3): sin inventario permanente ERPNext no lo usa para asentar; se fija por coherencia y para la regularización de cierre (spec 04 §7). |
| `stock_adjustment_account` | 6100 | Ídem; la variación de existencias la contabiliza el asiento de regularización, no ERPNext. |
| `stock_received_but_not_billed` | Vacía | Sin inventario permanente el albarán de compra no genera asiento **[verificar en bench que ningún flujo la exige]**. |
| Cuenta de gasto de los artículos de existencias (Item Defaults / Item Group) | 6000 (mercaderías), 6010 (materias primas), 6020 (otros aprovisionamientos) | Inventario administrativo: la compra va a gasto. |
| Cuenta de cierre del ejercicio (en el Period Closing Voucher) | 1290 | Se elige en cada Period Closing Voucher; no es un campo de Company. |

`account_type` en el plan: `Receivable` en 430–436 y 4380; `Payable` en 400–405, 410 y 4070, salvo las subcuentas de facturas pendientes de recibir o de formalizar (4009, 4039, 4109, 4309, 4339…), que no llevan tipo porque ERPNext exigiría un tercero en cada apunte; `Tax` en 472, 473, 4751 y 477; `Bank` en 572; `Cash` en 570; `Fixed Asset` en 20–21; `Accumulated Depreciation` en 280–281; `Depreciation` en 680–681; `Capital Work in Progress` en 23; Con inventario administrativo (A3): `Stock` en las hojas de 30–36, `Stock Adjustment` en 610–612 y `Cost of Goods Sold` en 600, solo para cumplir la lista de tipos obligatorios del importador; `Stock Received But Not Billed` no se usa. El importador de ERPNext considera obligatorios Cost of Goods Sold, Depreciation, Fixed Asset, Payable, Receivable, Stock Adjustment, Bank, Cash y Stock **[verificado v16]**; el plan debe incluirlos aunque no se use el importador.

## 4. Validación de cuentas en compañías PGC

`doc_events` → Account → `validate` (con salida temprana por `is_pgc_company`):

- Hoja nueva sin `account_number` → error.
- El número debe empezar por el prefijo de algún ancestro numerado.
- El prefijo de 2 o 3 dígitos debe corresponder a la rama (`root_type`) según la tabla del §1. Si no, error con la rama correcta.

No se modifica `root_type` ni se toca la herencia de ERPNext (R2).

## 5. Ficheros del plan como datos versionados

- El JSON lleva un campo propio `version`.
- Si se corrige el plan, la acción no se reaplica a compañías existentes; los cambios para ellas se documentan y, si hace falta, se crean con un patch idempotente que solo añade cuentas.

## 6. Opcional: subcuentas por tercero (decisión A1)

Si se decide incluir:

- Ajustes en Company: activar para clientes y para proveedores, prefijo (4300, 4000, 4100) y longitud (8).
- Al crear Customer/Supplier en una compañía PGC: crear la hoja con el siguiente número libre bajo el grupo del prefijo y asignarla en su tabla *Accounts*.
- Desactivado por defecto. Advertencia en la documentación: cada alta inserta un nodo en el árbol de cuentas (nested set), lo que en altas masivas o concurrentes se nota.
- Alternativa más ligera: campo `codigo_subcuenta` en el tercero, solo para exportar a gestorías.

## Criterios de aceptación

1. Aplicar Normal y PYMES a compañías nuevas sin errores; todas las hojas tienen número; ningún número duplicado.
2. Tras aplicar, el informe Balance Sheet nativo de ERPNext (sin plantilla) funciona y cuadra con un conjunto de asientos de prueba que toca cuentas de todas las ramas, incluidas 407, 438, 475 y 572.
3. Las cuentas por defecto de Company coinciden con la tabla del §3.
4. La acción falla sin cambios si la compañía tiene un GL Entry, si no es de España o si ya tiene el plan aplicado.
5. `dry_run` no escribe nada (test comparando el estado antes y después).
6. Crear una cuenta 4381 bajo Activo da error; bajo la rama de Pasivo correcta, funciona.
7. En una compañía no PGC del mismo sitio, crear cuentas sin número sigue funcionando.

## Pendiente de verificar o decidir

- Revisión contable completa del reparto (§1) y de las cuentas por defecto (§3).
- ~~Decisión A3~~: cerrada, inventario administrativo. Queda verificar en bench el comportamiento de compras y ventas de artículos de stock con `enable_perpetual_inventory = 0`.
- `unset_existing_data` **no borra los Item Tax Template ni las Tax Rule** de la compañía **[verificado v16.51]**: el asistente de configuración crea para España el Item Tax Template "Spain Tax", que bloquea el borrado de la cuenta de IVA. La acción los borra antes (`es_contabilidad/pgc.py`, `clear_company_chart`); se vuelven a crear con los datos iniciales (spec 09 §3). Queda por comprobar si hay otros doctypes que enlacen cuentas de la compañía (p. ej. Item Defaults de artículos ya creados); si los hay, la acción debe limpiarlos o fallar con un mensaje claro.
- 406 (envases y embalajes a devolver a proveedores, saldo deudor): asignada a Activo; revisión contable.
