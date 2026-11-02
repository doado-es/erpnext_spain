# hooks.py: por qué está cada hook

`erpnext_spain/hooks.py` solo lleva comentarios técnicos breves. Aquí queda el
motivo de cada hook y la spec o decisión de la que viene.

## doc_events

| Doctype | Evento | Handler | Motivo |
|---|---|---|---|
| Account | validate | `es_contabilidad.account.validate` | Número y rama de las cuentas nuevas en compañías PGC (spec 02 §4). |
| Customer, Supplier, Company | validate | `es_nif.party.validate` | Validación del NIF español (spec 14 §2). Salida temprana barata dentro del handler (doc 12 §2). |
| Address | validate | `es_impuestos.tax_category.set_address_category` | Categoría de impuestos por país (España, UE, resto) (spec 03). |
| Supplier | validate | `es_impuestos.tax_category.set_supplier_category` | Ídem, en el proveedor. |
| Supplier | validate | `es_retenciones.withholding.validate_supplier` | Grupo de retención con fila de tipo en su categoría (spec 08 §3). |
| Item, Item Group | validate | `es_impuestos.item_tax.mirror_rows` | Plantilla de impuestos del artículo también para recargo, retención y adquisición intracomunitaria (ERPNext solo aplica la fila con la misma categoría exacta). |
| Purchase Invoice | validate | `es_retenciones.withholding.validate_purchase_invoice` | Retenciones practicadas: clasificación de la fila e inmueble arrendado (spec 08 §3). |
| Purchase Invoice, Sales Invoice | validate | `es_iva.rows.validate` | Datos del desglose fiscal congelados en la factura (spec 06). |
| Purchase Invoice, Sales Invoice | on_submit / on_cancel | `es_sii.outbox.*` | Envío al SII (spec 14). |
| Purchase Invoice, Sales Invoice | onload | `es_facturacion.fiscal_tab.onload` | Historial de la pestaña «AEAT» o «SII / Factura electrónica». |
| Payment Entry | validate | `es_retenciones.withholding.validate_payment_entry` | Retenciones en pagos (spec 08). |
| Payment Entry, Journal Entry | on_submit / on_cancel | `es_efactura.b2b.payment_changed` | Pago efectivo completo de facturas electrónicas recibidas (spec 10 §5). |
| Bank Account | validate | `es_sepa.bank_account.validate` | Normas bancarias y mandato SEPA en la cuenta (specs 11-12). |
| Bank Transaction | validate | `es_bancos.importer.validate_bank_transaction` | Tercero por IBAN y pago por EndToEndId SEPA (spec 13 §4). |
| Company | validate | `utils.company.set_default_legal_name` | Razón social por defecto: el nombre de la compañía. |
| Company | validate | `es_sii.company.validate`, después `es_verifactu.company.validate` | SII y VeriFactu son excluyentes (spec 14 §1). El orden importa: primero el NIF (verificador), luego el conflicto SII/VeriFactu y al final la compuerta de activación de VeriFactu (spec 04 §2.1), para que el error explique el conflicto. |
| Company | on_update | `utils.gating.clear_site_pgc_cache` | Caché de «¿hay en el sitio alguna compañía con PGC?» (decisión R7 del 01/11/2026). |
| Company | after_insert | `es_contabilidad.onboarding.after_insert` | Plan PGC automático para las compañías de España (decisión del 01/11/2026). |
| Sales Invoice | autoname | `es_verifactu.invoice.autoname` | Nombre temporal del borrador solo en compañías que numeran al emitir (H1); como doc_event y no como extensión de la clase (H2). |
| Sales Invoice | validate | `es_facturacion.numbering.validate` | Numeración fiscal sin VeriFactu, amend y rectificativas (spec 05 §1-§2). |
| Sales Invoice | validate, before_submit, on_submit, before_cancel | `es_verifactu.emission.*` | Ciclo de emisión (spec 04 §4-6, lotes 4b/4c): validate aplica las compuertas (amend, desglose, simplificada↔POS, NIFs, rectificativa, tipo); before_submit renombra el borrador a la serie fiscal (snapshot de modo, posting_date y guarda de nombres explícitos) y mantiene el cerrojo de la cadena; on_submit crea el RegistroAlta encadenado bajo el cerrojo (y la remisión inmediata tras el commit); before_cancel genera el RegistroAnulación (según el snapshot de modo de la factura). |
| Sales Invoice | on_submit | `es_efactura.b2b.on_submit` | Factura electrónica B2B (spec 10 §5). |
| Sales Invoice | before_cancel | `es_efactura.api.block_cancel_if_presented` | No anular facturas ya presentadas en FACe (spec 10). |

## regional_overrides

`validate_regional` de ERPNext → `es_impuestos.invoice.validate_regional`: clasificación fiscal de las filas de impuestos (spec 03 §5). La región es el país de la compañía.

## JS de escritorio

- `app_include_js` → `public/js/notices.js`: avisos en el escritorio (evento realtime `erpnext_spain_notice`). Se sirve tal cual desde `public/`, sin bundle.
- `boot_session`: indica al navegador si el sitio tiene alguna compañía con PGC (formularios de terceros; decisión R7).
- `doctype_js` de Company:
  - `es_verifactu/public/js/company.js`: avisos legales del interruptor de VeriFactu, aviso discreto de modo pruebas y fecha de activación de solo lectura (spec 04 §2.1/§15).
  - `es_contabilidad/public/js/company.js`: acción «Aplicar plan PGC» (spec 02 §2).
  - `es_sii/public/js/company.js`.
  - `es_aeat/public/js/company_modes.js`: avisos al activar, pasar a producción, volver a pruebas o desactivar VeriFactu o el SII.
- `doctype_js` de Sales Invoice:
  - `es_verifactu/public/js/sales_invoice.js`: aviso de modo pruebas (snapshot de la factura y modo de pruebas de la compañía en borradores) y diálogo de subsanación (spec 04 §15, lote 6a).
  - `es_efactura/public/js/sales_invoice.js`: botón «Generar Facturae» (spec 10).
  - `es_facturacion/public/js/sales_invoice.js`: situación de cobro (spec 05 §4).
  - `es_facturacion/public/js/fiscal_tab.js`: pestaña «AEAT».
- `doctype_js` de Customer y Supplier → `es_nif/public/js/party.js`: formato de nombre de las personas físicas y contraste del NIF con la AEAT.
- `doctype_js` de Payment Order → `es_sepa/public/js/payment_order.js`: fichero SEPA de transferencias (spec 11 §4).
- `doctype_list_js`:
  - `es_verifactu/public/js/sales_invoice_list.js`: estilo de los BORRADOR-* en la lista de facturas (spec 04 §15).
  - `es_facturacion/public/js/bulk_actions.js`: acciones masivas (spec 15): facturar albaranes, enviar facturas, comprobar NIF.

## jinja

Métodos para los formatos de impresión (doc 12 §14, patrón de India Compliance; spec 04 §11): QR de validación VeriFactu y su URL (el formato imprime el enlace legible junto al código), desglose de IVA, denominación del tercero y razón social (spec 14), desglose por clasificación y rectificada (spec 05 §5). Rutas explícitas por función: solo la API pública del módulo queda expuesta a las plantillas.

## Asistente de configuración

`setup_wizard_requires` y `setup_wizard_stages`: pantalla «Plan General Contable» y etapa que aplica el PGC a la compañía que crea ERPNext (`es_contabilidad/onboarding.py`, decisión del 01/11/2026).

## Instalación y migración

- Custom fields declarados en Python (doc 12 §11). La app puede estar ya instalada cuando se añaden campos: por eso se crean tanto en `after_install` como en `after_migrate` (idempotente).
- `after_app_install` (R11): crea los custom fields que dependen de apps opcionales (p. ej. HRMS) cuando estas se instalan después de ERPNext Spain.

## scheduler_events

- `es_aeat.tasks.daily`: aviso diario de caducidad de certificados a 30, 7 y 1 días del fin de vigencia, por los dos canales de incidencias de la compañía (spec 13 §2 y spec 04 §15).
- `es_verifactu.tasks.drain_outbox` (cada minuto): drenaje de la cola de VeriFactu (spec 13 §5 y spec 04 §8). Solo drena las empresas con registros pendientes (sin comprobar si están activadas) y aísla los errores por empresa.
- `es_verifactu.tasks.daily` (lote 5b): alerta de cola estancada (spec 04 §8): registros en PendienteEnvio parados más de 24 h → incidencia por los dos canales.
- `es_facturacion.collection.flag_doubtful_candidates`: aviso de facturas candidatas a dudoso cobro (spec 05 §4).
- `es_bancos.aggregator.warn_expiring_consents` y `sync_all` (cada 6 h): agregador bancario (spec 13 §3). Experimental.
- `es_sii.outbox.warn_deadlines` y `drain_outbox` (cada 15 min): plazos y envío al SII (spec 14 §3).
- `es_efactura.b2b.communicate_payments` (cada hora): comunicación del pago de facturas electrónicas recibidas (spec 10 §5).
- Formato cron de 5 campos, el mismo que `frappe/hooks.py` y `erpnext/hooks.py`.

## Hooks transversales (spec 13 §8)

- `company_data_to_be_ignored` (doc 12 §17, R8): configuración y credenciales que no se borran al eliminar las transacciones de una compañía, para que la configuración de cumplimiento sobreviva a los borrados de pruebas. El libro de registros de VeriFactu y los registros del SII son historia legal inmutable: nunca se borran con las transacciones. También las series y los roles de notificación de VeriFactu, los inmuebles arrendados y el agregador bancario.
- `ignore_links_on_delete` (doc 12 §17, spec 04 §13): las respuestas de la AEAT y los registros de VeriFactu son históricos y no deben bloquear borrados legítimos de documentos de negocio. La línea es tabla hija: su enlace se ignora a través del padre.
- `user_data_fields` (doc 12 §17): protección de datos en exportaciones y anonimizado; la contraseña del certificado es dato sensible del propietario de la credencial.
