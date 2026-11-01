# Pendientes

Lista única de lo que falta, para ir cerrándolo por orden. Cada punto remite a su spec. Actualizado el 30/10/2026.

## Funcionalidades nuevas (no son de cumplimiento)

Peticiones del usuario del 30/10/2026. **Hecho (31/10/2026)**, con su spec en `docs/specs/15-funcionalidades.md`: facturación masiva de albaranes de venta y de compra, envío masivo de facturas por correo y comprobación de NIF (formato) y NIF-IVA (VIES). Pendiente: probar VIES contra el servicio real. **Hecho (31/10/2026)**: contraste con el censo de la AEAT (VNifV2, `nif/aeat_census.py`). La tabla siguiente conserva la petición original.

| Id | Funcionalidad | Notas |
|---|---|---|
| F1 | **Facturación masiva de albaranes de venta**: crear facturas de venta a partir de varios Delivery Note, agrupadas por cliente (y opcionalmente por periodo, dirección o condiciones de pago). | Ya prevista en la spec 07 ("facturación masiva desde albaranes"). Decidir criterios de agrupación, qué hacer con albaranes con distinta moneda, lista de precios o impuestos, y si se valida la factura o se deja en borrador. Debe respetar la numeración fiscal (spec 05) y VeriFactu. |
| F2 | **Facturación masiva de albaranes de compra**: crear facturas de compra a partir de varios Purchase Receipt del mismo proveedor. | La factura de compra la emite el proveedor: hace falta su número y fecha (`bill_no`, `bill_date`). Posible flujo: seleccionar albaranes de un proveedor y registrar la factura recibida que los agrupa. |
| F3 | **Envío masivo de facturas por correo**: enviar a cada cliente sus facturas validadas (una por correo o agrupadas), con el formato de impresión español y plantilla de correo. | En segundo plano (cola), con registro de lo enviado y de los errores, y sin reenviar lo ya enviado salvo que se pida. Destinatario: contacto de facturación del cliente. |
| F4 | **Validador de NIF/NIE/CIF y de NIF-IVA europeo**: herramienta para comprobar identificadores a demanda (uno suelto o una lista, p. ej. todos los clientes y proveedores) y no solo al guardar el tercero. | Ya existe el verificador de formato y dígito de control de NIF, NIE y CIF (módulo `nif`, que valida al guardar Customer, Supplier y Company) y el informe ES NIF Checkup. Falta: (a) comprobación en línea del NIF-IVA europeo en **VIES** (servicio de la Comisión Europea; necesario para entregas intracomunitarias exentas); (b) opcionalmente, contraste de NIF y nombre con el censo de la AEAT (servicio de identificación fiscal, requiere certificado); (c) guardar resultado y fecha de la última comprobación en el tercero; (d) pantalla o acción masiva. |

## Fase 0 — fundamentos (spec 01)

- Compatibilidad con v16 anteriores a 16.50 (D1, 01/11/2026): sin probar. Posible job de CI con Frappe y ERPNext de una v16 antigua; la pestaña fiscal ya tiene alternativa sin `EmbeddedList`.
- Avisos (WARNING) de `frappe/semgrep-rules`: textos sin `_()` en mensajes e informes (bloque 9) y `file-traversal` en rutas internas de la app. El CI solo falla con hallazgos ERROR.


## Plan contable (spec 02)

- Plan PGC automático (01/11/2026): probar el asistente de configuración completo en un sitio nuevo y la aplicación en segundo plano con un worker real (los tests llaman a las funciones directamente).
- §6 Subcuentas por tercero (decisión A1, opcional).
- Revisión contable del reparto de ramas y de las cuentas por defecto (2819 como amortización acumulada, 406, 6590 para redondeos, 6680 para diferencias de cambio…).
- Verificado (31/10/2026): con el inventario permanente desactivado, el Stock Ledger valora las existencias (test de regularización). Falta revisar compras y ventas de artículos de existencias de punta a punta.

## Impuestos (specs 03 y 09)

- Verificar en la documentación de la AEAT los códigos E7, E8 y la clave de régimen 21, y los textos de las claves de régimen.
- Revisión contable: IVA no deducible a la 6310.
- Spec 09: revisar cada año los festivos nacionales con la resolución del BOE (patch anual que añada el año).

## Estados financieros (spec 04)

- **Hecho (31/10/2026)**: modelos Normal y Abreviado, reclasificación por signo (por tercero en clientes y proveedores), sumas y saldos, libro diario, traspaso de 8/9 y regularización de existencias.
- PyG del modelo Normal sin el desglose a), b)… de cada partida (solo partidas principales y resultados); añadirlo si se presentan cuentas normales.
- Revisión contable del mapeo Normal y Abreviado (columna `nota`: 200, 257, 473, 553, 5585, 135, 136, 1341, subgrupo 15, 774…) y de las tablas de cierre (8/9 → 13x, clases de existencias por grupo de artículos).
- Formato del libro diario para legalización.
- Revisar las cuentas añadidas al mapeo PYMES que el modelo del BOE no recoge (columna `nota`: 473, 5585, 550, 554, 137, 15x, 195/197/199, 502, 507, 678, 778).

## Facturación (spec 05)

- **Hecho (31/10/2026)**: numeración fiscal sin VeriFactu, rectificativas (método y motivo), bloqueo de *amend*, situación de cobro y formato único.
- Revisión contable del esquema de dudoso cobro, deterioro, pérdida y recuperación (4360, 4900, 6940, 6500, 7940); cobro posterior a una pérdida definitiva (hoy, asiento manual a la 778).
- Rectificación por sustitución en VeriFactu (exige los importes de la rectificada; hoy se bloquea).
- Formato: desglose en moneda de la compañía (el detalle por artículo de ERPNext va en esa moneda); facturas en moneda extranjera por revisar.
- Decidir con el asesor si se bloquea emitir con fecha distinta de la de hoy (hoy, el borrador toma la fecha de emisión).

## Registro fiscal de IVA (spec 06)

- **Hecho (31/10/2026)**: desglose fiscal sobre la marcha desde la factura (sin doctype propio, revisión con el usuario), libros de expedidas y recibidas, borrador de liquidación y desglose común para VeriFactu, el SII y el 303.
- Rendimiento de los libros anuales con mucho volumen (se recorren las facturas del periodo): si hiciera falta, informe preparado de ERPNext.
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

- Factura electrónica (spec 10): **hecho Facturae 3.2.2 firmado para FACe con subida manual (31/10/2026)**. Pendiente: validar a mano un primer XML con el validador del Ministerio o en el entorno de pruebas de FACe; servicio web de FACe; facturas en moneda extranjera; descuentos por línea y generales; **B2B hecho (31/10/2026)** con canal manual o simulado: UBL 2.1, recepción y estados. Pendiente B2B: canal real (SPFE o plataforma, A9), validación Schematron EN 16931 (XSLT 2.0) y CIUS española de la AEAT, recargo de equivalencia y retenciones según la CIUS, unidades de medida (hoy C62).

- VeriFactu: prueba real en el entorno de pruebas de la AEAT (falta certificado); pendientes del TODO del código base (catálogos L8A y L10, formato del QR, paginación de la consulta, errores).
- **Hecho (31/10/2026)**: SII (spec 14) con cliente simulado. Pendiente: envío real al entorno de pruebas de la AEAT (falta certificado); libro de bienes de inversión y criterio de caja; con varias calificaciones (S1 y S2) en una misma factura expedida solo se informa la primera; destinatarios extranjeros siempre como entrega de bienes (falta distinguir prestaciones de servicios) **[revisar]**.
- **Hecho (31/10/2026)**: SEPA (spec 11), Norma 43 y adaptador de agregador (spec 13) y confirming AEF (spec 12).
- SEPA: verificación previa del beneficiario por lotes (VoP, §7, acuerdo bilateral con cada banco); `pain.001.001.03`/`pain.008.001.02` si algún banco los exige; plazos de presentación y caducidad de mandatos **[revisar]**; formato de los ficheros de devoluciones de cada banco.
- Agregador bancario real (decisión A8): hoy solo el adaptador simulado. camt.053.
- Confirming: probar el fichero con una entidad; el estándar no define ficheros de respuesta (estados a mano).
- **Hecho (31/10/2026)**: modelos 303 y 111 (cálculo, casillas revisables y fichero AEAT). Pendiente: importar los ficheros en el programa de la AEAT para comprobarlos; casillas del 303 sin origen automático (importaciones, regularizaciones, prorrata definitiva, régimen simplificado, criterio de caja) y opciones de la página 01 por defecto (no foral, no REDEME, solo régimen general…) **[revisar]**; modelos 115, 190, 180, 390, 349, 347 y 130.

## Traducciones

- **Hecho (31/10/2026)**: 157 cadenas compuestas de ERPNext revisadas con la terminología de España (pedido de venta y de compra, albarán, presupuesto, artículo, centro de coste, movimiento de existencias) con `locale/revise_erpnext_terms.py`, marcadas «automática, revisar»; nombres de los doctypes, informes y módulos nuevos. Pendiente: revisar a mano esas 157 entradas (concordancias de adjetivos y mayúsculas heredadas de ERPNext); el código heredado de VeriFactu tiene mensajes sin `_()` (avisos de Semgrep).
- Regenerar las cadenas que falten tras cada actualización de ERPNext.

## Datos de prueba

- El script de datos de prueba de `ctg` está fuera del repo (`~/es/specs/dev/demo_ctg.py`; se ejecuta copiándolo como módulo temporal de la app y con `bench --site es.localhost execute`). Decidir si se incorpora como herramienta de desarrollo.
