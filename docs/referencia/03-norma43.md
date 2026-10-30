# 3. Captura Norma 43 (Conciliación Bancaria)

[← Volver al índice](00-maestro.md)

## Objetivo

Parsear ficheros de extractos bancarios en formato Norma 43 (Cuaderno 43 del Consejo Superior Bancario, aún vigente para extractos aunque los pagos usen SEPA) e importarlos como movimientos para conciliación bancaria en ERPNext.

## Contexto normativo / técnico

- Formato de ancho fijo por registros (tipo 11 cabecera de cuenta, tipo 22 movimiento, tipo 23 información complementaria, tipo 33 cierre de cuenta).
- Cada banco puede tener pequeñas variaciones o campos opcionales distintos.

## Alcance

- Parser de ficheros Norma 43 a estructura de datos interna.
- Importación como Bank Transaction en ERPNext.
- Conciliación automática/asistida contra Payment Entry / Sales Invoice / Purchase Invoice existentes.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en parsing de Norma 43)*

## Diseño técnico propuesto

*(Por completar — evaluar si se apoya en el Bank Reconciliation Tool nativo de ERPNext o si requiere un flujo propio)*

## Dudas abiertas

- ¿Cuántos bancos distintos hay que soportar y qué variaciones de formato tienen realmente en la práctica (para no sobre-generalizar el parser)?
- ¿El motor de conciliación nativo de ERPNext (Bank Reconciliation Tool) es suficiente o hay que extenderlo?

## Tareas para agentes

- [ ] Escribir parser de Norma 43 (registros 11/22/23/33) a JSON/lista de movimientos.
- [ ] Mapear movimientos parseados a Bank Transaction de ERPNext.
- [ ] Probar con extractos reales de al menos 2-3 bancos distintos para detectar variaciones de formato.
