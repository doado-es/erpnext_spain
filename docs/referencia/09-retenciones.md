# 9. Gestión de Retenciones a Profesionales (IRPF)

[← Volver al índice](00-maestro.md)

## Objetivo

Aplicar y gestionar correctamente la retención de IRPF en las facturas de proveedores que sean profesionales (autónomos), calculando el importe retenido, reflejándolo en la contabilidad y facilitando su declaración (modelo 111 trimestral, modelo 190 resumen anual, certificados de retenciones).

## Contexto normativo

- Tipo de retención habitual para profesionales: 15% (7% o 20% en determinados casos: inicio de actividad, IRPF adicional aprobado por ley).
- Retenciones distintas de las de arrendamientos (que también existen en el PGC pero con otro tipo, típicamente 19%).
- Modelo 111 (trimestral) y Modelo 190 (resumen anual) para declarar las retenciones practicadas.

## Alcance

- Marcar proveedores como "profesional sujeto a retención" con su tipo aplicable.
- Cálculo automático de la retención en Purchase Invoice y su reflejo en la cuenta contable correspondiente (pasivo con Hacienda).
- Generación de informes/modelos 111 y 190.
- Emisión de certificado de retenciones para el proveedor.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en retenciones)*

> **Dependencia activa**: el IRPF afecta al `ImporteTotal` del registro VeriFactu y a los flujos de rectificativa (04, §6–§7): el contrato de desglose fiscal que consume VeriFactu debe exponer la retención aunque no forme parte del `DetalleDesglose` AEAT.

## Diseño técnico propuesto

*(Por completar — evaluar si se apoya en el motor de Tax Withholding Category que ya existe en ERPNext, adaptándolo a los tipos y modelos españoles)*

## Dudas abiertas

- ERPNext ya tiene un concepto de "Tax Withholding Category" (pensado originalmente para India/TDS) — ¿es reutilizable con adaptaciones o hay que construir algo propio?
- ¿Se incluyen también retenciones de alquileres (arrendamientos) en el mismo alcance o se deja para una fase posterior?
- ¿Prioridad del modelo 111 (trimestral, más urgente) frente al 190 (anual)?

## Tareas para agentes

- [ ] Evaluar el motor nativo "Tax Withholding Category" de ERPNext como base.
- [ ] Implementar cálculo automático de retención en Purchase Invoice según tipo de proveedor.
- [ ] Diseñar report builder para el Modelo 111.
- [ ] Diseñar report builder para el Modelo 190.
- [ ] Diseñar Print Format de certificado de retenciones.
