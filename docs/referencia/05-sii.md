# 5. Conexión al SII

[← Volver al índice](00-maestro.md)

## Objetivo

Integrar ERPNext con el Suministro Inmediato de Información (SII) de la AEAT, obligatorio para grandes empresas y quienes lo soliciten voluntariamente, con envío casi en tiempo real de los registros de facturación (emitidas, recibidas, bienes de inversión, cobros en metálico).

## Contexto normativo

- Envío mediante servicios web SOAP de la AEAT.
- Plazos de envío muy cortos (pocos días hábiles) desde la emisión/registro de la factura.
- Distinto de VeriFactu: quien está en SII no está obligado a VeriFactu (son sistemas alternativos, no acumulativos).

## Alcance

- Generación de los XML de registro de facturación (LRFacturasEmitidas, LRFacturasRecibidas...).
- Envío mediante SOAP con certificado digital.
- Gestión de respuestas de la AEAT (aceptado, aceptado con errores, rechazado) y su reflejo en ERPNext.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en SII. Nota: el módulo `l10n_es_aeat_sii_oca` de Odoo es una referencia útil de los campos y claves de registro que exige la AEAT, aunque no reutilizable directamente)*

> **Dependencia activa**: el SII construye sobre la capa AEAT compartida ([13-capa-aeat.md](13-capa-aeat.md) — credenciales por propósito `SII`, cliente SOAP, outbox con reintentos, registro de respuestas). El diseño de 04 la define; no duplicar infraestructura aquí. Además usa el **verificador de NIF/CIF transversal** ([14-verificador-nif.md](14-verificador-nif.md)) como última compuerta en Sales/Purchase Invoice — los registros SII llevan NIF de emisor Y contraparte, y en compras (Purchase Invoice) hace falta también el NIF del proveedor. Naming de contrapartes según el modelo de nombres de 14: `supplier_name` = razón social (los registros de recibidas llevan el nombre del emisor-proveedor).
>
> **Referencia externa verificada: OCA `l10n_es_aeat_sii_oca`** (Mature, desde 2017): envía al validar la factura (sincrónico en el request) con parámetro de lote (`sii_batch`, default 50), URLs del servicio SOAP configurables **por company** porque cambian según comunidad (Bizkaia/Gipuzkoa/Araba tienen SII propio — evaluar modelo de datos de agencias/URLs al detallar este spec). Su roadmap es nuestro backlog de referencia: aún le faltan reintentos controlados ("Sistema de control de número de reintentos" — nosotros lo tenemos en 13), rectificativas por sustitución, cobros/pagos, bienes de inversión, agencias de viaje, canje simplificadas→completas. No asumir que OCA cubre todo: su roadmap dice qué casos son difíciles.

## Diseño técnico propuesto

*(Por completar)*

## Dudas abiertas

- ¿Se prioriza SII o VeriFactu como primer entregable, dado que son excluyentes según el tipo de empresa? (afecta a qué construir primero)
- ¿Reutiliza la misma capa de firma con certificado digital que VeriFactu/eFactura, o va independiente?
- Gestión de reintentos y errores de comunicación con los webservices SOAP de la AEAT.

## Tareas para agentes

- [ ] Revisar especificación técnica SII (esquemas XSD oficiales de la AEAT).
- [ ] Diseñar capa de comunicación SOAP reutilizable (certificado, entornos pruebas/producción).
- [ ] Mapear Sales Invoice / Purchase Invoice de ERPNext a los XML de registro exigidos.
- [ ] Implementar gestión de respuestas y reintentos.
