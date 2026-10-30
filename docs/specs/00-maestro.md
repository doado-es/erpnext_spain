# erpnext_spain — Documento maestro

App de Frappe para adaptar ERPNext a la contabilidad y la fiscalidad españolas. Este documento fija las decisiones, las reglas técnicas obligatorias y el orden de trabajo. Cada funcionalidad tiene su propia spec (índice al final). Las specs están pensadas para que un agente o un desarrollador pueda trabajar en una sin leer las demás, pero ninguna puede contradecir este documento.

> Verificaciones: lo marcado como **[verificado v16]** se ha comprobado leyendo el código de `frappe/erpnext` y `frappe/frappe`, rama `version-16` (commit del 28/10/2026, último tag v16.53.0). Nada se ha ejecutado aún en un bench. Lo marcado como **[verificar]** es una suposición razonable que hay que confirmar al implementar.

## 1. Decisiones

| Id | Decisión |
|---|---|
| D1 | Solo ERPNext/Frappe **v16.50 o posterior**. No se mantiene compatibilidad con v15. |
| D2 | La app se llama **`erpnext_spain`** (renombrada desde `spain_compliance`, nombre que ya usa una app pública de Xappiens con la que no hay relación). |
| D3 | **No hay migración** de compañías, clientes ni de la app v1 (`spanish_compliance`): solo instalaciones nuevas sobre v16.50+. El plan PGC solo se aplica a compañías sin movimientos. |
| D4 | El **árbol de cuentas es nativo de ERPNext**: cada rama tiene un único `root_type`. Las cuentas llevan numeración PGC; la estructura por grupos, subgrupos y epígrafes del PGC se reconstruye en la capa de informes a partir del número de cuenta. |
| D5 | Balance y PyG del PGC se construyen como **`Financial Report Template` estándar** incluidas en la app y se ven con los informes nativos Balance Sheet / Profit and Loss, filtro `report_template` **[verificado v16]**. |
| D6 | Se cumplen sin excepciones las **reglas de Frappe para apps de cumplimiento** (charla "Building Compliance Software", Frappe Build 2026, y guía de contribución regional). Ver §2. |
| D7 | Arranque de una compañía nueva: **paso de onboarding "Aplicar plan PGC"** después del asistente de configuración, no una etapa propia en el asistente. |
| D8 | **Código base**: la rama `version-16` de `ct-Galega/spain_compliance` (capa AEAT, verificador de NIF y Verifactu v1 ya implementados), que se renombra a `erpnext_spain`. Estas specs son la fuente canónica; las del repo quedan como referencia. Inventario y correcciones pendientes en [inventario-spain-compliance-v16](inventario-spain-compliance-v16.md). |

Base legal de D4 (a confirmar con asesor): el cuadro de cuentas (4ª parte del PGC) y las definiciones y relaciones contables (5ª parte) no son obligatorios salvo en lo que contengan criterios de registro o valoración (RD 1514/2007, art. 2). Son obligatorios los modelos de cuentas anuales y los libros del Código de Comercio (Diario e Inventarios y Cuentas Anuales, con balances de comprobación de sumas y saldos al menos trimestrales, art. 28). Ninguno exige que el árbol del ERP siga los grupos 1 a 9.

## 2. Reglas técnicas obligatorias

Un PR que incumpla cualquiera de estas reglas no se integra. El CI comprueba las que se pueden automatizar (spec 01).

| Id | Regla |
|---|---|
| R1 | **Prohibido el monkey patching**: no se reasignan funciones, clases ni atributos de módulos de Frappe, ERPNext u otras apps. En un bench compartido afectaría a todos los sitios. |
| R2 | **Prohibido `override_doctype_class`**. Se extiende con `doc_events`, regional overrides (`regional_overrides` + funciones con `@erpnext.allow_regional`), hooks documentados y doctypes propios. Si falta un punto de extensión, se abre una issue en `frappe/erpnext`, no se parchea. |
| R3 | **Custom fields por código**, con `create_custom_fields` en `after_install`/`after_migrate`, nunca con fixtures. Se eliminan en `before_uninstall`. Igual para los Property Setters. |
| R4 | **`doc_events` baratos**: lo primero es una salida temprana con valores cacheados (`frappe.get_cached_value`, caché propia). Nada de consultas por línea de documento. No se añaden `doc_events` a GL Entry ni Payment Ledger Entry salvo necesidad justificada en la spec. |
| R5 | **Sin SQL crudo**: query builder (`frappe.qb`) o `frappe.get_all`. **Sin `frappe.db.commit()`** (los jobs en segundo plano confirman solos). |
| R6 | **Todo endpoint `@frappe.whitelist()` tiene type hints y comprobación de permisos o rol.** Obligatorio en los que llamen a servicios de la AEAT u otros terceros. |
| R7 | **Cada compañía decide**: todo comportamiento español se activa solo en compañías con la marca *Plan PGC aplicado* o con el ajuste de la funcionalidad correspondiente (`numeracion_fiscal`, `es_verifactu_enabled`, …) (spec 01 §5). El resto de compañías del sitio se comporta como ERPNext estándar. |
| R8 | **Datos de configuración con campo compañía** se declaran en `company_data_to_be_ignored` para que el borrado de transacciones no los elimine **[verificado v16]**. |
| R9 | **Cualquier documento propio que genere asientos** debe soportar dimensiones contables. Preferencia: generar Journal Entry nativo en lugar de GL propio. |
| R10 | **Print formats** propios se fijan como predeterminados con Property Setter al instalar y se limpian al desinstalar. Se extienden con utilidades Jinja, nunca parcheando el documento base. |
| R11 | **Dependencias opcionales** (p. ej. HRMS) no se declaran como dependencia dura: sus custom fields se crean si la app está instalada, también vía `after_app_install` **[verificado v16]**. |
| R12 | **Tests y Semgrep** (`frappe/semgrep-rules`) en el CI, sin hallazgos. |

## 3. Convenciones

Se adoptan las convenciones que ya aplica el código base (D8):

- **Identificadores en inglés**: funciones, variables, módulos Python, fieldnames y nombres de informes. Excepciones: las claves del protocolo AEAT se guardan tal cual (`RegistroAlta`, `DetalleDesglose`…), y los valores de dominio que define la AEAT también.
- **Los nombres de campo de estas specs son descriptivos** (están en español para leerlas mejor). Al implementar se traducen al inglés con el prefijo `es_` en los custom fields (`es_verifactu_enabled`, `es_trade_name`). Ejemplo: `calificacion_iva` → `es_vat_classification`.
- **Prefijo `ES`** en doctypes y módulos Frappe (`ES Verifactu`, `ES Sii`, `ES Sepa`, `ES Impuestos`, …) y `es_` en custom fields y carpetas de módulo, con `aeat` y `nif` como capas transversales y el módulo base `ERPNext Spain` (el que crea `bench new-app`, spec 01 §3) como única excepción. El prefijo evita colisiones de nombres de módulo entre apps (Frappe resuelve doctype → app por el nombre del módulo). Comprobado: ni Frappe ni ERPNext usan doctypes, módulos ni fieldnames con ese prefijo.
- **Nombres de doctypes e informes nuevos en las specs**: se describen en español ("Registro Fiscal IVA", "Sumas y saldos PGC") y cada spec indica el **nombre final** en inglés con prefijo `ES` (`ES Vat Register`, `ES Trial Balance by Level`). La etiqueta en español llega por las traducciones es-ES.
- **Endpoints**: nombre en inglés; `methods=["POST"]` en todos los que modifican datos, también los que admiten `dry_run`.
- **Nombres en estas specs frente al código base**: el código base usa hoy `SC`/`sc_` y se renombra a `ES`/`es_` en la fase 0 (spec 01 §1). Las specs ya usan los nombres nuevos, también cuando describen lo que existe: `es_verifactu_enabled` es hoy `sc_verifactu_enabled`, `ES AEAT Credential` es hoy `SC AEAT Credential`.
- **Configuración**: `ES Settings` (Single) para lo global; pestaña "Spain Compliance" en Company (custom fields y tablas hijas propias) para lo de cada empresa. Nunca override del controlador de Company.
- **Activación por funcionalidad y empresa** (`es_verifactu_enabled`, …) además de la marca `pgc_aplicado` del plan contable (spec 01 §5).
- **Mensajes de error con el remedio concreto**, como en el código.
- **Textos de interfaz** en español con `_()`; traducciones es-ES en la app.
- Nunca reutilizar el nombre de un campo o propiedad de ERPNext (p. ej. `company_abbr` ya existe como propiedad).
- **Ramas**: `version-16` (estable) y `develop`.
- **Un PR por apartado de spec**, con tests y la casilla de reglas R1–R12 revisada en la descripción.

## 4. Fases e índice de specs

| Fase | Spec | Contenido | Estado |
|---|---|---|---|
| 0 | [inventario-spain-compliance-v16](inventario-spain-compliance-v16.md) | Estado del código base, cumplimiento de R1–R12 y correcciones H1–H5 | Hecho |
| 0 | [01-fundamentos](01-fundamentos.md) | Renombrado, estructura, instalación, gating, CI, correcciones del código base | Lista para desarrollo |
| 1 | [02-plan-contable](02-plan-contable.md) | Plan PGC nativo (Normal y PYMES), acción "Aplicar plan PGC", validación de cuentas | Lista; requiere revisión contable del reparto |
| 1 | [09-datos-iniciales](09-datos-iniciales.md) | Inventario y reglas de los registros de arranque (globales y por compañía) y de su actualización por cambios normativos | Lista |
| 1 | [03-impuestos](03-impuestos.md) | Clasificación fiscal, plantillas de IVA, RE, IRPF, reglas de impuestos | Lista; tipos a verificar al implementar |
| 2 | [04-estados-financieros](04-estados-financieros.md) | Plantillas Balance/PyG (Normal, Abreviado, PYMES), reclasificación por signo, sumas y saldos, libro diario, cierre 8/9 | Lista; mapeo a epígrafes requiere contable |
| 3 | [05-facturacion](05-facturacion.md) | Series, rectificativas, correlatividad, situación de cobro, formato de factura | Lista |
| 3 | [06-registro-fiscal-iva](06-registro-fiscal-iva.md) | Registro de IVA por factura, ISP e intracomunitarias, libros y borrador de liquidación | Lista |
| 3 | [08-retenciones](08-retenciones.md) | Retenciones de IRPF practicadas (mecanismo nativo de ERPNext) y soportadas (plantillas de venta), informes para 111/115/180/190/130 | Lista; A7 y claves del 190 pendientes |
| 4 | [10-factura-electronica](10-factura-electronica.md) | Facturae y FACe (B2G); factura electrónica B2B del RD 238/2026 y la Orden HAC/1028/2026 (emisión, recepción y estados) | Lista; A9 y documentación técnica de la SPFE pendientes |
| 4 | [11-sepa](11-sepa.md) | Transferencias (`pain.001`) y adeudos CORE/B2B (`pain.008`) con mandatos, respuestas, devoluciones y verificación del beneficiario | Lista; versiones por banco a verificar |
| 4 | [12-confirming](12-confirming.md) | Remesas de confirming en el formato estándar de la AEF y su contabilidad | Requiere leer el PDF oficial v.03.26 |
| 4 | [13-conciliacion-bancaria](13-conciliacion-bancaria.md) | Importación Norma 43 y conexión por API (agregador PSD2) hacia la conciliación nativa | Lista; A8 pendiente |
| 4 | [14-sii](14-sii.md) | Suministro Inmediato de Información: libros, cola de envío, plazos, cuadre | Lista; esquema vigente a verificar |
| — | Verifactu | Ya implementado (v1) en el código base; pendientes en su TODO y en el inventario | Hecho v1 |
| 5+ | [07-roadmap](07-roadmap.md) | Modelos AEAT, factoring, otros | Por detallar |

Fase 0: el inventario del código base ya está hecho. Lo que existe y cumple se conserva (capa AEAT, verificador de NIF, Verifactu v1); antes de añadir funcionalidad se corrigen los hallazgos H1–H5 (spec 01 §8).

## 5. Decisiones abiertas

| Id | Pregunta | Propuesta por defecto |
|---|---|---|
| A1 | ¿Subcuentas contables por cliente/proveedor (430xxxxx / 400xxxxx)? | Opción por compañía, desactivada por defecto (spec 02 §6). |
| A2 | ~~Correlatividad por fechas~~ | Cerrada: con la numeración al emitir del código base la correlatividad queda garantizada por construcción (spec 05 §3). |
| A3 | ~~¿Inventario permanente de ERPNext o administrativo del PGC?~~ | **Cerrada (30/10/2026): inventario administrativo.** Las compras van a gasto (grupo 60) y las existencias se regularizan al cierre (30x contra 61x/71x) con un asiento propio; las compañías PGC trabajan con `enable_perpetual_inventory = 0` (spec 02 §2–§3, spec 04 §7). |
| A4 | ¿Qué modelo de cuentas anuales primero? | PYMES (el más frecuente), luego Abreviado y Normal. |
| A5 | IGIC / IPSI (Canarias, Ceuta, Melilla). | Fuera de alcance en esta versión. |
| A6 | Verifactu vs SII. | No es una elección de producto sino de cada compañía: `es_sii_enabled` para obligadas y adheridas, `es_verifactu_enabled` para el resto; las dos casillas son excluyentes y lo garantiza la validación de Company (spec 14 §1). Orden de desarrollo: según la cartera de clientes. |
| A7 | Periodo de las retenciones en los modelos 111 y 115: ¿fecha de pago (art. 78.1 RIRPF) o de factura? | Informe con las dos opciones; la compañía decide con su asesor (spec 08 §5). |
| A8 | Agregador bancario para la conexión por API (spec 13). | Elegir por cobertura de bancos españoles, licencia y coste. |
| A9 | Canal de factura electrónica B2B: desarrollo propio contra la SPFE de la AEAT o integración con una plataforma privada (spec 10). | Adaptador intercambiable; decidir el primero cuando se publique la documentación técnica de la SPFE. |

## 6. Definición de terminado (para cualquier spec)

1. Criterios de aceptación de la spec cubiertos por tests que se ejecutan en el CI.
2. CI en verde: ruff, Semgrep con `frappe/semgrep-rules` y la regla propia contra R1/R2, tests en bench v16.
3. Instalación y desinstalación limpias en un sitio nuevo (sin restos de custom fields ni property setters).
4. Una compañía sin la marca PGC no cambia de comportamiento.
5. Documentación de usuario actualizada en el workspace de la app.

## 7. Referencias

- Charla "Building Compliance Software", Nikhil Kothari, Frappe Build 2026: https://www.youtube.com/watch?v=MN4hPiliN6A
- Guía de Frappe para apps regionales: https://docs.frappe.io/cloud/guidelines-for-contributing-regional-compliance-app
- Referencia de buenas prácticas: `resilient-tech/india-compliance`.
- Referencia funcional (no copiar código, AGPL): `OCA/l10n-spain` (Odoo).
