# 13. Capa AEAT Compartida (VeriFactu + SII + futuro eFactura)

[← Volver al índice](00-maestro.md)

> Especificación transversal creada al detallar VeriFactu (04): la integración con la AEAT comparte infraestructura entre módulos (SOAP + certificado + registro de respuestas + reintentos). Este fichero la define para que 05 (SII) construya sobre ella y NO duplique.

## Objetivo

Una única capa de integración con los servicios web de la AEAT, reutilizada por VeriFactu (SOAP `SistemaFacturacion`) y SII (SOAP de suministro inmediato), y que aporta el almacenamiento de certificados que también reutilizará eFactura (06) para su firma XAdES.

## Contexto

- Ambos servicios son SOAP sobre HTTPS con **autenticación por certificado digital (TLS mutua)** y respuestas estructuradas en líneas por registro (con CSV de acuse, estados por línea y códigos de error).
- Ambos necesitan: gestión de certificado por empresa (multi-tenant: varias companies por site), entornos de pruebas/producción, lotes con límites, reintentos, y registro auditable de cada respuesta.
- La referencia (`testsc/apps/spanish_compliance/verifactu/aeat_lib/`) ya resuelve el patrón para VeriFactu; se extrae y generaliza.

## Alcance

- Gestión de credenciales (certificados) por empresa con expiración y rotación.
- Cliente SOAP (factoría zeep) con registro de endpoints por servicio y entorno.
- Registro auditable de respuestas AEAT (crudo + parseado por líneas).
- Outbox/reintentos con aislamiento por empresa y rate-limit.
- Firma (perfil a verificar contra la Orden HAC/1177/2024; si se exige firma XAdES del registro, vive aquí).
- Utilidades: timestamps Europe/Madrid (ISO 8601 con offset), permisos por empresa, notificaciones a roles.

Fuera de alcance: mapeos de negocio (los aporta cada funcionalidad: data adapter de VeriFactu, mappers SII), settings propios de cada feature, UI de negocio.

## Diseño técnico propuesto

### 1. Módulo y doctypes

```
spain_compliance/aeat/
├── doctype/
│   ├── sc_aeat_credential/
│   ├── sc_aeat_response/
│   └── sc_aeat_response_line/
├── client.py        # AEATClient: factoría SOAP (zeep, TLS mutua)
├── signer.py         # firma del contenido remitido (perfil a verificar)
├── manager.py        # AEATOutboxManager: drenaje por empresa + reintentos
└── utils.py          # huso horario, permisos, notificaciones
```

### 2. `SC AEAT Credential`

- Campos: `company` (Link), `purpose` (Select: `VeriFactu` | `SII` — un certificado puede servir para ambos con dos filas o una fila multi-propósito; recomendación: una fila por (company, purpose) para trazabilidad, aunque apunten al mismo p12), `cert_file` (Attach → private/files), `cert_password` (Password, cifrado por Frappe), metadatos de vigencia (`valid_from`, `valid_until` — parseados del certificado al guardar), `enabled`.
- Extracción p12→PEM al validar (patrón de la referencia: `cryptography.load_pkcs12` → PEM en `private/files`, nombres por (company, purpose)); limpieza al desactivar/cambiar.
- Scheduler daily: **aviso de expiración próxima a 30/7/1 días** por los canales de la company — roles → Notification Log **y** `sc_incidents_email` (email externo, ver 04 §2.1 — campo transversal de la Company). Indicador de días-restantes en el list view de la credencial y en el tab de Company.
- Seguridad: password cifrado (Password field); los PEM en `private/files` son accesibles solo server-side. Tradeoff documentado (la referencia borra el password tras extraer PEM; preferimos conservarlo para poder re-extraer/rotar sin re-subir el archivo).

### 3. `SC AEAT Response` + `SC AEAT Response Line`

- Response: `service` (`VeriFactu` | `SII`), `company`, `request_payload` (JSON — qué se envió), `raw_response` (JSON), `estado_envio`, `csv` (acuse AEAT), `fault_code`/`fault_message` (si aplica).
- Response Line: `response` (parent), `ref_externa` (id de nuestro registro), `tipo_operacion`, `id_factura` (JSON: emisor/numero/fecha), `estado_registro`, `codigo_error`, `descripcion_error`, `registro_duplicado`, flags subsanación.
- Es la normalización del patrón de la referencia (`SC Verifactu AEAT Response`/`Line Response`) generalizada por servicio. Los procesadores de cada funcionalidad (verifactu/sii) consumen las líneas por `ref_externa`.
- List views paginadas; NUNCA fetch-all (gap de rendimiento de la referencia).

### 4. Cliente SOAP (`client.py`)

- Factoría por servicio+entorno: registro declarativo de WSDL/servicio/puertos (VeriFactu: WSDL único con puertos `SistemaVerifactu`/`SistemaVerifactuPruebas`; SII: endpoints propios por entorno — los define 05).
- TLS mutua con la PEM de la credencial de la empresa; timeouts configurables.
- SOAP Fault → conversión a líneas sintéticas de respuesta (patrón de la referencia) para que los procesadores trabajen un solo formato.
- **Cero lógica de negocio** en el cliente: recibe payload estructurado, devuelve dict serializable.

### 5. Outbox y reintentos (`manager.py`)

- Interfaz por funcionalidad ("driver"): `get_pending(company) -> records`, `build_payload(company, records)`, `send(client, payload)`, `process_response(response, response_doc)`. El manager genérico itera empresas activas, respetando rate-limit por empresa (`timeout_seconds`), lotes con límite, y **aislamiento total de errores** (`log_error` por empresa, jamás abortar el run).
- Reintentos con backoff y tope de intentos por registro; al agotarse, notificación + estado visible.
- Los drivers se registran en un dispatcher por servicio — el scheduler (cron `* * * * *`) drena todos los servicios activos.

### 6. Firma (`signer.py`)

- Responsabilidad: firmar el contenido remitido según el perfil exigido por cada servicio. **Verificación pendiente** (ver 04 §Dudas): si la Orden exige XAdES del registro para VeriFactu, se implementa aquí (misma pieza reutilizable por eFactura/Facturae en 06); si TLS mutua es suficiente, queda como passthrough documentado.
- Misma credencial (2) para firmar y autenticar.

### 7. Permisos y notificaciones (`utils.py`)

- `has_aeat_permission(user, company, purpose)`: check explícito por empresa+propósito para TODA llamada whitelisted que dispare comunicación con AEAT (doc 12 §18).
- `notify_roles(company, purpose, subject, message)`: roles→usuarios (patrón de la referencia) vía Notification Log.
- `now_aeat()`, `format_aeat_datetime()`, `format_aeat_date()`: huso Europe/Madrid y formatos AEAT, un único punto de verdad.

### 8. Hooks transversales

- `company_data_to_be_ignored`: `SC AEAT Credential`, settings de cada funcionalidad.
- `ignore_links_on_delete`: `SC AEAT Response` (y sus lines) para no bloquear borrados legítimos de documentos de negocio.
- `user_data_fields` para el password de la credencial (protección de datos si se exporta).

## Cumplimiento del patrón 12

Mismos patrones que 04 (doc_events n/a, scheduler_events para expiración + drenaje, permisos explícitos en whitelisted, sin SQL crudo, type hints en endpoints, tests desde el primer commit con cliente mockeado). El manager se diseña testeable: drivers inyectables + reloj inyectable (rate-limit).

## Dudas abiertas

- ¿Un certificado por (company, purpose) o por company con propósitos múltiples? (Recomendación: por (company, purpose), mismos datos físicos.)
- Perfil de firma (hereda de la verificación de 04).

## Tareas para agentes

- [ ] Implementar doctypes credential + response/line con migración conceptual desde la referencia (`SC Verifactu AEAT Response` → `SC AEAT Response`).
- [ ] Implementar cliente SOAP factoría con registro de endpoints (VeriFactu primero; SII los añade en su fase).
- [ ] Implementar outbox manager con drivers + rate-limit + aislamiento + reintentos (tests con reloj/driver mock).
- [ ] Implementar expiración de certificados (daily) con notificación.
- [ ] Mock del cliente AEAT para los tests de integración de 04 y 05 (grabar/reproducir, usando `aeat_response_examples/` de la referencia como semilla).

## Dependencias con otros specs

- **[04-verifactu.md](04-verifactu.md)** — primer consumidor; se construye a la par.
- **[05-sii.md](05-sii.md)** — segundo consumidor (mismo cliente SOAP, mismo outbox, credenciales por purpose `SII`).
- **[06-efactura.md](06-efactura.md)** — reutiliza `SC AEAT Credential` para la firma XAdES de Facturae (si se decide compartir; decisión a tomar al detallar 06).
