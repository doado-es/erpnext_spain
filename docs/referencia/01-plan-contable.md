# 1. Adaptación del Plan Contable (PGC)

[← Volver al índice](00-maestro.md)

## Objetivo

Adaptar el Chart of Accounts de ERPNext al Plan General Contable español (PGC 2007 y sus adaptaciones sectoriales), resolviendo el problema de que en ERPNext cada cuenta tiene un único `root_type` fijo (Asset, Liability, Equity, Income, Expense), mientras que en el PGC una misma cuenta puede comportarse de forma distinta según el contexto (ej. cuentas de regularización, cuentas de grupos 8/9 de gastos e ingresos imputados al patrimonio neto, cuentas puente).

## Contexto normativo

- Estructura del PGC por grupos (1-9): Financiación básica, Inmovilizado, Existencias, Acreedores/deudores, Cuentas financieras, Compras/gastos, Ventas/ingresos, Gastos imputados al patrimonio neto, Ingresos imputados al patrimonio neto.
- Los grupos 8 y 9 son el caso conflictivo: son cuentas de gasto/ingreso que en determinados movimientos no van a la cuenta de pérdidas y ganancias sino directamente a patrimonio neto (ej. ajustes por valoración, subvenciones).

## Alcance

- Plantilla de Chart of Accounts en formato Frappe (JSON) equivalente al PGC 2007 y PGC PYMES.
- Resolución del problema de `root_type` variable según el caso.
- Mapeo de balance de situación y cuenta de pérdidas y ganancias con el formato legal español (para los informes, no solo para el libro mayor).

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios y el árbol de cuentas de OCA/l10n-spain como referencia de estructura)*

## Diseño técnico propuesto

*(Por completar tras revisar el comportamiento real de `root_type` en el código de ERPNext — candidatos: Custom Field para "root_type efectivo por asiento", lógica en `on_submit` de Journal Entry para reclasificar, o reporting paralelo que no dependa de `root_type` para las cuentas conflictivas)*

## Dudas abiertas

- ¿Cuántas cuentas reales del PGC caen en el caso conflictivo de root_type variable? (dimensionar el problema antes de diseñar la solución)
- ¿Se resuelve a nivel de cuenta (Account) o a nivel de asiento (GL Entry)?
- ¿Impacto en los reports estándar de ERPNext (Balance Sheet, P&L) si se toca `root_type`?

## Tareas para agentes

- [ ] Auditar en el código de ERPNext dónde se usa `root_type` (reports, validaciones, balance sheet) para medir el impacto de cualquier cambio.
- [ ] Modelar el árbol de cuentas PGC 2007 completo en JSON de Chart of Accounts.
- [ ] Prototipar la solución al problema de root_type variable sobre un bench de pruebas.
