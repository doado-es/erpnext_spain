# Custom App: Localización ERPNext España

## Objetivo

Construir una app custom de Frappe/ERPNext que adapte la operativa contable, fiscal y bancaria de ERPNext a los requisitos de España (PGC, AEAT, Banco de España), sin forkear el core.

## Principios de diseño

- **No tocar el core de ERPNext.** Toda la lógica vive en la app custom, usando `hooks.py`, `doc_events`, Custom Fields, Custom Scripts y overrides controlados.
- **Reutilizar al máximo el motor contable de ERPNext** (partida doble, GL Entry, Payment Entry, Tax Templates). La app añade capas de localización, no reemplaza el core financiero.
- Cada funcionalidad se documenta en su propio fichero (ver índice) con: objetivo, contexto normativo, alcance, estado/referencias, diseño técnico propuesto, dudas abiertas y tareas para agentes.
- Este documento maestro se irá actualizando con decisiones transversales (nombre de la app, estructura de DocTypes compartidos, convenciones de naming, dependencias entre módulos).

## Índice de funcionalidades

| # | Fichero | Funcionalidad | Estado |
|---|---------|----------------|--------|
| 1 | [01-plan-contable.md](01-plan-contable.md) | Adaptación del plan contable (PGC, root types) | Pendiente de detallar |
| 2 | [02-sepa.md](02-sepa.md) | Generación de ficheros SEPA (Norma 19, 34...) | Pendiente de detallar |
| 3 | [03-norma43.md](03-norma43.md) | Captura Norma 43 (conciliación bancaria) | Pendiente de detallar |
| 4 | [04-verifactu.md](04-verifactu.md) | Conexión a VeriFactu | Diseño técnico v1 listo |
| 5 | [05-sii.md](05-sii.md) | Conexión al SII | Pendiente de detallar |
| 6 | [06-efactura.md](06-efactura.md) | eFactura | Pendiente de detallar |
| 7 | [07-impuestos-defecto.md](07-impuestos-defecto.md) | Automatización de tipos de impuesto por defecto | Pendiente de detallar |
| 8 | [08-informes-iva.md](08-informes-iva.md) | Generación de informes de IVA (303, 347, 349, 390) | Pendiente de detallar |
| 9 | [09-retenciones.md](09-retenciones.md) | Gestión de retenciones a profesionales (IRPF) | Pendiente de detallar |
| 10 | [10-traducciones.md](10-traducciones.md) | Buenas traducciones (es-ES) | Pendiente de detallar |
| 11 | [11-facturacion-masiva.md](11-facturacion-masiva.md) | Facturación masiva de delivery notes | Pendiente de detallar |
| 12 | [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md) | Indicaciones técnicas generales (patrón India Compliance) | Primera versión lista |
| 13 | [13-capa-aeat.md](13-capa-aeat.md) | Capa AEAT compartida (VeriFactu + SII + eFactura) | Diseño técnico v1 listo |
| 14 | [14-verificador-nif.md](14-verificador-nif.md) | Verificador de NIF/CIF (transversal) | Diseño técnico v1 listo |

## Decisiones transversales

- [x] Nombre de la app / repositorio (spain_compliance)
- [x] Estructura de módulo dentro de la app → un submódulo Frappe por funcionalidad (ver [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md))
- [x] Versión mínima de Frappe/ERPNext soportada → **v16** (`version-16-hotfix` del bench testsc). Pendiente plasmarlo en `pyproject.toml` (`tool.bench.frappe-dependencies`) al iniciar el desarrollo — decisión: `frappe = ">=16.0.0,<17.0.0"` y lo mismo para erpnext.
- [x] Convención de naming para DocTypes nuevos (prefijo, si lo hay) El prefijo será SC (ejemplo, SC Settings)
- [x] Estrategia de configuración (revisada por decisión de producto — supera el "un Single por bloque funcional" inicial): **`SC Settings`** = Single hub con lo **genérico/global** de cada funcionalidad (secciones por funcionalidad: VeriFactu → identidad SIF + endpoints; SEPA → genérico; ...); **lo por-empresa vive en un tab "Spain Compliance" del doctype Company** — Custom Fields vía `create_custom_fields` + child tables propias (ej. `SC Verifactu Series`) + validaciones en `doc_events` de Company (nunca override del controller). El anti-monolito se preserva por el eje global-hub vs per-company-en-Company. Las series de facturas se configuran POR COMPANY (el contador de tabSeries es por prefijo sin dimensión empresa — compartir serie entre companies rompe la correlatividad de ambas).
- [x] Mecanismo de extensión del core: `@allow_regional`/`regional_overrides` donde el core lo soporte, `doc_events` en el resto; `extend_doctype_class` por defecto sobre `override_doctype_class` (ver [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md))
- [x] Custom Fields: declarados en Python vía `create_custom_fields` en `after_install`, con `delete_custom_fields` en desinstalación (ver [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md))
- [x] `required_apps = ["frappe/erpnext"]` en `hooks.py`, y reacción condicional a otras apps del ecosistema vía `after_app_install(app_name)` (ver [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md))
- [x] **Capa AEAT compartida** → spec [13-capa-aeat.md](13-capa-aeat.md): credenciales, cliente SOAP, registro de respuestas y outbox/reintentos se construyen UNA vez y los consume VeriFactu (04) y SII (05); eFactura (06) reutiliza el almacén de certificados.
- [x] **Convención de nombrado de módulos** → módulo Frappe por funcionalidad **con prefijo `SC `** (`SC Verifactu`, y en su momento `SC Sii`, `SC Sepa`, `SC Impuestos`, …) + capas transversales con nombre corto (`aeat`, `nif`) como excepción documentada. **Por qué el prefijo**: frappe resuelve doctype→app vía un mapa inverso módulo→app (`frappe.local.module_app`) que se construye iterando las apps instaladas — si dos apps declaran el mismo nombre de módulo, la última pisa a la primera y los doctypes del perdedor dejan de importar (verificado en el bench: `verifactu` → `spanish_compliance` rompía el migrate de la nueva app). Los términos de dominio español (`verifactu`, `sepa`, `sii`) son colisión **garantizada** con la app v1 y con cualquier otra app de localización — y la migración v1→v2 de sites reales exige coexistir con `spanish_compliance` instalada. El prefijo `SC ` además casa con la convención de prefijo de doctypes (los doctypes ya son `SC Verifactu *`). Los overrides viven dentro de cada funcionalidad (`spain_compliance.sc_verifactu.overrides.sales_invoice`); `regional_overrides` en `hooks.py` actúa como índice que apunta a la implementación de la funcionalidad correspondiente (refina el ejemplo `<app>.spain.overrides.*` del doc 12 manteniendo su espíritu).
- [x] **App previa `testsc/apps/spanish_compliance` = REFERENCIA, no port** — se reutilizan algoritmos verificados (huella/canonicalización, estructura de cabecera/registros, gestión p12→PEM) y patrones (SOAP Fault→líneas sintéticas, subsanación por código de error), corrigiendo sus deudas (ver tabla de gaps en [04-verifactu.md](04-verifactu.md)): sin `override_doctype_class`, sin SQL crudo, sin hardcodeo de SIF, ledger como doctype independiente, aislamiento por empresa en el scheduler. Toda decisión nueva debe cumplir [12-indicaciones-tecnicas.md](12-indicaciones-tecnicas.md).
- [x] **Idioma de los identificadores (decisión de desarrollo)**: TODO identificador nuestro (funciones, variables, constantes, fieldnames de doctypes, nombres de módulos Python, reports, tests) va en **inglés** (`drain_outbox`, `record_type`, `hash`, `prior_rejection`). EXCEPCIONES deliberadas: (1) las claves del wire AEAT (`Cabecera`, `RegistroAlta`, `IDEmisorFactura`, `Huella`, `DetalleDesglose`, `OperacionExenta`…) viajan y se almacenan VERBATIM en `record_json` — son contrato externo, renombrarlas rompería la integración; (2) labels de campos, mensajes de error y textos user-facing en **es-ES** (spec 10: la app es para contables españoles); (3) valores de datos/enum del dominio AEAT ("PendienteEnvio", "RegistroAlta", "Pruebas", "Inmediata") tal cual los define la AEAT/UI.
- [x] Repositorios de referencia externos: **OCA l10n-spain** (verificados y citados donde corresponde): `l10n_es_verifactu_oca` → spec 04 (arquitectura equivalente + roadmap que valida nuestras extensiones + cita normativa AEAT de subsanación/anulación), `l10n_es_aeat_sii_oca` → spec 05 (patrón de envíos y roadmap como backlog de referencia), `l10n_es_partner` → spec 14 (nombre comercial). India Compliance ya verificado en el doc 12.
- [x] **Colisión de nombres con la app v1 en coexistencia** (descubierta en desarrollo, verificada contra `frappe.local.module_app`): (1) módulo `Verifactu` → resuelta con el prefijo SC (ver convención de módulos); (2) doctype **`SC Settings`** — la v1 también tiene un Single con ese nombre exacto (módulo "Spanish Compliance"). Decisión: **mantenemos el nombre** — en un site con ambas apps el último sync se queda el doctype (en migraciones v1→v2 lo tomamos nosotros); la config SIF de la v1 (unos pocos campos) se re-ingresa a mano en el nuevo Single y el patch opcional de migración de v1 NO depende del SC Settings viejo (solo de custom fields de terceros). Documentado como takeover aceptado.

## Referencias externas generales

- OCA/l10n-spain (Odoo) — referencia de estructura de plan de cuentas y módulos, no de código directamente reutilizable
- Documentación AEAT: SII, VeriFactu (RD 1007/2023), modelos 303/347/349/390
- Documentación Frappe: hooks, Custom Fields, Server Scripts, Print Formats
