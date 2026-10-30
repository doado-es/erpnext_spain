# 6. eFactura

[← Volver al índice](00-maestro.md)

## Objetivo

Soportar la facturación electrónica española: formato Facturae para el sector público (FACe) y, en el futuro próximo, la factura electrónica B2B obligatoria derivada de la Ley Crea y Crece.

## Contexto normativo

- **Facturae**: formato XML propio español, obligatorio para facturar a las Administraciones Públicas a través de FACe (Punto General de Entrada de Facturas Electrónicas).
- **Factura electrónica B2B** (Ley Crea y Crece): pendiente de despliegue reglamentario completo; previsiblemente convivirá con o usará el mismo QR/hash de VeriFactu.
- Firma electrónica de la factura (XAdES) requerida para Facturae.

## Alcance

- Generación de Facturae XML desde Sales Invoice.
- Firma XAdES del XML.
- Envío/registro en FACe (o el punto de entrada que corresponda al cliente/administración).
- Preparar el diseño para la futura factura electrónica B2B (aunque el detalle normativo aún no esté cerrado del todo).

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en Facturae/eFactura)*

## Diseño técnico propuesto

*(Por completar)*

## Dudas abiertas

- ¿Prioridad real de esta funcionalidad? (depende de si los clientes objetivo facturan a Administraciones Públicas)
- ¿Comparte capa de firma digital con VeriFactu/SII o es independiente por ser un estándar distinto (XAdES vs. firma AEAT)?
- Nivel de incertidumbre alto sobre el desarrollo reglamentario de la factura B2B — ¿cuánto diseñar ahora vs. esperar?

## Tareas para agentes

- [ ] Revisar especificación Facturae (esquema XSD) y requisitos de FACe.
- [ ] Implementar generación de Facturae XML desde Sales Invoice.
- [ ] Implementar firma XAdES.
- [ ] Seguir la evolución del reglamento de factura electrónica B2B antes de comprometer diseño definitivo.
