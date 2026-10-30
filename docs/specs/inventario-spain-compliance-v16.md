# Inventario de la app actual (`spain_compliance`, rama `version-16`)

Fase 0 del maestro: qué hay hecho, qué cumple las reglas R1–R12, qué hay que corregir y cómo encaja con las specs 01–14 de este proyecto.

> Fuente: ZIP de la rama `version-16` aportado el 30/10/2026. Revisión estática del código y de las specs del propio repo (`specs/00–14`); **no se ha ejecutado** ni la app ni sus tests. Las afirmaciones sobre Frappe/ERPNext se han contrastado con el código de la rama `version-16` (commit del 28/10/2026).

## 1. Resumen

La app está **mucho más avanzada y mejor alineada con las reglas de Frappe** de lo que suponían las specs de este proyecto:

- **Capa AEAT** compartida implementada: credenciales por empresa y propósito, cliente SOAP (zeep) con TLS mutua, registro de respuestas, outbox con reintentos, firma.
- **Verificador de NIF/CIF** transversal implementado.
- **Verifactu v1** implementado: libro de registros encadenado, emisión y anulación, subsanación, consulta a la AEAT, QR y formato de impresión, notificaciones por roles.
- Unas **6.300 líneas de Python** (sin tests), **21 ficheros de test con 259 casos** y specs propias detalladas: 04 Verifactu (361 líneas), 12 indicaciones técnicas (437), 13 capa AEAT y 14 verificador de NIF.
- Pendientes según su propio índice: plan contable, SEPA, Norma 43, SII, eFactura, impuestos por defecto, informes de IVA, retenciones, traducciones y facturación masiva.

Las specs de este proyecto deben **construir sobre lo existente**, no reemplazarlo (§5).

## 2. Cumplimiento de las reglas R1–R12

| Regla | Estado | Detalle |
|---|---|---|
| R1 Sin monkey patching | ✅ | Ninguna reasignación de atributos de módulos de Frappe o ERPNext. |
| R2 Sin overrides de clase | ⚠️ | No hay `override_doctype_class`. Hay un `extend_doctype_class` (mixin con `autoname` en Sales Invoice). **Se puede sustituir por un `doc_event`**: `set_new_name` llama a `doc.run_method("autoname")` y `run_method` ejecuta los `doc_events` aunque el controlador no defina el método **[verificado en Frappe v16]**. Ver H2. |
| R3 Custom fields por código | ✅ | `create_custom_fields` en `after_install` y `after_migrate`, borrado en `before_uninstall`, con protección ante campos homónimos de otras apps. Nota: el §4 de su doc 12 todavía recomienda fixtures; contradice su propio §11 y la charla; conviene corregir el texto. |
| R4 doc_events baratos | ⚠️ | Hay salidas tempranas, pero con `frappe.db.get_value` sin caché en `validate` y `before_submit` de cada Sales Invoice. Cambiar a `frappe.get_cached_value`. |
| R5 Sin SQL crudo ni commits | ✅ | Solo en dos patches de renombrado, para el `ALTER TABLE ... DROP COLUMN` (justificado y comentado). |
| R6 Endpoints con tipos y permisos | ✅ | Los 5 endpoints tienen type hints; los que tocan la AEAT comprueban permiso por empresa y propósito. Mejora: `rectify` modifica datos y admite GET; restringir a `methods=["POST"]`. |
| R7 Cada compañía decide | ❌ | **H1**: el nombre temporal de borrador se aplica a todas las compañías y las que no tienen Verifactu se quedan con él al validar. |
| R8 `company_data_to_be_ignored` | ✅ | Credenciales, series, roles de notificación y el libro de registros Verifactu (historia legal, no se borra). |
| R9 Dimensiones contables | — | No aplica todavía (no genera asientos). |
| R10 Print formats | ⚠️ | Formato predeterminado vía Property Setter. Falta borrar ese Property Setter al desinstalar. |
| R11 Dependencias opcionales | — | No aplica todavía. |
| R12 Tests y Semgrep en CI | ❌ | **No hay CI** (sin `.github/workflows`) ni Semgrep. Los 259 tests solo corren a mano. Pre-commit con ruff, eslint, prettier y pyupgrade. |

## 3. Hallazgos que corregir

**H1 — Alta. Facturas con nombre de borrador permanente en compañías sin Verifactu.**
El mixin `SalesInvoiceVerifactuMixin.autoname` asigna `BORRADOR-<epoch>-<hash>` (o el patrón de borrador de la compañía) a **todas** las Sales Invoice, con Verifactu o sin él. El renombrado a la serie fiscal solo ocurre en `before_submit` y solo si `sc_verifactu_enabled`. Su propio test `test_inactive_company_submit_untouched` comprueba que, sin Verifactu, la factura validada **conserva el nombre temporal**. Consecuencias:
- Compañías españolas que aún no activan Verifactu (lo normal hasta 2027) y compañías en el SII emiten facturas con números no correlativos, contrarios al art. 6 del RD 1619/2012.
- Compañías de otros países del mismo sitio cambian de comportamiento.

Corrección propuesta: el `autoname` actúa solo si la compañía tiene activada la **numeración fiscal española** (un ajuste propio, independiente de Verifactu, para cubrir también a las compañías en el SII); si no, no asigna nombre y Frappe sigue con `naming_series` **[verificado: `set_new_name` cae a las opciones de naming si `autoname` no asigna nombre]**.

**H2 — Media. Mixin de clase sustituible por `doc_event`.**
`doc_events = {"Sales Invoice": {"autoname": "...emission.autoname"}}` hace lo mismo sin extender la clase: elimina la única extensión de clase de la app y evita conflictos de MRO con otras apps que extiendan Sales Invoice.

**H3 — Media. Clave privada del certificado sin cifrar en disco.**
`SC AEAT Credential._extract_pem` escribe el certificado y la **clave privada sin cifrado** (`NoEncryption()`) en `sites/<site>/private/files/<empresa>-<propósito>-key.pem`, con los permisos por defecto del proceso y un nombre predecible, sin documento File asociado. Esos ficheros entran en las copias de seguridad con ficheros. Propuesta: permisos `0600` como mínimo; mejor, fuera de `private/files` (directorio propio del sitio excluido de backups públicos) o descifrado en memoria o en un temporal `0600` por envío.

**H4 — Media. Sin CI.** Añadir GitHub Actions con bench v16, ejecución de los 259 tests y Semgrep con `frappe/semgrep-rules` (spec 01 §7). Su TODO ya apunta a fallos intermitentes con el scheduler durante los tests: el CI los hará visibles.

**H5 — Baja.**
- `pyproject.toml` declara `frappe >= 16.0.0-dev` y lo mismo para ERPNext; la decisión D1 es v16.50 o posterior (la propia rama `version-16` de ERPNext ya exige Frappe ≥ 16.50).
- Property Setter del formato de impresión no se borra al desinstalar.
- El stub `get_spain_tax_breakup` deduce el impuesto y el tipo de la `description` de la fila ("IVA - 21"). Ya está identificado en su TODO; la sustituyen las specs 03 y 06 (§5).

**H6 — Corrección a su TODO.** Dice que ERPNext no aplica las Tax Rule al crear la factura. En v16, `get_party_details` (lo que llama el formulario al elegir cliente o proveedor) ejecuta `set_taxes`, que llama a `get_tax_template` con las Tax Rule y fija `taxes_and_charges` **[verificado v16]**. Falta comprobar en un bench si también ocurre en facturas creadas por API sin pasar por el formulario.

## 4. Correspondencia de funcionalidades

| Funcionalidad | Spec del repo | Estado en el repo | Spec de este proyecto | Qué hacer |
|---|---|---|---|---|
| Capa AEAT (certificados, SOAP, outbox) | 13 | **Hecho** | 10 §3, 14 | Reutilizar `SC AEAT Credential` y el outbox; las specs 10 y 14 no crean doctypes de certificado propios. |
| Verificador NIF | 14 | **Hecho** | 06 (identificación) | Reutilizar. |
| Verifactu | 04 | **Hecho v1** | 07 (hoja de ruta) | Tratarlo como existente; queda el contrato de desglose (fila siguiente) y H1/H2. |
| Desglose fiscal de la factura | 07 (stub) | Stub por descripción | 03, 06 | La clasificación (03) y el Registro Fiscal IVA (06) cumplen el contrato `get_spain_tax_breakup` (tipo, tipo impositivo, base, cuota, calificación, clave de régimen, causa de exención). |
| Series, rectificativas, correlatividad | 04 §4 (numeración al emitir, series por tipo de factura) | **Hecho (solo con Verifactu)** | 05 §1–3 | Reescribir la spec 05 sobre su diseño: con número al emitir y fecha de hoy, la correlatividad queda garantizada por construcción y sobra el control de la spec 05 §3. Generalizarlo a todas las compañías españolas (H1). |
| Plan contable | 01 | Pendiente | 02, 04 | Usar las specs 02 y 04. |
| Impuestos por defecto | 07 | Pendiente | 03, 09 | Usar 03 y 09. Su TODO plantea Tax Rule o un campo en Customer: vale Tax Rule (H6). |
| Retenciones | 09 | Pendiente | 08 | Su TODO llega a la misma conclusión: tipo negativo en ventas y mecanismo nativo en compras. Añadir a la spec 08 su punto sobre Verifactu y SII (el IRPF no va en el desglose de Verifactu; en el SII va aparte). |
| Informes de IVA | 08 | Pendiente | 06 §5, 07 (modelos) | Usar 06. |
| SEPA | 02 | Pendiente | 11 | Usar 11. |
| Norma 43 y conciliación | 03 | Pendiente | 13 | Usar 13. |
| SII | 05 | Pendiente | 14 | Usar 14 sobre la capa AEAT existente. |
| eFactura | 06 | Pendiente | 10 | Usar 10. |
| Confirming | — | — | 12 | Nuevo. |
| Estados financieros PGC | — | — | 04 | Nuevo. |
| Datos iniciales | — | — | 09 | Nuevo. |
| Traducciones | 10 | Pendiente | 07 | Sin cambios. |
| Facturación masiva | 11 | Pendiente | 07 | Sin cambios. |

## 5. Convenciones del repo que prevalecen sobre las de este proyecto

Decisiones ya tomadas y aplicadas en el código, que las specs de este proyecto deben adoptar:

| Tema | Repo (prevalece) | Specs de este proyecto (a corregir) |
|---|---|---|
| Identificadores | **Inglés** (funciones, fieldnames, módulos Python); labels y mensajes en es-ES; claves AEAT literales | Español |
| Prefijo | **`SC`** en doctypes y módulos Frappe (`SC Verifactu`, `SC Sii`, `SC Sepa`, …), por la colisión de nombres de módulo entre apps. **Decisión posterior: se renombra a `ES`** (§6) | Módulos `Contabilidad ES`, `Fiscalidad ES`, `Facturacion ES` |
| Configuración | **`SC Settings`** (Single) para lo global; pestaña "Spain Compliance" en Company para lo de cada empresa | Solo custom fields en Company |
| Activación | Por funcionalidad y empresa (`sc_verifactu_enabled`, …) | Marca única `pgc_aplicado` |
| Mensajes de error | Con el remedio concreto | — |

La marca `pgc_aplicado` sigue siendo útil para el plan contable y lo que depende de él, pero como una activación más junto a las de cada funcionalidad.

## 6. Decisiones tomadas (30/10/2026)

1. **Nombre de la app: `erpnext_spain`.** Se renombra el paquete (spec 01 §1).
2. **Sin migración**: solo instalaciones nuevas sobre v16.50+. Se eliminan los patches de migración del código base y las menciones a la coexistencia con la app v1 `spanish_compliance` (maestro D3, spec 01 §1).
3. **Las specs de este proyecto son la fuente canónica**; las del repo quedan como referencia. Las specs ya se han adaptado al código existente: convenciones (maestro §3), correcciones H1–H5 (spec 01 §8), numeración fiscal (spec 05), contrato del desglose con Verifactu (spec 06 §6), capa AEAT en SII y factura electrónica (specs 10 y 14).
4. **Prefijo `SC` → `ES`** en doctypes, módulos y custom fields (`sc_*` → `es_*`), en el mismo paso que el renombrado de la app. Sin colisiones con Frappe ni ERPNext (spec 01 §1, maestro §3). Este inventario conserva los nombres `SC` porque describe el código tal como está.

## 7. Plan de acción propuesto

| Orden | Tarea | Hallazgo |
|---|---|---|
| 1 | Numeración fiscal solo en compañías con el ajuste activo; resto con `naming_series` | H1 |
| 2 | Mixin → `doc_event` de `autoname`; quitar `extend_doctype_class` | H2 |
| 3 | Proteger la clave privada del certificado | H3 |
| 4 | CI con bench v16, tests y Semgrep | H4 |
| 5 | Caché en salidas tempranas, `POST` en `rectify`, dependencia ≥ 16.50, limpieza del Property Setter | H5, R4, R6 |
| 6 | Renombrado a `erpnext_spain` y retirada de los patches de migración (spec 01 §1) | §6 |
| 7 | Siguiente funcionalidad: specs 03 + 06 (clasificación y Registro Fiscal IVA), que sustituyen el stub del desglose de Verifactu y desbloquean SII e informes de IVA | H5 |
