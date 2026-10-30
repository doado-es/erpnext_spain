# 11. Facturación "Masiva" de Delivery Notes

[← Volver al índice](00-maestro.md)

## Objetivo

Permitir generar facturas de venta de forma masiva/agrupada a partir de múltiples Delivery Notes pendientes de facturar, con las reglas de agrupación habituales en la operativa española (agrupar por cliente, por periodo, consolidando varias entregas en una sola factura mensual, etc.).

## Contexto

- Es común en el tejido empresarial español (especialmente distribución/mayoristas) facturar de forma consolidada — por ejemplo, una única factura mensual que recoge todos los albaranes (delivery notes) del periodo para un mismo cliente.
- ERPNext permite facturar Delivery Notes individualmente o seleccionar varios manualmente, pero no hay un flujo "masivo" con reglas de agrupación configurables out of the box.

## Alcance

- Herramienta/flujo para seleccionar un conjunto amplio de Delivery Notes (por rango de fechas, cliente, compañía) y generar las Sales Invoice resultantes en bloque.
- Reglas de agrupación configurables: una factura por cliente y periodo, o respetando otros criterios (ej. por dirección de envío, por proyecto).
- Manejo de errores en el proceso masivo (algunos delivery notes fallan la facturación, el resto continúa) con reporte claro de qué se facturó y qué no.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en facturación masiva; hay antecedente de trabajo de facturación masiva de Purchase Invoice vía MCP para KUBIC ELECTRICAL S.L. que puede servir de referencia de patrón, aunque sea el lado de compras)*

## Diseño técnico propuesto

*(Por completar — evaluar si se construye como Server Script/background job sobre la función nativa `make_sales_invoice` de Delivery Note, o como DocType propio tipo "Proceso de Facturación Masiva" con su propio log de ejecución)*

## Dudas abiertas

- ¿Reglas de agrupación fijas (por cliente+periodo) o configurables por el usuario en cada ejecución?
- ¿Ejecución síncrona (para volúmenes pequeños) o como background job con notificación al terminar (para volúmenes grandes)?
- ¿Qué pasa con los Delivery Notes parcialmente facturados o con condiciones especiales de precio que varían entre albaranes del mismo cliente?

## Tareas para agentes

- [ ] Revisar `make_sales_invoice` nativo de Delivery Note y sus limitaciones para consolidar varios en una sola factura.
- [ ] Diseñar DocType de "proceso de facturación masiva" con selección de criterios y log de resultado.
- [ ] Implementar como background job para volúmenes grandes.
- [ ] Definir comportamiento ante errores parciales (qué se factura, qué queda pendiente, cómo se reintenta).
