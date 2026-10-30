# 4. Conexión a VeriFactu

[← Volver al índice](00-maestro.md)

## Objetivo

Integrar ERPNext con el sistema VeriFactu de la AEAT (Real Decreto 1007/2023 y Orden HAC/1177/2024): generar el registro de facturación encadenado (huella SHA-256 con la huella del registro anterior), incluir el código QR en la factura, y remitir los registros a la AEAT según la modalidad elegida, gestionando respuestas, errores y subsanaciones.

## Contexto normativo

- Cada factura emitida genera un **RegistroAlta**; cada cancelación genera un **RegistroAnulación**. Ambos se encadenan por huella.
- Servicio web SOAP de la AEAT (`sfVerifactu`, WSDL `SistemaFacturacion.wsdl`): operación `RegFactuSistemaFacturacion` (alta/anulación en lotes de hasta 1000 registros) y `ConsultaFactuSistemaFacturacion` (consulta).
- Requiere certificado digital (autenticación TLS mutua en el servicio; perfil de firma del registro a verificar contra la Orden — ver dudas abiertas).
- El software (nosotros, como productor) debe identificarse como **SIF** (Sistema Informático de Facturación) con valores certificados ante la AEAT por release.
- Sistemas alternativos: quien está en SII o TicketBAI no está obligado a VeriFactu (son excluyentes).
- Verificación: el QR de la factura enlaza a la URL de validación de la AEAT (`ValidarQR?nif=&fecha=&importe=&numserie=`).

## Alcance

- Generación del registro de facturación VeriFactu (Alta) en la emisión de Sales Invoice.
- Registro de Anulación en la cancelación de Sales Invoice.
- Encadenamiento de huellas por empresa (SIF).
- Generación e inclusión del QR en el Print Format de factura.
- Remisión a la AEAT en las modalidades: **inmediata** (encolada al submit) o **diferida** (drenada por scheduler, dentro de la ventana legal de remisión consecutiva). La modalidad **sin remisión** (conservación local) queda soportada en el modelo de datos pero fuera del alcance de la v1.
- Gestión del certificado digital y del SIF multi-empresa (varios certificados para varias companies en el mismo site) — vía la capa compartida AEAT (ver [13-capa-aeat.md](13-capa-aeat.md)).
- Subsanación de rechazos (automática y manual) y reintentos.
- Consulta a la AEAT (query de registros).

Fuera de alcance v1: facturas recibidas (VeriFactu solo registra facturas emitidas), modalidad sin remisión, régimen de agencias de viajes y otros regímenes especiales con requisitos de registro propios.

## Estado actual / referencias

### App de referencia (NO se porta tal cual): `testsc/apps/spanish_compliance`

Implementación previa con flujo verificado contra el entorno de pruebas de la AEAT. Reutilizable como **referencia de algoritmos y estructura AEAT**:

- `verifactu/aeat_lib/aeat_client.py` — cliente SOAP (zeep) con TLS mutua, WSDL único con puertos `SistemaVerifactu` / `SistemaVerifactuPruebas`, y el patrón de convertir SOAP Faults en `RespuestaLinea` sintéticas para procesamiento uniforme.
- `verifactu/aeat_lib/aeat_data_adapter.py` (~1174 líneas) — mapeo declarativo ERPNext→AEAT (`ERPNEXT_MAPPER`), huella encadenada, desglose, procesamiento de respuestas, estrategia de errores, subsanación.
- `verifactu/aeat_lib/aeat_communications_manager.py` — remisión diferida por scheduler (cron cada minuto), lotes con límite configurable (máx. 1000 AEAT), rate-limit por compañía (`timeout_seconds`), timezone Europe/Madrid.
- `verifactu/doctype/*` — 6 doctypes (registro, tipos de factura, respuesta AEAT + lineas, query, roles de notificación).
- `overrides/sales_invoice.py` / `overrides/company.py` — ciclo de vida SI (naming BORRADOR + renombrado al submit, bloqueo de amendments, anulación tras aceptación), gestión p12→PEM del certificado.
- `verifactu/aeat_lib/aeat_response_examples/` — ejemplos de respuesta AEAT reales: **usar como fixtures de test**.
- `fixtures/sc_verifactu_sales_invoice_type.json` — tipos de factura con series asociadas.
- Su `todo.md` cataloga los gaps conocidos (ver tabla inferior).

### Deudas conocidas de la referencia (a resolver en este diseño)

| Gap de `todo.md` | Resolución en este diseño |
|---|---|
| `consultar()` roto (company `.pop()`) | Query doctype con selector de company explícito (§10) |
| Valores SIF hardcodeados (certificación por release) | Config en `SC Verifactu Settings`, no en código (§2) |
| Respuestas de Anulación no procesadas | State machine único para Alta y Anulación (§3, §9) |
| Rectificativas de facturas externas no soportadas | Custom fields de rectificada externa (§6) |
| Solo ClaveRegimen "01" | Matriz de régimen vía contrato con 07 (§7) |
| Solo OperacionExenta ausente (L10) | Causa de exención vía contrato con 07 (§7) |
| Asume una sola fila de impuestos | Desglose multi-tasa multi-impuesto (§7) |
| `Company.tax_id` no único → respuestas mal enrutadas | Validación de unicidad al activar VeriFactu en la company (§2) |
| Fetch de todas las respuestas en cada list view | Paginación/cache + queries indexadas (§2) |
| SQL crudo en `es_subsanable` (viola doc 12 §19) | Reimplementar con ORM/qb (§9) |
| `frappe.throw` en el loop del scheduler mata todo el run | Aislamiento por empresa con `log_error` (§8) |
| Sin validador de NIF/CIF — la referencia solo exige presencia del NIF (emisor y destinatario), un NIF mal formado se descubre recién como rechazo AEAT | Verificador transversal con validación en origen (Customer/Supplier/Company) + última compuerta en la factura ([14-verificador-nif.md](14-verificador-nif.md)) |
| Campos `commercial_name` en Company+Customer creados pero **muertos** (cero consumidores — verificado); el registro usaba `customer_name` como razón social de facto | Modelo de nombres de [14](14-verificador-nif.md): `customer_name` = razón social (explícito, a todos los registros), `sc_nombre_comercial` transversal en Customer/Supplier con consumidores definidos (print via jinja), Company sin campo (Letter Head cubre branding) |
| `before_cancel` exige modo factura == modo company ACTUAL (`_check_proper_operational_mode`) → tras desactivar VeriFactu, **no se pueden anular las facturas emitidas durante el período activo** (la AEAT nunca recibe el RegistroAnulación) | Anulación gateada por el snapshot de modo de la factura, no por el modo actual; outbox drena pendientes y anulaciones sin importar `enabled` (§6, §8) |
| `override_doctype_class` en SI/Company (viola doc 12 §3) | `doc_events` + mixin `extend_doctype_class` que SOLO añade `autoname` (§4) |
| **`on_submit` de la referencia no llama `super()`** → el `on_submit` del core (GL entries `sales_invoice.py:510`, stock ledger `:503`, propagación de estados) **nunca se ejecuta**: facturas sin asientos contables. ERPNext no postea GL vía `doc_events` propios (verificado en `erpnext/hooks.py`), no hay vía alternativa | Eliminado por diseño: con `doc_events` el core corre siempre primero (`Document.hook.compose`, `document.py:1633-1647`) — imposible de replicar (§4) |
| QR como property de clase | `jinja.methods` (§11) |

### Referencia externa verificada: OCA `l10n_es_verifactu_oca` (Odoo 17.0, Beta)

El módulo VeriFactu de la comunidad Odoo española (Aures Tic, ForgeFlow, Tecnativa, Factor Libre — README verificado): **su arquitectura coincide con la nuestra** — registro de envío generado al validar la factura + "cada minuto se enviarán todos aquellos registros pendientes mediante un cron" (outbox + scheduler, literal), ledger como modelo independiente (`verifactu_invoice_entry`), respuestas con líneas (`..._response` + `..._response_line`), zeep, certificado p12→claves con botón, datos de desarrollador SIF y encadenamiento configurables. **Su roadmap pide lo que nuestro diseño ya tiene**: envío separado de la validación vía queue_job (nuestra remisión `Inmediata` con `enqueue_after_commit`), control de errores y avisos por caída de AEAT (nuestras incidencias de dos canales + outbox estancado), consulta de estado (nuestro §10), operaciones exentas (contrato 07). **Cita normativa AEAT de su README que confirma nuestros flujos §6/§9**: errores en campos internos del registro → corregir factura original + "RF de alta de subsanación" (nuestro registro de subsanación); factura entera errónea → "RF de anulación" (nuestro RegistroAnulación). Diferencias a retener: activación por *journal* (más granular que nuestra por company — evaluable a futuro), clave de régimen mapeada en *fiscal positions* (nuestro 07 lo posee por contrato), y **el AEAT puede devolver un tiempo de espera entre envíos (>60s) que el cliente debe respetar** (adoptado en §8/13).

### Fuentes oficiales (pendientes de verificar al detalle en implementación)

- Orden HAC/1177/2024 (modelo de registros, catálogos L1–L15, firma) — el diseño asume su estructura según la referencia verificada; **verificar contra texto oficial**: perfil exacto de firma del registro, catálogo completo de tipos F1/F3/R1–R5, códigos de error, y vector de ejemplos oficiales de huella.
- WSDL y documentación AEAT VeriFactu (entorno de pruebas/prewww2).

## Diseño técnico propuesto

### 1. Arquitectura de módulos

```
spain_compliance/
├── aeat/                      # capa compartida (ver 13-capa-aeat.md)
│   ├── doctype/sc_aeat_credential/
│   ├── doctype/sc_aeat_response/
│   ├── doctype/sc_aeat_response_line/
│   ├── client.py              # factoría cliente SOAP (zeep, TLS mutua)
│   ├── signer.py              # firma del registro (perfil a verificar)
│   ├── manager.py             # outbox + reintentos + aislamiento por empresa
│   └── utils.py               # timestamps Europe/Madrid, permisos, notificaciones
└── sc_verifactu/              # funcionalidad (este spec) — módulo "SC Verifactu"
    ├── doctype/
    │   ├── sc_verifactu_settings/            # Single: identidad SIF + config global
    │   ├── sc_verifactu_company_settings/    # child: config por empresa
    │   ├── sc_verifactu_billing_record/      # libro de registros (ledger)
    │   ├── sc_verifactu_invoice_type/        # catálogo F1..R5 (fixture)
    │   └── sc_verifactu_aeat_query/          # consultas a AEAT
    ├── overrides/
    │   └── sales_invoice.py     # doc_events (validate, before_submit, on_cancel)
    ├── mixins/
    │   └── sales_invoice.py     # extend_doctype_class: SOLO autoname/rename
    ├── report/facturas_subsanables/
    └── utils/
        ├── jinja.py             # get_verifactu_qr_code, helpers de print
        └── data_adapter.py      # mapeo declarativo ERPNext→AEAT (puro, testeable)
```

> **Nota de módulo**: el paquete de la funcionalidad es `sc_verifactu/` (módulo Frappe "SC Verifactu"), no `verifactu/` — el nombre desnudo colisiona con el módulo `verifactu` de la app v1 `spanish_compliance` en el mapa inverso módulo→app de frappe y rompe el sync en coexistencia (ver decisión en [00-maestro.md](00-maestro.md)).

Wiring en `hooks.py`:

- `doc_events` → validaciones y ciclo de vida de Sales Invoice (orden-independientes).
- `extend_doctype_class` → mixin de Sales Invoice **solo** para `autoname`/renombrado en submit (pasos orden-críticos que los `doc_events` no garantizan; ver §4).
- `scheduler_events` (cron `* * * * *`) → drenaje del outbox (§8).
- `jinja.methods` → helpers de impresión (§11).
- `after_install`/`before_uninstall` → crear/eliminar Custom Fields (§2.3).
- `company_data_to_be_ignored` → settings y credenciales. `ignore_links_on_delete` → responses y billing records.

### 2. Modelo de datos

#### 2.1 Configuración: `SC Settings` (global) + tab "Spain Compliance" en Company (por empresa)

**`SC Settings`** (Single — hub transversal del app): las cosas **genéricas/globales** de cada funcionalidad, en secciones. Sección VeriFactu: identidad SIF certificada (es del productor del software, no de cada empresa — `nombre_razon`, `nif`, `nombre_sistema_informatico`, `id_sistema_informatico`, `version` por release — nunca hardcode, flags L4) y endpoints WSDL pruebas/producción (editables). Secciones futuras: SEPA genérico, etc. **Nunca** config por-empresa aquí.

**Tab "Spain Compliance" en Company** — Custom Fields vía `create_custom_fields` (doc 12 §11), como Tab Break con Section Breaks por funcionalidad. Sección VeriFactu:

- `sc_verifactu_enabled` (activar), `sc_verifactu_test_mode` (Pruebas/Producción), `sc_verifactu_activation_date`, `sc_verifactu_credential` (Link → `SC AEAT Credential`, compartida con SII — ver 13), `sc_verifactu_remission_mode` (`Inmediata` | `Diferida`), `sc_verifactu_draft_series` (serie de borradores — la usa el mixin `autoname`, §4), **`sc_incidents_email`** (email de incidencias — TRANSVERSAL, no verifactu-scoped: lo consumen las incidencias de remisión §9 Y la caducidad de certificados de la capa 13; todas las features de compliance de la company reportan aquí), `sc_verifactu_timeout_seconds`, `sc_verifactu_batch_limit` (≤ 1000), `sc_verifactu_mandatory_in_order_cure`, `sc_verifactu_noi` (NúmeroInstalación — read-only, derivado al validar).
- Child table (Table field): **`SC Verifactu Series`** — filas `{serie, tipo AEAT}` de ESA company (mapeo series ↔ tipo). Biyección validada (una serie por tipo, un tipo por serie). **Serie única entre companies** (error si se comparte): el contador `tabSeries` es por PREFIJO sin dimensión company (`naming.py` `getseries(key)`) — dos companies con la misma serie intercalarían números y cada una vería huecos en SU serie (correlatividad rota). Defecto latente del modelo de la referencia (series globales por tipo en el fixture).
- Child table: **`SC Verifactu Notification Role`** — roles con notificación in-app de incidencias (Notification Log); `incidents_email` añade el canal email externo (p.ej. asesor fiscal). Ambos canales se disparan desde §9.
- **Validaciones** (doc_event `validate` de Company): al activar: `tax_id` presente, **único entre companies del site** y **válido** (verificador [14](14-verificador-nif.md) — cierra el gap de enrutado de respuestas), credential válida, `activation_date` presente, `draft_series` sin colisión con series mapeadas, biyección y no-compartición de series, derivación de NOI (hash SHA-256 Base32 por (site, company), persistido, no recalculado). **`activation_date` se congela (read-only) en cuanto exista cualquier registro de la empresa** — moverla invalidaría la semántica de los registros ya emitidos. **Desactivar NO exige outbox vacío** (ver §8: el drenaje sigue para lo pendiente y las anulaciones).
- **Avisos legales al activar/desactivar** (JS confirm en el toggle del Company form — la UX; las validaciones server de arriba son la frontera dura):
  - **Al activar**: desde `activation_date`, toda factura emitida genera registros encadenados (huellas) remitidos a la AEAT; los borradores pasan a nombre temporal (número solo al emitir); no se pueden fechar facturas hacia atrás; los amendments se bloquean (usar rectificativas); **se inicia una cadena** que queda como libro inmutable.
  - **Al desactivar**: si la empresa está legalmente obligada a VeriFactu, desactivar = **incumplimiento** (facturas emitidas sin registro/remisión); la cadena se congela (reactivar continúa la misma cadena — §5, no empieza otra); los registros pendientes siguen remitiéndose (§8); las facturas emitidas durante el período activo siguen anulables con RegistroAnulación (§6 — el libro no desaparece).
  - El aviso de desactivación muestra además el nº de registros pendientes de envío si los hay.
- **`activation_date` (semántica CONFIRMADA)**: las facturas EMITIDAS (FechaExpedicion) desde esa fecha generan registro VeriFactu; las anteriores son legacy pre-VeriFactu — sin registro, rectificables como "rectificada externa" (§6). Con el bloqueo de fecha al emitir (§4), FechaExpedicion ≈ momento del submit.
- **Limpieza**: `before_uninstall` elimina los Custom Fields del tab y sus child tables (doc 12 §12) — crítico por tocar un doctype del core en contexto multi-cliente.
- **UX**: `doctype_js` de Company para mostrar/ocultar secciones según `enabled` (patrón de la referencia, `company.js`); si el tab crece con futuras funcionalidades, evaluar tab-per-funcionalidad como alternativa.

El catálogo `SC Verifactu Invoice Type` queda SOLO como catálogo de códigos/semántica (F1, F2, F3, R1–R5: código, etiqueta, `es_simplificada`, `tipo_rectificativa`) — SIN series globales; las series viven por company en el mapeo. Uso al submit: tipo de la factura (§2.3) → serie de SU company → `make_autoname` (§4).

#### 2.2 `SC Verifactu Billing Record` (ledger — doctype normal, NO child table)

Cambio clave sobre la referencia: los registros de facturación pasan de child table de Sales Invoice a **doctype independiente**. Motivos: (1) el libro de registros debe sobrevivir a cualquier operación sobre la factura (integridad legal de la cadena), (2) las queries de subsanación/orden de cadena operan sobre el ledger sin cargar facturas, (3) permisos propios.

Campos:
- `company`, `sales_invoice` (Link), `tipo_registro` (`RegistroAlta` | `RegistroAnulacion`), `tipo_factura` (código F*/R*), `chain_index` (int — posición en la cadena de la empresa, para auditoría y orden de subsanación).
- `record_json` (JSON — **fuente de verdad** del registro AEAT, exactamente lo remitido), `huella` (Data), `previous_huella` (Data, `""` si es el primero).
- Estado (§3): `status`, `response` (Link → SC AEAT Response), `response_error_code`, `response_error_msg`, `subsanable` (derivado).
- Inmutabilidad: tras `Correcto` el registro queda congelado (solo el procesador de respuestas puede transicionar estados; `validate` del controller lo garantiza). La subsanación NUNCA edita un registro: crea uno nuevo con flag `Subsanacion`.

#### 2.3 Custom Fields en Sales Invoice (vía `create_custom_fields` en `after_install`, con limpieza en `before_uninstall` — doc 12 §11–12)

Mínimo conjunto (naming corto `sc_verifactu_`, no los nombres verbosos de la referencia):
- `sc_verifactu_invoice_type` (Link → SC Verifactu Invoice Type, default F1, reqd si la company está activa).
- `sc_verifactu_mode` (Data — snapshot inmutable del modo operativo al emitir: `Verifactu` / `Verifactu en pruebas` / `Sin SIF`; como la referencia, se congela por factura para detectar cambios de modo).
- `sc_verifactu_status` (Select/Data — estado denormalizado para list view y filtros; lo actualiza el procesador de respuestas).
- Rectificada externa (cierra gap): `sc_verifactu_external_rectified_nif`, `sc_verifactu_external_rectified_number`, `sc_verifactu_external_rectified_date` — para rectificar facturas emitidas fuera del sistema.
- Escape hatches fiscales (los usa 07 si el cálculo automático no aplica): `sc_verifactu_clave_regimen` (Select, default "01 — General"), `sc_verifactu_exempt_cause` (Select L10).

### 3. Máquina de estados

Estados del **registro** (billing record): `PendienteEnvio` → `Correcto` | `AceptadoConErrores` | `Incorrecto`. Transiciones solo por el procesador de respuestas (o creación → PendienteEnvio). Sin ediciones manuales.

Estados de la **factura** (denormalizados, derivados del último registro): mapa registro×estado → estado de factura (patrón `VERIFACTU_INVOICE_STATUS_MAPPER` de la referencia: Alta Aceptada, Alta Con Errores, Anulada, Pendiente Envío, etc.).

Estrategia por código de error AEAT (mapa en código, extendible):
- **Reintento automático** → nuevo registro con flag `RechazoPrevio`.
- **Subsanación automática** (p.ej. timestamp fuera de rango) → regenerar registro corregido sin intervención.
- **Subsanación manual** → notificar roles configurados + factura visible en report "Facturas subsanables" + dialog con campos a corregir (patrón `VERIFACTU_ERROR_FIELDS` de la referencia: por código de error, qué campos pedir y con qué defaults).
- **Desconocido** → `log_error` + notificación (nunc cras: contactar desarrollador).

### 4. Flujo de emisión (Alta)

> **Verificado contra el código fuente de Frappe/ERPNext v16 del bench** (evidencia citada en cada paso). No se usa `override_doctype_class` en ningún punto. Garantía estructural: con `doc_events`, el método del core SIEMPRE corre antes que nuestros handlers (`Document.hook.compose`, `frappe/model/document.py:1633-1647`), por lo que es imposible saltarse la contabilización del core — defecto real de la referencia (ver tabla de deudas, fila "on_submit sin super()").

1. **Naming sin quemar serie**: el core `SalesInvoice` NO define `autoname` (verificado), así que el mixin `extend_doctype_class` **añade** el método `autoname` — adición pura, la forma más limpia de extend — que asigna nombre temporal a los borradores: **`draft_series` de la company** (§2.1) vía `make_autoname` si la company está configurada (nombres secuenciales, ordenables, reconocibles); fallback `BORRADOR-{ts}-{hash}` si no lo está (companies no registradas en settings). En el naming, `set_new_name` invoca `doc.run_method("autoname")` (`frappe/model/naming.py:189`) antes de las naming options. Ningún número de serie fiscal se consume hasta la emisión real (la serie de borradores es un contador aparte, sin valor legal — los huecos en ella son irrelevantes). **Decisión**: aplicar a TODAS las companies (uniforme, igual que la referencia — su issue #21), para tener un único código probado y evitar dobles comportamientos; el renombrado solo consume contador de `tabSeries` fiscal en el submit.
2. **`validate`** (doc_event, tras el validate del core): early-exits baratos si la company no tiene VeriFactu (doc 12 §2). Validaciones: amendments bloqueados (con remedio: usar rectificativa), impuesto o causa de exención presente, coherencia tipo F2/R5 ↔ `is_pos`, **NIF emisor y NIF cliente válidos — no solo presentes como en la referencia — vía el verificador transversal ([14-verificador-nif.md](14-verificador-nif.md))**, reglas de rectificativa (§6).
3. **`before_submit`** (doc_event; corre tras el `before_submit` del core — que solo hace `add_remarks`, `sales_invoice.py:466-467` — y ANTES de `db_update` y del `on_submit` del core; orden verificado en `document.py:1413-1415` + `_save`): dentro del **lock por empresa** (§12, cubre naming+cadena de una vez):
   - Checks de modo operativo (certificado y NIF configurados, mensaje con remedio), snapshot de modo, bloqueo de fecha si procede (duda abierta).
   - **Renombrado a la serie final** (verificada la mecánica en `rename_doc.py:108-232`): **guard** — renombrar SOLO si `doc.name.startswith("BORRADOR-")` (protege imports/migraciones con números explícitos: `flags.in_import` preserva nombres en `naming.py:158`, y la referencia renombraba incondicionalmente = números históricos clobberados). Llamada quirúrgica: `frappe.rename_doc(doctype="Sales Invoice", old=doc.name, new=make_autoname(...), force=True, show_alert=False, rebuild_search=False)` — los defaults son trampa (ver coste). Tras el retorno: `doc.name = <nuevo>` + **fix obligatorio de children**: reasignar `child.parent = doc.name` en las child tables en memoria — `rename_doc` actualiza el `parent` de las filas en DB (`update_child_docs`), pero nuestro doc en memoria conserva los `parent` stale; después, `update_child_table` borra por `parent == self.name` y re-inserta cada fila con su propio campo `parent` (`document.py:674,686-688`) → sin el fix, las filas quedan huérfanas bajo el BORRADOR (el "child-table reference issue" de la referencia). `validate_rename` aporta `SELECT ... FOR UPDATE` sobre el nombre destino (`rename_doc.py:351`) — anti-duplicado extra gratis.
   - **Coste del renombrado (verificado)** — qué hace `rename_doc` por submit:
     - Barato (indexado ✓): UPDATE fila padre (PK) + `parent` de children; sweep GL Entry (`voucher_no` indexado) y Payment Ledger Entry (`voucher_no` indexado); `__UserSettings` (tabla chica).
     - **Caro (SIN índice ✗, tablas potencialmente enormes)**: `Version.docname`, `File.attached_to_name`, `Communication.reference_name`, `Stock Ledger Entry.voucher_no` (solo `voucher_type` indexado, sin compuesto) — UPDATEs que matchean 0 filas (es un draft) pero pagan la evaluación del WHERE = scan.
     - **Defaults trampa de la firma** (`rename_doc.py:108-119`): `rebuild_search=True` encola `rebuild_for_doctype` de búsqueda global POR CADA submit (job pesado en sites con volumen — la referencia lo sufre sin saberlo); `show_alert=True` mete un msgprint de rename en cada submit. Ambos se neutralizan con los parámetros de la llamada quirúrgica.
     - **Decisión de performance** (implementación concreta, verificada): añadir los índices compuestos vía `frappe.db.add_index` desde `after_migrate` del app (hook de install.py — NO SQL crudo: es la API del framework, idempotente por diseño con `has_index` + `ADD INDEX IF NOT EXISTS`, `mariadb/database.py:419-436`; se ejecuta en cada migrate → auto-reparable). Índices (columna selectiva primero; orden de columnas cubre el sweep `WHERE type=? AND name=?` y también lookups por nombre solo):
       - `Version`: `(docname, ref_doctype)` — sweep de `rename_versions`
       - `File`: `(attached_to_name, attached_to_doctype)` — sweep de `update_attachments`
       - `Communication`: `(reference_name, reference_type)` — sweep de `rename_dynamic_links`
       - `Stock Ledger Entry`: `(voucher_no, voucher_type)` — sweep de `rename_dynamic_links` (sigue el precedente de `Payment Ledger Entry` (`voucher_no, voucher_type`), ERPNext ya añadió `(voucher_type, voucher_no)` para GL Entry en `gl_entry.py:on_doctype_update()` — GL queda cubierto por el core, no lo tocamos)
       - DDL generado (referencia): `ALTER TABLE `tabVersion` ADD INDEX IF NOT EXISTS `docname_ref_doctype_index`(`docname`, `ref_doctype`)` — etc.
       - **Tradeoff documentado**: cada índice añade coste de escritura a tablas calientes de INSERT (Version: cada save del sistema; Communication: cada email/comentario; SLE: cada movimiento de stock) — el coste B-tree por insert es marginal y el beneficio (scan→lookup en cada submit de factura) lo justifica; presupuestar medición con datos voluminosos.
       - Alternativa descartada: rename "quirúrgico" propio que salte los sweeps de GL/SLE/Payment (garantidamente vacíos en drafts) — reimplementar maquinaria del framework es frágil (otras apps pueden linkear drafts); se prefiere el camino del framework + índices. **Presupuesto**: test de submit con datos voluminosos en el site de pruebas; si con índices el rename sigue doliendo, revisitar con datos.
   - **Post-renombrado UX (resuelto nativo)**: `rename_doc` publica `doc_rename` con `after_commit=True` (`rename_doc.py:224-230`) y el Desk escucha y **redirige el form abierto al nombre nuevo** (`form.js:338-343`) — cero JS nuestro para el redirect. Pendiente solo estilado de BORRADOR-* en list views (tarea).
   - **Caveat de integraciones**: el nombre de un draft NO es estable a través del submit (cambia BORRADOR→serie). Integradores externos no deben retener el nombre del draft entre llamadas: o hacen create+submit en la misma request (reciben el nombre final), o trackean por referencia propia. Documentar en README/guía de integración.
   - Tras el renombrado, `db_update` del submit escribe padre e hijos ya bajo el nombre final, y el `on_submit` del core crea stock ledger y GL entries (`sales_invoice.py:503,510`) con nombre final: cero cirugía de links posterior.
   - **Propiedad transaccional** (verificada): todo el submit es UNA transacción — `make_autoname` incrementa `tabSeries` con `SELECT ... FOR UPDATE` + UPDATE atómico dentro de la misma txn (`naming.py` `getseries`), y el renombrado también; si el submit falla en cualquier punto posterior (p.ej. límite de autorización en el `on_submit` del core), el rollback devuelve el contador y el nombre: el número no se pierde. Nota: el mecanismo nativo `revert_series_if_last` (`naming.py:462-478`, llamado desde `delete_doc.py:241`) solo devuelve el número si el borrador borrado era el ÚLTIMO de la serie — no cubre el caso "borrador 42 abandonado tras emitir la 43+" → por eso el nombre temporal es necesario, no opcional.
4. **`on_submit`** (doc_event; corre DESPUÉS del `on_submit` del core — GL/stock ya existentes con nombre final): crear el registro Alta (§5) en estado `PendienteEnvio`; si `remission_mode = Inmediata` → `frappe.enqueue(..., enqueue_after_commit=True)` del envío (nunca antes del commit del submit).
5. **`before_cancel`** (doc_event): exige estado `Alta Aceptada` → genera el RegistroAnulación encadenado (§6).

**Alternativas descartadas al renombrado** (constancia de diseño):

| Alternativa | Por qué no |
|---|---|
| Naming nativo en borrador (no hacer nada) | Huecos por borradores abandonados: `revert_series_if_last` solo sana el caso "era el último número" (verificado). Numeración correlativa VeriFactu comprometida. |
| Prohibir borradores | Rompe el flujo estándar de Desk (guardar → revisar → submit) y los flujos de aprobación. |
| Rellenar huecos (reusar el número libre más bajo) | Identidad de factura ambigua si un borrador con número se mostró/envió y luego se borra; carrera de concurrencia sobre el hueco. |
| Doctype separado de "borrador" → factura al emitir | Re-arquitectura del flujo de ventas (SO/DN/timesheets/auto-repeat → SI); demasiado invasivo para el beneficio. |

**Nota POS**: `POS Invoice` se crea y submita sin estado borrador — para tickets simplificados (F2) vía POS la consecutividad sale natural, sin renombrado. El flujo F2 por `Sales Invoice` normal (POS manual en SI) sigue el camino §4 con tipo F2 y validación `is_pos`.

**Análisis funcional del "número al emitir"** (juicio de producto, verificado contra práctica del mercado):

- El número de factura es un atributo del **acto de emisión**, no del borrador: en España una factura existe cuando se expide; un borrador no es factura. La numeración nativa de ERPNext (número en borrador) es la anomalía — queja recurrente de contables españoles ("¿por qué mi borrador quemó el 0042?").
- Es el **patrón estándar del software contable serio**: Odoo (el ERP más usado en España junto con SAP) muestra literalmente `/` como nombre de factura en borrador y asigna el número al post; SAP/Business Central/A3 asignan al contabilizar; OCA construyó `l10n_es_sequence` (secuencias anti-huecos) para el mismo problema en TicketBAI/SII. VeriFactu fuerza lo que el producto debía hacer de todos modos para el mercado español.
- **Costes funcionales aceptados + mitigaciones**: borradores no referenciables por número (mitigable con formato de nombre ordenable; el "¿qué número va a tener?" no tiene respuesta honesta hasta emitir — no mostrar números predichos); imprimir borrador como proforma (herramienta equivocada: Quotation es el medio; opcional print de borrador rotulado "NO ES FACTURA"); coste de cambio de hábito para clientes existentes (gestión de cambio, release note). La referencia declaró `doctype_list_js` para maquillar los BORRADOR en listas pero el archivo no existe — deuda UX sin cerrar que vuestro diseño debe completar (tarea).
- **Tradeoff abierto de producto (decisión del dueño del producto)**: aplicar uniforme a TODAS las companies (recomendado: un solo código probado, un solo comportamiento, sin sorpresas al activar VeriFactu a mitad de año) vs. solo companies con VeriFactu (menor impacto en clientes que no lo necesitan, a costa de dos comportamientos y soporte dual).

### 5. Encadenamiento y huella (algoritmo congelado)

La cadena es **por empresa** (un SIF por company+NOI). El último registro existente (Alta o Anulación) provee la huella previa; el primero usa `Huella=""` y `PrimerRegistro="S"`. **La cadena sobrevive a desactivaciones**: reactivar una company continúa la cadena existente (el ledger es el mismo libro — `PrimerRegistro="S"` solo ocurre una vez en la vida del SIF).

Canonicalización (verificada en la referencia contra el entorno de pruebas AEAT; **congelar con tests de vector** y contrastar con ejemplos oficiales):

- **Alta**: SHA-256 sobre `IDEmisorFactura=…&NumSerieFactura=…&FechaExpedicionFactura=…&TipoFactura=…&CuotaTotal=…&ImporteTotal=…&Huella={huella_anterior}&FechaHoraHusoGenRegistro=…` → hex **uppercase**.
- **Anulación**: SHA-256 sobre `IDEmisorFacturaAnulada=…&NumSerieFacturaAnulada=…&FechaExpedicionFacturaAnulada=…&Huella={huella_anterior}&FechaHoraHusoGenRegistro=…`.
- `FechaHoraHusoGenRegistro`: ISO 8601 con offset con dos puntos (`+01:00`), timezone Europe/Madrid. `FechaExpedicionFactura`: `dd-mm-aaaa`. `TipoHuella = "01"`, `IDVersion = "1.0"`.
- Mapeos de importes: `ImporteTotal = rounded_total`, `CuotaTotal = total_taxes_and_charges`.

Generación serializada por empresa (§12) → asignar `chain_index` → persistir `record_json` + `huella` + `previous_huella`.

### 6. Rectificativas y anulaciones

- **Rectificativa** = Sales Invoice `return_against` (credit/debit note) o tipo R*. Validaciones (doc_event validate): la original debe estar en estado `Alta Aceptada`; no puede coexistir otra rectificativa pendiente/errónea sobre la misma original. `TipoRectificativa` (S sustitución / I por diferencias) derivado del tipo R* (`get_tipo_rectificativa` de la referencia).
- **Rectificativa de factura externa** (gap): si `return_against` vacío y hay custom fields de rectificada externa (NIF emisor + número + fecha), se reporta en `FacturasRectificadas` sin link interno.
- **Anulación** = cancelación de la Sales Invoice (`before_cancel` doc_event): exige estado `Alta Aceptada` de la original → genera RegistroAnulación encadenado. **La compuerta de anulación es el snapshot de modo de la FACTURA (`sc_verifactu_mode`), no el modo actual de la company**: una factura emitida en modo VeriFactu debe poder anularse con su RegistroAnulación aunque la company esté desactivada después — el libro es historia legal inmutable y la anulación de una factura real siempre requiere registro. (Defecto v1: `_check_proper_operational_mode` exigía modo factura == modo company actual → **imposibilitaba anular facturas del período VeriFactu tras desactivar** — ver tabla de deudas.) La anulación del alta pendiente (rechazo) no cancela la factura: se corrige por subsanación.

### 7. Desglose fiscal — contrato con 07 (impuestos) y 09 (retenciones)

El `Desglose.DetalleDesglose` se construye a partir de un **adaptador puro y testeable** que NO depende de internals de ERPNext. La referencia usaba `get_itemised_tax_breakup_data` + convención de nombre de tax template `"IVA - 21"`; la nueva app define en su lugar un contrato con el módulo de impuestos (spec 07):

```
get_spain_tax_breakup(invoice) -> list[DetallleLine]:
    # impuesto: IVA (01) | IPS (02) | IGIC (03) | RENTA? no — recargos...
    # tipo_impositivo, base_imponible, cuota
    # calificacion_operacion: S1 | S2 | S3 (sujeta y no exenta / exenta / no sujeta)
    # clave_regimen: L8A (01 general, 02 export, 03 intracomunitaria, …)
    # causa_exenta: L10 (cuando S2)
    # destinatarios + tipo_operacion (N1..N4, S1..S3) para escenarios especiales
```

- El mapeo Tax Template → semántica fiscal española (claves de régimen, causas de exención, inversiones del sujeto pasivo) es propiedad del módulo **07**, no de VeriFactu. VeriFactu consume el contrato y valida (tasa ∈ {21,10,4,0}, coherencia tasa-descripción, multi-tasa OK, IRPF presente en la factura NO va en DetalleDesglose pero afecta ImporteTotal — el contrato lo expone para verificación).
- Multi-fila de impuestos soportada de origen (agregación por tasa con `Decimal` + `ROUND_HALF_UP`, patrón de la referencia).
- Los escape hatches (custom fields clave régimen / causa exenta) permiten corregir casos especiales sin tocar 07.
- **Destinatarios**: `NombreRazon` = `customer_name` (razón social — modelo de nombres de [14](14-verificador-nif.md); la referencia ya lo hacía así). NIF del cliente via verificador 14 (§compuertas).

### 8. Remisión a la AEAT (outbox)

- El ledger con `PendienteEnvio` es el outbox. El **manager compartido** (13) drena por empresa: lote ≤ `batch_limit` (máx. AEAT 1000), `Cabecera` (ObligadoEmision: NombreRazon + NIF de la company) + registros ordenados por `chain_index`.
- **El drenaje no depende de `sc_verifactu_enabled`**: el scheduler procesa toda company con registros pendientes — así lo pendiente al desactivar sigue remitiéndose (remisión consecutiva) y las **anulaciones post-desactivación** (§6) llegan a la AEAT. El flag `enabled` solo gatea la generación de NUEVOS Altas.
- **Alerta de outbox estancado**: job diario — registros `PendienteEnvio` con más de N horas (configurable, default 24h) → incidencia por los dos canales (§9). Con remisión diferida la ventana legal es corta: un outbox parado es una incidencia, no un estado silencioso.
- Modalidad `Inmediata`: `frappe.enqueue` al submit. Modalidad `Diferida`: scheduler cron cada minuto.
- Rate-limit por empresa (`timeout_seconds`) con timestamps en Europe/Madrid (patrón `_check_flow_time` de la referencia). **Además, respetar el tiempo de espera que la propia AEAT puede devolver entre envíos (>60s — señalización del protocolo documentada en el roadmap de OCA `l10n_es_verifactu_oca`)**: el manager de la capa 13 lo incorpora al rate-limit de la company antes del siguiente lote.
- **Aislamiento por empresa**: cada envío va en su propia transacción/try; un error se registra con `frappe.log_error` y se continúa con la siguiente empresa (NUNCA `frappe.throw` en el loop — gap de la referencia).
- Reintentos: backoff simple en el manager (13), con tope de intentos y notificación si se agota.
- SOAP Fault → `RespuestaLinea` sintética por registro (patrón de la referencia) para unificar el procesamiento.

### 9. Procesamiento de respuestas y subsanación

- La respuesta cruda se persiste en `SC AEAT Response` (+ `SC AEAT Response Line`, capa 13). El procesador de VeriFactu recorre las líneas por `RefExterna` (= nombre del billing record) y transiciona estados — **incluyendo líneas de Anulación** (gap de la referencia).
- Actualiza el estado denormalizado de la factura, aplica la estrategia por código de error (§3), y notifica las **incidencias** por los DOS canales — roles → Notification Log (in-app) **y** `sc_incidents_email` de la company (email externo, p.ej. asesor fiscal, vía `frappe.sendmail`). Catálogo de eventos de incidencia: rechazo AEAT con subsanación (manual o automática fallida), reintento agotado tras backoff, fallo persistente de conexión con la AEAT, outbox estancado (§8), y caducidad de certificado (la capa 13, ver su spec). Publica `frappe.publish_realtime` para refrescar la form (el listener JS es aditivo, no crítico).
- Subsanación en orden: si `mandatory_in_order_cure`, solo puede subsanarse la factura cuyo último registro sea el más antiguo pendiente/erróneo del SIF (reimplementar con ORM/frappe.qb — gap de SQL crudo de la referencia).
- Report "Facturas subsanables" + dialog por código de error (campos a corregir con defaults) → `subsanar` (whitelisted, con check de permisos explícito por company — doc 12 §18) → nuevo registro encadenado con flags `Subsanacion`/`RechazoPrevio`/`SinRegistroPrevio` según corresponda.

### 10. Consulta AEAT (`SC Verifactu Aeat Query`)

Doctype para lanzar `ConsultaFactuSistemaFacturacion`: selector explícito de company (+ su credencial), filtros (NIF, número, fechas), resultados en child table. Corrige el gap de `consultar()` (sin `.pop()` implícito).

### 11. QR e impresión

- `jinja.methods`: `get_verifactu_qr_code(doc)` (SVG del QR con la URL `ValidarQR` — URL de test/producción según settings de la company), `get_verifactu_breakup(doc)` (desglose IVA para la plantilla), expuestos para el Print Format.
- Print Format de factura española con QR + texto legal; fijado como `default_print_format` de Sales Invoice vía `frappe.make_property_setter` en `after_install` (doc 12 §13), no hardcode.

### 12. Concurrencia de la cadena

La secuencia leer-último→calcular-huella→insertar **y el renombrado/numeración** deben serializarse por empresa: el lock (Redis/`frappe.utils.locks`, clave `verifactu:chain:{company}`) se toma en `before_submit` y cubre `make_autoname` + lectura del último registro + creación del nuevo — así el número de factura y la posición en la cadena se asignan en el mismo orden. Nota: el contador `tabSeries` ya se protege a nivel DB (`getseries` usa `SELECT ... FOR UPDATE`, `naming.py`) — el lock nuestro añade atomicidad numeración↔cadena, no reemplaza al de DB. A falta de lock, retry corto. La referencia ya filtra "solo registros con JSON persistido" para evitar lecturas de transacciones en curso — mantener. Tests específicos: dos submits simultáneos (números y cadenas consecutivos sin duplicados) y rollback de submit fallido tras renombrado (el número vuelve a liberarse).

### 13. Cumplimiento del patrón 12 (resumen)

| Patrón (doc 12) | Aplicación |
|---|---|
| `regional_overrides` | No aplica a VeriFactu (no hay puntos `@allow_regional` para remisión); se usará en 07 |
| `doc_events` | validate / before_submit (incl. renombrado a serie final + fix de children) / on_submit / before_cancel de Sales Invoice |
| `extend_doctype_class` | Mixin Sales Invoice que SOLO **añade** `autoname` (método inexistente en el core — verificado); composición: mixins primero en MRO, coexistente entre apps (`base_document.py:179-208`) |
| `override_doctype_class` | **No se usa** (la referencia lo usaba — corregido) |
| Custom Fields en código | §2.3 vía `create_custom_fields` + limpieza en uninstall |
| Single por bloque | SC Verifactu Settings + child por empresa |
| Submódulo por funcionalidad | `verifactu/` + capa transversal `aeat/` (spec 13) |
| `scheduler_events` | Cron por minuto (drenaje diferido) + daily (expiración de certificados, en 13) |
| `jinja.methods` | QR + desglose (§11) |
| Property Setter | default_print_format (§11) |
| Permisos explícitos en whitelisted | `subsanar`, retry, query — con company check (§9, §10) |
| No SQL crudo | `es_subsanable` reescrito con ORM/qb |
| Sin `frappe.db.commit` explícito | Manager respeta ciclo transaccional por job |
| `ignore_links_on_delete` | Responses; billing records (para no bloquear borrados legítimos de facturas) |
| `company_data_to_be_ignored` | Settings + credenciales (no borrar config en resets de transacciones) |
| Tests desde el primer commit | §14 |

### 14. Tests

- **Huella/canonicalización**: vectores unitarios (construir casos con valores conocidos; contrastar con ejemplos oficiales de la Orden — tarea).
- **Data adapter** (funciones puras): mapeos, desglose multi-tasa/multi-impuesto, exentas, rectificativas internas/externas.
- **State machine**: con fixtures de `aeat_response_examples/` de la referencia (Alta, Anulación, Faults sintéticos).
- **Workflow de integración**: emisión → remisión (cliente mockeado) → respuesta correcta/errónea → subsanación → anulación. En site de pruebas del bench.
- **Concurrencia de cadena**: submits paralelos por empresa.

### 15. Avisos UX y legales

- **Banner modo pruebas en facturas** (`set_intro` en el form de Sales Invoice, vía `doctype_js`): si la company está en "VeriFactu en pruebas" (o la factura submitada tiene snapshot `Verifactu en pruebas`), banner visible tipo: *"⚠ Modo VeriFactu EN PRUEBAS — las remisiones van al entorno de pruebas de la AEAT y NO tienen validez fiscal."*. Patrón set_intro: limpiar primero (`frm.set_intro("")`), refrescar en `refresh` + cambio de `company`. El mismo banner (más discreto) en el form de Company cuando `test_mode` está activo.
- **Avisos legales de activación/desactivación** (§2.1): confirm dialogs con las consecuencias legales al togglear `sc_verifactu_enabled` — la desactivación avisa del incumplimiento si hay obligación, de que la cadena se congela (reactivar continúa la misma), de los registros pendientes que seguirán drenándose, y de que las anulaciones del período siguen funcionando.
- **Estilado de borradores en list views**: BORRADOR-* diferenciado visualmente (el nombre temporal no es una factura) — tarea de UI con `doctype_list_js`.
- **Archivo JS**: `verifactu` registra `doctype_js` para Sales Invoice y Company (`spain_compliance/verifactu/public/js/`) — un solo archivo por doctype con todos los behaviors (banner, dialogs, sync tipo↔serie del §4).
- **Caducidad de certificados** (la posee la capa 13): aviso diario a 30/7/1 días del fin de vigencia por roles (Notification Log) + `sc_incidents_email` de la company; indicador de días-restantes en el list view de `SC AEAT Credential` y en la sección de credenciales del tab de Company. Un certificado caducado = remisiones caen → mejor avisarlo ANTES (la incidencia post-mortem ya llega sola).

## Dudas abiertas

**Resueltas por diseño:**
- Certificado digital: gestión multi-empresa en `SC AEAT Credential` compartida con SII/eFactura (13); p12 + password (Password field), extracción a PEM en private/files; seguimiento de expiración con notificación.
- Rectificativas/anulaciones en la cadena: Anulaciones encadenadas como Altas; subsanación crea registro nuevo, nunca edita.
- Relación con eFactura: comparten capa de certificado (13); la firma XAdES de Facturae es de otro estándar (propio del spec 06).

**Pendientes de decisión (negocio/usuario):**
1. **Modalidad sin remisión (conservación local)**: ¿v1 o fase posterior? Recomendación: modelo de datos la soporta desde el día 1, implementación en fase posterior (v1: remisión inmediata + diferida + modo pruebas).
2. **Bloqueo de fecha de emisión**: la referencia fuerza `posting_date = now()` al submit en modo VeriFactu (la factura no puede fecharse atrás). ¿Mantener? Recomendación: mantener (coherente con "registro en el momento de la emisión" de la Orden).
3. **Series por tipo de factura** (F1/F2/R* con numeraciones separadas): la referencia lo hace vía `SC Verifactu Invoice Type`. ¿Mantener?
4. **Datos de certificación SIF** (NombreRazon, NIF del productor, IdSistema, Version por release): necesarios para producción; en desarrollo valen placeholders en settings con test que impida exportar con placeholders.

**Pendientes de verificación normativa (implementación):**
- Perfil de firma exigido (¿TLS mutua suficiente o XAdES del registro? — la referencia funciona con TLS mutua contra el entorno de pruebas; contrastar con la Orden/WSDL).
- Catálogos completos: tipos F1–F3/R1–R5 (la referencia solo tiene F1/F2/R4/R5), claves de régimen L8A, causas de exención L10, códigos de error AEAT.
- Formato exacto del contenido del QR (la referencia usa `nif,fecha,importe,numserie` — validar con la Orden).

## Tareas para agentes

- [ ] Crear configuración del §2: `SC Settings` (Single, sección VeriFactu: identidad SIF + endpoints) y tab "Spain Compliance" en Company vía `create_custom_fields` (sección VeriFactu + childs `SC Verifactu Series`/`SC Verifactu Notification Role` + validaciones en doc_event de Company: biyección series↔tipo, no compartir serie entre companies, draft_series sin colisión, NIF único, activation_date, NOI). Catálogo `SC Verifactu Invoice Type` COMPLETO (F1/F2/F3/R1–R5, sin series globales).
- [ ] Implementar capa 13 mínima usada por VeriFactu (credential, response, client, manager) — ver spec 13.
- [ ] Implementar data adapter puro + huella congelada con tests de vector.
- [ ] Implementar mixin (solo `autoname`) + doc_events (§4) con tests de: children consistentes tras renombrado, core genera GL con nombre final, rollback de submit fallido libera el número de serie.
- [ ] Sincronizar tipo de factura → `naming_series` de la SI (JS + helper server), con la serie por tipo definida en el fixture de Invoice Type.
- [ ] Implementar outbox + scheduler + aislamiento por empresa (§8).
- [ ] Implementar procesador de respuestas + state machine + subsanación ORM (§9).
- [ ] Implementar QR + jinja methods + print format + property setter (§11).
- [ ] Implementar consulta AEAT (§10).
- [ ] Tests de integración con cliente mockeado + fixtures de respuestas.
- [ ] Verificar firma/catálogos/QR contra Orden HAC/1177/2024 y WSDL oficial antes de pruebas reales.

## Dependencias con otros specs

- **[13-capa-aeat.md](13-capa-aeat.md)** — capa compartida AEAT (credenciales, cliente SOAP, responses, outbox). Se construye junto con este módulo.
- **[07-impuestos-defecto.md](07-impuestos-defecto.md)** — contrato `get_spain_tax_breakup` (§7): el mapeo Tax Template → semántica fiscal es propiedad de 07.
- **[09-retenciones.md](09-retenciones.md)** — IRPF afecta ImporteTotal y flujos de rectificativa; el contrato de desglose lo expone.
- **[05-sii.md](05-sii.md)** — comparte capa 13 (certificado, cliente, outbox). Quien está en SII no usa VeriFactu: los settings por empresa deben dejarlo claro en UI.
