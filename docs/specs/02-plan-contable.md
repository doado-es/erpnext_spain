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

| Subgrupo | Rama | Notas |
|---|---|---|
| 10–13, 19 | Patrimonio neto | 103/104 y 557 son correctoras de PN; siguen en PN. |
| 14–18 | Pasivo | |
| 20–29 | Activo | 28 y 29 son correctoras (saldo acreedor) dentro de Activo. |
| 30–39 | Activo | 39 correctora. |
| 40, 41 | Pasivo | **407** (anticipos a proveedores) va a Activo. 406 a revisar. |
| 43 | Activo (430–436) | **437 y 438** van a Pasivo. |
| 44 | Activo | |
| 46 | Activo (460) | 465, 466 a Pasivo. |
| 47 | Activo (470–474) | 475–479 a Pasivo. |
| 48 | Activo (480) | 485 a Pasivo. |
| 49 | Activo (490–493, correctoras) | 499 a Pasivo. |
| 50–52 | Pasivo | |
| 53–54 | Activo | |
| 55 | Ver nota | Cuentas cuyo lado depende del saldo (550–555, 559): rama nominal Activo, reclasificación por signo en spec 04. 556 Pasivo, 558 Activo. |
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
- **Todas las hojas con `account_number`** del PGC. Los números son únicos por compañía (ERPNext lo valida), así que los nodos de grupo duplicados por la partición (p. ej. "43 Clientes" en Activo y "Anticipos y envases de clientes" en Pasivo) van **sin número**.
- Nivel de las hojas: el más detallado que defina el PGC (3 o 4 dígitos, p. ej. 4300). Las compañías amplían a 8 dígitos si quieren.
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

**Pasos** (en una transacción; `dry_run` devuelve el resumen sin escribir):

1. `unset_existing_data(company)` del importador de planes **[verificado v16]**: vacía las cuentas por defecto de Company y borra las cuentas, cuentas de terceros, cuentas de modos de pago, cuentas de retención y plantillas de impuestos de esa compañía.
2. `create_charts(company, custom_chart=tree)` con el JSON elegido.
3. **Fijar las cuentas por defecto de Company explícitamente** por número de cuenta (§3). **No** usar `set_default_accounts` del importador: toma la primera cuenta `Receivable` que encuentra, que podría ser la 438, y además crea la plantilla de IVA genérica del 21 % **[verificado v16]**.
4. Crear los registros de compañía de la spec 09 §3: plantillas de impuestos, Item Tax Templates, Tax Rules, cuentas de retención y cuentas de los modos de pago. Van después del paso 1, porque `unset_existing_data` borra los de la compañía.
5. `sync_financial_report_templates()` (spec 04).
6. Marcar `pgc_aplicado = 1` y `modelo_plan`.
7. Registrar en el historial de la compañía qué plan y qué versión del JSON se aplicó.

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
| `default_income_account` | 7000 / 7050 | Según actividad; configurable. |
| `default_expense_account` | 6000 / 6290 | Según actividad. |
| `exchange_gain_loss_account` | 668 / 768 | ERPNext usa una sola cuenta para ganancias y pérdidas; decidir cuál y cómo se presenta (la PyG la muestra neta). |
| `unrealized_exchange_gain_loss_account` | ídem | |
| `round_off_account`, `write_off_account` | A decidir | |
| `accumulated_depreciation_account` | 2810 | |
| `depreciation_expense_account` | 6810 | |
| `disposal_account` | 671 / 771 | Una sola cuenta en ERPNext; mismo problema que diferencias de cambio. |
| `capital_work_in_progress_account` | 23x | |
| `asset_received_but_not_billed` | 523 | |
| `default_provisional_account` | 4009 | Servicios recibidos sin factura. |
| `default_deferred_revenue_account` | 4850 | |
| `default_deferred_expense_account` | 4800 | |
| Existencias (`default_inventory_account`, `stock_adjustment_account`, `stock_received_but_not_billed`) | 300 / 610 / 4009 | **Depende de la decisión A3** (inventario permanente o administrativo). |
| Cuenta de cierre del ejercicio (en el Period Closing Voucher) | 1290 | |

`account_type` en el plan: `Receivable` en 430–436 y 4380; `Payable` en 400–405, 410 y 4070; `Tax` en 472, 473, 4751 y 477; `Bank` en 572; `Cash` en 570; `Fixed Asset` en 20–21; `Accumulated Depreciation` en 280–281; `Depreciation` en 680–681; `Capital Work in Progress` en 23; `Stock`, `Stock Adjustment`, `Cost of Goods Sold` y `Stock Received But Not Billed` según A3. El importador de ERPNext considera obligatorios Cost of Goods Sold, Depreciation, Fixed Asset, Payable, Receivable, Stock Adjustment, Bank, Cash y Stock **[verificado v16]**; el plan debe incluirlos aunque no se use el importador.

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
- Decisión A3 (inventario).
- Que `unset_existing_data` no deje referencias en otros doctypes de v16 que enlacen cuentas de la compañía (p. ej. Item Defaults); si las deja, la acción debe limpiarlas o fallar con un mensaje claro.
