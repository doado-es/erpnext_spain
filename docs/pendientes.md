# Pendientes

Lista única de lo que falta, para ir cerrándolo por orden. Cada punto remite a su spec. Actualizado el 30/10/2026.

## Funcionalidades nuevas (no son de cumplimiento)

Peticiones del usuario del 30/10/2026. Cada una tendrá su spec antes de empezar.

| Id | Funcionalidad | Notas |
|---|---|---|
| F1 | **Facturación masiva de albaranes de venta**: crear facturas de venta a partir de varios Delivery Note, agrupadas por cliente (y opcionalmente por periodo, dirección o condiciones de pago). | Ya prevista en la spec 07 ("facturación masiva desde albaranes"). Decidir criterios de agrupación, qué hacer con albaranes con distinta moneda, lista de precios o impuestos, y si se valida la factura o se deja en borrador. Debe respetar la numeración fiscal (spec 05) y VeriFactu. |
| F2 | **Facturación masiva de albaranes de compra**: crear facturas de compra a partir de varios Purchase Receipt del mismo proveedor. | La factura de compra la emite el proveedor: hace falta su número y fecha (`bill_no`, `bill_date`). Posible flujo: seleccionar albaranes de un proveedor y registrar la factura recibida que los agrupa. |
| F3 | **Envío masivo de facturas por correo**: enviar a cada cliente sus facturas validadas (una por correo o agrupadas), con el formato de impresión español y plantilla de correo. | En segundo plano (cola), con registro de lo enviado y de los errores, y sin reenviar lo ya enviado salvo que se pida. Destinatario: contacto de facturación del cliente. |
| F4 | **Validador de NIF/NIE/CIF y de NIF-IVA europeo**: herramienta para comprobar identificadores a demanda (uno suelto o una lista, p. ej. todos los clientes y proveedores) y no solo al guardar el tercero. | Ya existe el verificador de formato y dígito de control de NIF, NIE y CIF (módulo `nif`, que valida al guardar Customer, Supplier y Company) y el informe ES NIF Checkup. Falta: (a) comprobación en línea del NIF-IVA europeo en **VIES** (servicio de la Comisión Europea; necesario para entregas intracomunitarias exentas); (b) opcionalmente, contraste de NIF y nombre con el censo de la AEAT (servicio de identificación fiscal, requiere certificado); (c) guardar resultado y fecha de la última comprobación en el tercero; (d) pantalla o acción masiva. |

## Fase 0 — fundamentos (spec 01)

- Avisos (WARNING) de `frappe/semgrep-rules`: textos sin `_()` en mensajes e informes (bloque 9) y `file-traversal` en rutas internas de la app. El CI solo falla con hallazgos ERROR.


## Plan contable (spec 02)

- §6 Subcuentas por tercero (decisión A1, opcional).
- Revisión contable del reparto de ramas y de las cuentas por defecto (2819 como amortización acumulada, 406, 6590 para redondeos, 6680 para diferencias de cambio…).
- Verificar en bench compras y ventas de artículos de existencias con el inventario permanente desactivado (A3).

## Impuestos (specs 03 y 09)

- Verificar en la documentación de la AEAT los códigos E7, E8 y la clave de régimen 21, y los textos de las claves de régimen.
- Revisión contable: IVA no deducible a la 6310.
- Spec 09: revisar cada año los festivos nacionales con la resolución del BOE (patch anual que añada el año).

## Estados financieros (spec 04)

- Modelos Abreviado y Normal (Balance y PyG).
- Reclasificación por signo de clientes y proveedores con saldo contrario y de bancos en descubierto.
- Revisar las cuentas añadidas al mapeo PYMES que el modelo del BOE no recoge (columna `nota`: 473, 5585, 550, 554, 137, 15x, 195/197/199, 502, 507, 678, 778).
- §4 Sumas y saldos por niveles; §5 libro diario numerado; §6 traspaso de los grupos 8 y 9; §7 regularización de existencias.

## Facturación (spec 05)

- **Hecho (31/10/2026)**: numeración fiscal sin VeriFactu, rectificativas (método y motivo), bloqueo de *amend*, situación de cobro y formato único.
- Revisión contable del esquema de dudoso cobro, deterioro, pérdida y recuperación (4360, 4900, 6940, 6500, 7940); cobro posterior a una pérdida definitiva (hoy, asiento manual a la 778).
- Rectificación por sustitución en VeriFactu (exige los importes de la rectificada; hoy se bloquea).
- Formato: desglose en moneda de la compañía (el detalle por artículo de ERPNext va en esa moneda); facturas en moneda extranjera por revisar.
- Decidir con el asesor si se bloquea emitir con fecha distinta de la de hoy (hoy, el borrador toma la fecha de emisión).

## Registro fiscal de IVA (spec 06)

- **Hecho (31/10/2026)**: Registro Fiscal IVA, reconstrucción, libros de expedidas y recibidas, borrador de liquidación y desglose común para VeriFactu.
- Confirmar con el usuario la autorrepercusión con dos filas en la plantilla de compra (implementada y probada con el registro y la liquidación) frente al regional override.
- Importaciones con DUA (base del valor en aduana).
- VeriFactu: comprobar contra el entorno de pruebas el desglose de N1/N2 (hoy se envía tipo y cuota 0) y el recargo de equivalencia.
- Tipo de factura de las recibidas (hoy F1, o R1 si es rectificativa) y clave de identificación del tercero (02 UE, 06 resto) **[revisar]** con el SII.

## Retenciones (spec 08)

- **Hecho (31/10/2026)**: categorías, grupos, cuenta 4751, validación del proveedor, inmuebles arrendados, clasificación de la fila e informes de practicadas y soportadas.
- A7: periodo de 111 y 115 por fecha de pago o de factura (hoy, fecha de la retención). Decidir con el asesor.
- Revisar con el asesor los tipos, las claves y subclaves del 190 de cada categoría y los grupos con reducción del 60 % (art. 68.4 LIRPF).
- Exigir `apply_tds` cuando el proveedor tenga categoría (evitar facturas de profesionales sin retención por olvido).

## Comunicación con la AEAT y terceros

- Factura electrónica (spec 10): **hecho Facturae 3.2.2 firmado para FACe con subida manual (31/10/2026)**. Pendiente: validar a mano un primer XML con el validador del Ministerio o en el entorno de pruebas de FACe; servicio web de FACe; facturas en moneda extranjera; descuentos por línea y generales; B2B (SPFE o plataforma, decisión A9) y recepción de facturas.

- VeriFactu: prueba real en el entorno de pruebas de la AEAT (falta certificado); pendientes del TODO del código base (catálogos L8A y L10, formato del QR, paginación de la consulta, errores).
- SII (spec 14): libros, cola de envío, plazos y cuadre. Hoy solo está la activación.
- Factura electrónica (spec 10), SEPA (spec 11), confirming (spec 12), Norma 43 y conexión bancaria (spec 13).
- Modelos AEAT (spec 07).

## Traducciones

- Revisión es-ES de las cadenas compuestas de ERPNext que siguen con la variante general ("Orden de venta", "Producto"…).
- Regenerar las cadenas que falten tras cada actualización de ERPNext.

## Datos de prueba

- El script de datos de prueba de `ctg` está fuera del repo (`~/es/specs/dev/demo_ctg.py`; se ejecuta copiándolo como módulo temporal de la app y con `bench --site es.localhost execute`). Decidir si se incorpora como herramienta de desarrollo.
