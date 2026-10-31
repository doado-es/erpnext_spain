# 15 — Funcionalidades: facturación masiva, envío masivo y validador de NIF/VIES

Fase 5 · Depende de: 05, 06, 09 · Peticiones del usuario F1–F4 (`docs/pendientes.md`)

Escrita el 31/10/2026 durante el desarrollo autónomo, con las decisiones marcadas **[revisar]** para validarlas con el usuario.

## F1. Facturación masiva de albaranes de venta

- Acción en la lista de **Delivery Note**: "Facturar seleccionados". También endpoint `erpnext_spain.es_facturacion.bulk.invoice_delivery_notes(delivery_notes, group_by_period, submit)` (POST, rol Accounts User/Manager, permiso de creación de Sales Invoice).
- Solo albaranes validados, no devueltos, no cerrados y con algo pendiente de facturar (`per_billed < 100`).
- **Agrupación**: una factura por compañía, cliente, moneda, lista de precios, plantilla de impuestos, dirección de facturación y condiciones de pago; opcionalmente, también por **mes** del albarán. Albaranes con valores distintos en esos campos no se mezclan (van a facturas distintas). **[revisar]**
- Se usa el mapeo nativo de ERPNext (`make_sales_invoice` con `target_doc`), así que las líneas enlazan a su albarán y el porcentaje facturado se actualiza como en una factura manual.
- La factura se crea en **borrador** por defecto (numeración fiscal al validar, spec 05); opcionalmente se valida.
- Más de 20 albaranes: en segundo plano, con aviso al terminar.

## F2. Facturación de albaranes de compra

- Acción en la lista de **Purchase Receipt**: "Registrar factura del proveedor". Los albaranes deben ser del **mismo proveedor**, compañía y moneda.
- Pide el número y la fecha de la factura del proveedor (`bill_no`, `bill_date`, obligatorios) y crea **una** Purchase Invoice con todas las líneas pendientes, en borrador (o validada si se pide).
- Endpoint `erpnext_spain.es_facturacion.bulk.invoice_purchase_receipts(purchase_receipts, bill_no, bill_date, submit)`.

## F3. Envío masivo de facturas por correo

- Acción en la lista de **Sales Invoice**: "Enviar por correo". Endpoint `erpnext_spain.es_facturacion.mailing.send_invoices(sales_invoices, group_by_customer, resend)`.
- Siempre en segundo plano (cola `long`). Solo facturas validadas.
- Destinatario: correo del contacto de la factura (`contact_email`) o, si no hay, el del contacto principal del cliente. Sin destinatario: se registra el error y se sigue.
- Formato de impresión español (spec 05 §5) en PDF y plantilla de correo **"ES Factura"** (datos iniciales, editable por el usuario).
- Una factura por correo o todas las de un cliente en uno (opción).
- **No se reenvía** lo ya enviado (`es_emailed_on` en la factura) salvo que se pida.
- Registro en **ES Invoice Email Log** (factura, cliente, destinatario, estado, error, fecha).

## F4. Validador de NIF/NIE/CIF y NIF-IVA europeo (VIES)

- El verificador de formato y dígito de control ya existe (módulo `nif`). Se añade:
  - Comprobación del NIF-IVA europeo en **VIES** (API REST de la Comisión Europea, `check-vat-number`) para clientes y proveedores de otros Estados de la UE. Adaptador con cliente real y cliente simulado para los tests.
  - Resultado en el tercero: `es_vies_status` (Válido / No válido / No disponible), `es_vies_name` (nombre registrado) y `es_vies_checked_on`.
  - Acción masiva en las listas de Customer y Supplier ("Comprobar NIF") que revisa el formato del NIF español o, para la UE, consulta VIES, en segundo plano.
- Contraste de NIF y nombre con el censo de la AEAT (requiere certificado): **pendiente** (interfaz preparada, sin cliente).

## Criterios de aceptación

1. Tres albaranes de dos clientes generan dos facturas; las líneas enlazan a sus albaranes y estos quedan facturados al validar.
2. Con agrupación por mes, dos albaranes del mismo cliente de meses distintos van a facturas distintas.
3. Un albarán ya facturado o cerrado no se incluye y se informa.
4. Albaranes de compra de dos proveedores dan error; de uno solo, una factura con `bill_no` y `bill_date`.
5. El envío masivo crea un correo por factura (o por cliente) con el PDF adjunto, registra el resultado y no reenvía lo enviado.
6. La comprobación VIES guarda estado, nombre y fecha; un NIF-IVA no válido queda marcado; sin servicio, "No disponible".
7. Sin rol, ningún endpoint escribe.
