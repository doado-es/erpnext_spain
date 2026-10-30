# 2. Generación de Ficheros SEPA (antigua Norma 19, 34...)

[← Volver al índice](00-maestro.md)

## Objetivo

Generar los ficheros de adeudos y transferencias SEPA (formato XML ISO 20022 — pain.001 para transferencias, pain.008 para adeudos directos/remesas de recibos) que sustituyeron a las antiguas normas del Consejo Superior Bancario (Norma 19, Norma 34) para el intercambio con bancos españoles.

## Contexto normativo / técnico

- SEPA Credit Transfer (SCT) → formato `pain.001.001.03` (o versiones posteriores)
- SEPA Direct Debit (SDD) → formato `pain.008.001.02`, con distinción entre CORE y B2B
- Requiere gestión de mandatos SEPA (mandate ID, fecha de firma) para los adeudos

## Alcance

- Generación de remesas de recibos (adeudos a clientes) desde Sales Invoice / Payment Entry.
- Generación de ficheros de transferencia (pagos a proveedores) desde Payment Entry.
- Gestión de mandatos SEPA asociados a clientes.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en generación de ficheros SEPA)*

## Diseño técnico propuesto

*(Por completar)*

## Dudas abiertas

- ¿Se generan las remesas desde Payment Entry existente o se crea un DocType propio "Remesa SEPA" que agrupe varios Payment Entry / Sales Invoice?
- ¿CORE o B2B como default, o configurable por cliente?
- ¿Gestión de devoluciones de recibos (impagados) como flujo de vuelta?

## Tareas para agentes

- [ ] Definir DocType para Mandato SEPA y su relación con Customer.
- [ ] Implementar generador de XML pain.008 para remesas de recibos.
- [ ] Implementar generador de XML pain.001 para transferencias a proveedores.
- [ ] Validar los ficheros generados contra un validador SEPA de referencia antes de producción.
