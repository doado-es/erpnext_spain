# 14 — SII (Suministro Inmediato de Información del IVA)

Fase 4 · Depende de: 03, 05, 06 y la capa AEAT del código base (certificado, con la corrección H3 de la spec 01 §8) · Excluyente con Verifactu (07) por compañía

## Objetivo

Llevar los libros registro de IVA en la sede electrónica de la AEAT mediante el envío de los registros de facturación en los plazos del SII, para las compañías obligadas o adheridas voluntariamente, a partir del Registro Fiscal IVA (spec 06).

## Estado normativo — **verificar en la sede de la AEAT (documentación técnica vigente) antes de implementar**

| Elemento | Situación |
|---|---|
| Base | RD 596/2016 (modifica el Reglamento del IVA) y Orden HFP/417/2017; en funcionamiento desde el 01/07/2017. |
| Obligados | Volumen de operaciones superior a 6.010.121,04 € el año anterior, grupos de IVA, inscritos en el REDEME y adheridos voluntariamente (modelo 036). |
| Plazos | 4 días hábiles (sin sábados, domingos ni festivos nacionales). Expedidas: desde la expedición. Recibidas: desde el registro contable, y en todo caso antes del día 16 del mes siguiente al periodo de liquidación **[verificar]**. |
| Efectos | Los obligados no presentan 347 ni 390 **[verificar]**; plazo del 303 mensual. |
| Relación con Verifactu | Quien lleva sus libros por el SII queda fuera de Verifactu. |
| Técnica | Servicios web SOAP con certificado electrónico; respuesta con estado por registro y CSV **[verificar versión de esquema vigente]**. |

## Alcance

1. Configuración por compañía (sistema de registro: SII o Verifactu).
2. Libros: facturas expedidas, facturas recibidas, bienes de inversión, determinadas operaciones intracomunitarias y, si aplica, cobros y pagos del criterio de caja.
3. Construcción de los registros desde el Registro Fiscal IVA.
4. Cola de envío, respuestas, modificaciones y bajas.
5. Control de plazos.
6. Consulta y cuadre con los datos de la AEAT.

## 1. Configuración

- Se construye sobre la **capa AEAT del código base** (spec 13 del repo, ya implementada): `ES AEAT Credential` ya admite el propósito SII; cliente SOAP con TLS mutua, `ES AEAT Response` y su línea por registro, outbox con reintentos y aislamiento por empresa, permisos por empresa y propósito, y notificaciones por roles.
- Activación por empresa con un ajuste propio (`es_sii_enabled`), **excluyente** con `es_verifactu_enabled`: la validación de Company (`doc_event` `validate`) impide activar los dos. Se eligen dos casillas y no un único Select para conservar el gating del código base (`is_feature_enabled(company, flag)`). Como una escritura que no pase por `validate` (`db.set_value`, importaciones) podría saltarse la validación, cada módulo comprueba además la casilla del otro antes de generar registros: si las dos están activas, no genera nada y deja un Error Log que dice cuál desactivar. El cambio de uno a otro solo se permite a partir de un periodo sin facturas registradas en el otro sistema.
- **Hecho (30/10/2026)**: sección "SII" en la pestaña de Company (`es_sii/setup.py`): `es_sii_enabled`, `es_sii_test_mode` (Pruebas/Producción, por defecto Pruebas), `es_sii_activation_date` y `es_sii_credential` (propósito SII). La validación de Company (`es_sii/company.py`) impide activar SII y VeriFactu a la vez y exige el NIF; `utils/gating.active_billing_system` devuelve VeriFactu, SII o ninguno, y si los dos están activos por una escritura sin validación no trata la compañía como ninguno de los dos y deja un Error Log. El aviso de modo pruebas solo aparece con el sistema activado.
- La numeración al emitir (spec 05 §1) no depende de Verifactu, así que las compañías en el SII la tienen igual.
- Entorno: pruebas / producción.

## 2. Datos adicionales

El Registro Fiscal IVA (spec 06) tiene casi todo. Faltan, como custom fields en las facturas o en la clasificación (spec 03):

| Dato | Dónde |
|---|---|
| Clave de régimen especial o trascendencia (01 general, 02 exportación, … **[verificar lista vigente]**) | Clasificación fiscal de la fila (`clave_regimen`, spec 03 §1), con valor por defecto por plantilla. Es el mismo campo que usa Verifactu. |
| Tipo de factura (F1, F2, F3, F4, F5, F6, R1–R5) | Factura; F1/R1–R5 ya existen (spec 05), el resto según el caso |
| Descripción de la operación | Factura (texto, con valor por defecto) |
| Fecha de operación si difiere de la de expedición | Factura |
| Identificación de la contraparte extranjera (IDOtro: país, tipo y número) | Tercero (tipo de identificación de la spec 06) |
| Fecha de registro contable de las recibidas | Fecha de contabilización de la Purchase Invoice |

## 3. Envío

Doctype "ES Sii Record" (módulo `es_sii`), uno por factura y libro, con el mismo patrón que `ES Verifactu Billing Record` del código base (inalterable, en `company_data_to_be_ignored` e `ignore_links_on_delete`):

| Campo | Contenido |
|---|---|
| `company`, `libro`, `voucher_type`, `voucher_no` | Origen |
| `tipo_comunicacion` | Alta / Modificación / Baja **[verificar códigos]** |
| `contenido` | XML o JSON del registro enviado, inalterable |
| `estado` | Pendiente · Enviado · Correcto · Aceptado con errores · Incorrecto |
| `csv`, `codigo_error`, `descripcion_error` | Respuesta de la AEAT, **solo lectura** |
| `fecha_limite` | Calculada con el calendario de días hábiles |
| `intentos`, `ultimo_intento` | Reintentos |

- Generación: `doc_events` `on_submit` de Sales Invoice y Purchase Invoice crean el registro pendiente a partir del Registro Fiscal IVA. Cancelar una factura enviada genera una baja (o la anulación que proceda **[verificar]**). Corregir datos de una factura enviada genera una modificación.
- Envío: el outbox de la capa AEAT, que agrupa los pendientes por compañía y libro (hasta el máximo por petición que admita la AEAT **[verificar]**), los envía y guarda la respuesta en `ES AEAT Response`. Reintentos con la estrategia de errores que ya usa Verifactu.
- Control de plazos: calendario de festivos nacionales en datos iniciales (spec 09); aviso a Accounts Manager de los registros que vencen hoy o mañana y de los vencidos.
- Permisos (R6): envío manual y reenvío solo con rol; el job usa el certificado sin exponerlo.

## 4. Consulta y cuadre

- Consulta de lo registrado en la AEAT por periodo y libro, y comparación con el Registro Fiscal IVA: facturas que faltan, que sobran o con importes distintos.
- Informe de estado del SII por periodo: pendientes, incorrectas, aceptadas con errores.

## Criterios de aceptación

1. Una factura expedida genera un registro de alta pendiente con fecha límite a 4 días hábiles, saltando fines de semana y festivos nacionales.
2. El contenido valida contra el esquema vigente de la AEAT para expedidas y para recibidas.
3. Con el entorno de pruebas de la AEAT, un envío devuelve estado por registro y CSV, y se guardan.
4. Una respuesta "Incorrecto" deja el registro en error con el código y la descripción, y la corrección genera un nuevo envío.
5. Cancelar una factura enviada genera la comunicación de baja.
6. Una compañía con `es_sii_enabled` no genera registros Verifactu, y viceversa. Guardar una Company con las dos casillas activas da error; si se fuerzan las dos por `db.set_value`, ninguno de los dos módulos genera registros y queda un Error Log.
7. ISP, adquisiciones intracomunitarias y rectificativas se envían con las claves y desgloses correctos (casos de la spec 06).
8. El cuadre detecta una factura que no está en la AEAT.

## Pendiente de verificar o decidir

- Versión vigente del esquema y de los servicios web, y límite de registros por envío.
- Plazos exactos de recibidas y de operaciones intracomunitarias.
- Lista vigente de claves de régimen especial y tipos de factura.
- Libro de bienes de inversión y criterio de caja: incluirlos en la primera versión o después.
- Códigos de tipo de comunicación (alta, modificación, baja).
