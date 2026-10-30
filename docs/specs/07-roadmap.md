# 07 — Hoja de ruta (por detallar)

Funcionalidades posteriores. Cada una tendrá su spec completa antes de empezar; aquí se fijan el objetivo, los puntos de extensión previstos y las restricciones que ya se conocen. Todas cumplen R1–R12 del maestro.

Ya tienen spec propia: factura electrónica B2G y B2B (10), SEPA (11), confirming (12), conciliación bancaria y Norma 43 (13) y SII (14). Verifactu está implementado en el código base.

## Verifactu — implementado (v1) en el código base

- Libro de registros encadenado (alta y anulación), emisión con numeración al emitir, subsanación, consulta a la AEAT, QR y formato de impresión, notificaciones por roles y outbox sobre la capa AEAT. Ver la spec 04 del repo y el inventario.
- **Plazos**: tras el Real Decreto-ley 15/2025, de 2 de diciembre (BOE 03/12/2025), 1 de enero de 2027 para contribuyentes del Impuesto sobre Sociedades y 1 de julio de 2027 para el resto. Quien lleva sus libros por el SII (spec 14) queda fuera de Verifactu.
- **Pendientes** (TODO del código base y estas specs): desglose real en lugar del stub por descripción (spec 06 §6); numeración independiente de Verifactu y sin extensión de clase (spec 01 §8, H1 y H2); perfil de firma y catálogos L8A y L10 contra la Orden HAC/1177/2024; formato exacto del QR; paginación de la consulta; catálogo completo de errores de la AEAT.
- **Riesgo**: es software sujeto a declaración responsable del productor; conviene revisión jurídica antes de publicarlo.

## Modelos AEAT

- 303, 390, 349, 347, 111, 115, 190, 180 y 130, generados desde el Registro Fiscal IVA (spec 06) y, para las retenciones, desde la tabla nativa `Tax Withholding Entry` (spec 08), con un doctype de declaración por compañía y periodo, cálculo revisable y exportación al formato de la AEAT.
- Las compañías en el SII no presentan 347 ni 390 **[verificar]** (spec 14).
- Primera entrega: 303 y 111, por frecuencia.

## Otros

- Factoring (cesión de facturas de venta) con el formato estándar de factoring de la AEF (spec 12).
- Envío automático de ficheros SEPA al banco (EBICS o API de pagos) (spec 11).
- Traducciones es-ES: catálogo `erpnext_spain/locale/es.po` (primera versión el 30/10/2026). Como la app se instala después de ERPNext, sus traducciones prevalecen sobre las de Frappe y ERPNext (`get_translations_from_apps` las aplica por orden de instalación) **[verificado v16]**. Contiene: los nombres de los doctypes y módulos propios; las cadenas que faltan en los `es.po` de Frappe (51) y ERPNext (648) de la versión instalada; y la terminología contable y comercial de España en lugar de la general (Libro mayor, Balance de sumas y saldos, Centro de coste, Albarán, Presupuesto, Pedido de venta, Artículo, Amortización…). Pendiente: revisión es-ES completa de las cadenas compuestas de ERPNext (p. ej. las que contienen «Sales Order» o «Item»), que siguen con la variante general, y regenerar las que falten tras cada actualización de ERPNext. Los `.mo` se compilan con `bench build` o `bench compile-po-to-mo --app erpnext_spain`.
- Facturación masiva desde albaranes de venta (Delivery Note → Sales Invoice agrupada por cliente y periodo) y de compra (Purchase Receipt → Purchase Invoice). Ver `docs/pendientes.md`, F1 y F2.
- Envío masivo de facturas por correo. Ver `docs/pendientes.md`, F3.
- Contribución del plan PGC a la carpeta `verified` de ERPNext, con `disable_default_financial_report_template` (spec 02).
- Estado de cambios en el patrimonio neto y estado de flujos de efectivo (spec 04).
