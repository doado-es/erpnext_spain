# 04 — Estados financieros y libros contables

Fase 2 · Depende de: 01, 02 · Bloquea: —

## Objetivo

Balance y Pérdidas y Ganancias en los modelos oficiales (Normal, Abreviado y PYMES) usando el motor de plantillas nativo de ERPNext v16, más los informes que el motor no cubre: sumas y saldos por niveles de dígitos y libro diario numerado. Sin informes de escritorio modificados (R1, R2).

## Alcance

1. Fuente única del mapeo de cuentas a epígrafes.
2. Seis `Financial Report Template`: Balance y PyG × Normal, Abreviado, PYMES.
3. Reclasificación de cuentas según el signo de su saldo.
4. Informe de sumas y saldos por niveles.
5. Libro diario con numeración por ejercicio.
6. Asiento de traspaso de los grupos 8 y 9.
7. Asiento de regularización de existencias (inventario administrativo, decisión A3).

Fuera de alcance por ahora: Estado de cambios en el patrimonio neto, Estado de flujos de efectivo, memoria y depósito en el Registro Mercantil.

## 1. Lo que da ERPNext v16 [verificado v16]

- Doctypes `Financial Report Template` (con `report_type`, `module`, `rows`) y `Financial Report Row`.
- Fuentes de fila: `Account Data`, `Calculated Amount`, `Custom API`, `Blank Line`, `Column Break`, `Section Break`.
- `balance_type`: Opening Balance, Closing Balance, Period Movement (Debits - Credits). Casilla `reverse_sign` por fila.
- Las filas `Account Data` filtran cuentas hoja activas de la compañía con una fórmula sobre campos de Account: `["campo", "operador", "valor"]` o combinaciones `{"and": [...]}` / `{"or": [...]}`.
- **Si un `like` no lleva `%`, el motor lo convierte en `%valor%`**. Hay que escribir siempre el prefijo con `%` explícito: `["account_number", "like", "430%"]`. Sin él, "430" casaría también con 4430.
- Las filas `Custom API` llaman a `frappe.call(método, filters=…, periods=…, row=…)` y esperan una lista de valores por periodo. El método debe ser whitelisted y **permitir GET**.
- Los informes nativos Balance Sheet y Profit and Loss Statement aceptan el filtro `report_template` y, si se indica, usan el motor de plantillas.
- Las plantillas de una app se guardan en `<módulo>/financial_report_template/<scrub(nombre)>/<scrub(nombre)>.json`, con un `account_categories.json` opcional en la carpeta `financial_report_template`. `sync_financial_report_templates()` las inserta para todas las apps instaladas (solo las que no existen); ERPNext la llama al crear las cuentas de una compañía.

## 2. Fuente única del mapeo

Fichero versionado `es_contabilidad/statements/epigrafe_mapping.csv`, revisado por un contable, del que se **generan** las plantillas. Nadie edita los JSON a mano.

| Columna | Contenido |
|---|---|
| `modelo` | Normal / Abreviado / PYMES |
| `estado` | Balance / PyG |
| `codigo` | Código estable de la fila (p. ej. `A.II.2`), que es el `reference_code` |
| `epigrafe` | Texto oficial |
| `nivel` | Sangría |
| `tipo` | `cuentas` · `signo` · `formula` · `titulo` |
| `incluir` | Prefijos de cuenta separados por espacios (`430 431 432`) |
| `excluir` | Prefijos a excluir |
| `lado` | Solo en `tipo = signo`: `deudor` / `acreedor` |
| `invertir_signo` | 0/1 |
| `formula` | Solo en `tipo = formula`: combinación de códigos |

Fuente del texto y la estructura: modelos de la 3ª parte del PGC (RD 1514/2007) y del PGC PYMES (RD 1515/2007). **La relación cuenta → epígrafe la elabora y firma un contable**; es el entregable de mayor riesgo de esta spec.

Generador `es_contabilidad/statements/generate_templates.py` (se ejecuta en desarrollo y su salida se commitea):

- `cuentas` → fila `Account Data` con `{"or": [["account_number","like","430%"], …]}` y, si hay exclusiones, `{"and": [<inclusión>, ["account_number","not like","4309%"], …]}`.
- `signo` → fila `Custom API` (§3).
- `formula` → fila `Calculated Amount` **[verificar la sintaxis de fórmula del motor]**.
- `titulo` → `Section Break` o `Blank Line` con texto.
- Balance con `Closing Balance`; PyG con `Period Movement`. `reverse_sign` en las filas de PN, pasivo e ingresos, según la convención de signo del motor **[verificar en bench]**.

Nombres de plantilla: "PGC Normal — Balance", "PGC Normal — Pérdidas y ganancias", y equivalentes para Abreviado y PYMES.

## 3. Reclasificación por signo

Casos: cuentas de clientes y proveedores con saldo contrario, 572 en descubierto, cuentas corrientes con socios (551–555), HP deudora/acreedora cuando se usan subcuentas mixtas.

- Endpoint único `erpnext_spain.es_contabilidad.statements.api.balance_by_sign`, `@frappe.whitelist(methods=["GET"])`, con type hints y comprobación de permiso de lectura sobre GL Entry (R6).
- Recibe `filters`, `periods`, `row`. Busca la configuración de la fila por `row.reference_code` en el mapeo (prefijos y lado) y devuelve, por periodo, la suma de los saldos de las cuentas cuyo saldo es del lado pedido.
- **Los saldos deben calcularse igual que el motor** (saldo inicial, asientos de cierre, libro de finanzas, dimensiones). Preferencia: reutilizar la clase de consulta del motor (`FinancialQueryBuilder.fetch_account_balances`) llamándola, no parcheándola. Es API interna de ERPNext: se cubre con un test que compare resultados (criterio 3) para detectar cambios.
- Cada cuenta aparece una sola vez en el estado: las filas `cuentas` excluyen los prefijos que tengan fila `signo`, y las dos filas `signo` (deudor/acreedor) del mismo prefijo suman el total de la cuenta.

## 4. Sumas y saldos por niveles

Script Report `ES Trial Balance by Level` (título traducido: "Sumas y saldos PGC") en el módulo ES Contabilidad:

- Filtros: compañía, desde, hasta, nivel (1, 2, 3, 4, cuenta), incluir asiento de cierre, libro de finanzas.
- Columnas: cuenta (prefijo o número), nombre, saldo inicial, debe, haber, saldo final.
- Agrupación por prefijo del `account_number`, **independiente del árbol de ERPNext**: así se ve la estructura de grupos 1–9 aunque el árbol esté partido por `root_type`.
- Consultas con `frappe.qb` sobre GL Entry (R5); permiso de lectura sobre GL Entry.
- Totales debe = haber.

## 5. Libro diario

Script Report `ES Journal Book` (título traducido: "Libro diario PGC"):

- Número de asiento correlativo por ejercicio y compañía, asignado por orden de fecha y comprobante, estable entre ejecuciones.
- Clases: apertura, ordinario, regularización (Period Closing Voucher), cierre.
- Columnas: número de asiento, fecha, cuenta, concepto, debe, haber, documento origen.
- Exportable para legalización **[formato de legalización: verificar]**.

## 6. Traspaso de los grupos 8 y 9

El Period Closing Voucher de ERPNext solo lleva las cuentas de resultados a la cuenta de cierre. Las cuentas de los grupos 8 y 9 (gastos e ingresos imputados al patrimonio neto) se traspasan a sus cuentas del subgrupo 13 con un **Journal Entry nativo** generado por una acción de cierre de la app (con dimensiones, R9). Tabla de correspondencias 8x/9x → 13x en el mapeo, revisada por el contable.

## 7. Regularización de existencias (inventario administrativo)

Con la decisión A3 las compañías PGC no usan el inventario permanente: las compras se contabilizan en el grupo 60 y las cuentas 30–36 conservan el saldo del cierre anterior hasta que se regularizan.

- Acción de cierre de la app, por compañía y fecha de cierre, que genera un **Journal Entry nativo** (con dimensiones, R9): se da de baja la existencia inicial (61x/71x a 30x) y se da de alta la final (30x a 61x/71x). Equivale a asentar solo la diferencia en 61x/71x; se registran las dos partidas por claridad en el libro diario.
- **Valor de la existencia final**: la valoración del Stock Ledger a la fecha de cierre (informe Stock Balance), que ERPNext calcula aunque el inventario permanente esté desactivado **[verificar en bench]**. El usuario puede revisar y corregir el importe antes de validar (p. ej. por deterioro o recuento físico).
- **Correspondencia grupo de artículos → cuenta**: mercaderías 300/610, materias primas 310/611, otros aprovisionamientos 320/612, productos en curso 330/710, semiterminados 340/711, terminados 350/712, subproductos y residuos 360/713. Se configura por Item Group; **revisión contable**.
- Va antes del Period Closing Voucher, para que la variación entre en el resultado del ejercicio.
- Los deterioros de existencias (39x/69x/79x) quedan fuera de esta acción; se asientan a mano.

## Criterios de aceptación

Con una compañía PYMES de prueba y asientos que tocan todas las ramas, incluidas cuentas con saldo contrario a su naturaleza:

1. En la plantilla de Balance: total activo = total PN + pasivo, y ambos coinciden con el Balance Sheet nativo sin plantilla.
2. En la plantilla de PyG: el resultado coincide con el Profit and Loss nativo.
3. Si todas las cuentas de un prefijo tienen el mismo signo, la fila `signo` coincide con lo que daría una fila `cuentas` del mismo prefijo.
4. Un cliente con saldo acreedor aparece en el pasivo y no en el activo; la 572 en descubierto, en deudas a corto plazo.
5. Abreviado y PYMES dan los mismos totales que Normal.
6. El generador produce los mismos JSON si se ejecuta dos veces (determinista); el CI falla si los JSON commiteados no coinciden con la salida del generador.
7. Sumas y saldos: debe = haber en todos los niveles; los saldos del nivel 3 suman el nivel 1.
8. Tras `bench migrate` en un sitio con la app, las seis plantillas existen.
9. Regularización de existencias: con existencia inicial 1.000 € en 300 y valoración final de 1.500 €, el asiento deja 1.500 € en 300 y un saldo acreedor de 500 € en 610; ejecutarla dos veces para la misma fecha da error.

## Pendiente de verificar o decidir

- Sintaxis de las fórmulas y convención de signo del motor de v16 (en bench).
- Estabilidad de `FinancialQueryBuilder` como API interna; plan B: consulta propia que replique la lógica, con el criterio 3 como red de seguridad.
- Mapeo cuenta → epígrafe (contable).
