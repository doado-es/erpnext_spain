# Instrucciones para agentes — erpnext_spain

App de Frappe que localiza ERPNext para España. Solo ERPNext/Frappe **v16.50+**.

## Antes de escribir código

1. Lee `docs/specs/00-maestro.md` entero: decisiones, reglas R1–R12 y convenciones. Ninguna spec puede contradecirlo.
2. Lee la spec de la tarea y las que cite. Trabaja **un apartado de spec por rama y por PR**.
3. Si la spec marca algo como **[verificar]**, compruébalo en el código de Frappe/ERPNext v16 o en el bench antes de apoyarte en ello, y anota el resultado en el PR.
4. Si algo de la spec no se puede hacer sin incumplir una regla, para y pregunta. No busques atajos.

## Reglas que el CI no perdona (resumen; el detalle está en el maestro §2)

- **Nunca** monkey patching: no reasignes funciones, clases ni atributos de módulos de Frappe, ERPNext u otras apps.
- **Nunca** `override_doctype_class` ni `extend_doctype_class`. Extiende con `doc_events`, `regional_overrides` (funciones con `@erpnext.allow_regional`), hooks documentados y doctypes propios. Si falta un punto de extensión, se propone una issue en `frappe/erpnext`.
- Custom fields y Property Setters **por código** (`create_custom_fields` en `after_install`/`after_migrate`), con su limpieza en `before_uninstall`. Nunca fixtures para custom fields.
- Datos iniciales con funciones `ensure_*` idempotentes que crean lo que falta y no pisan lo que haya cambiado el usuario (spec 09).
- `doc_events` con salida temprana barata como primera instrucción: `is_pgc_company(company)` o `is_feature_enabled(company, flag)` con `frappe.get_cached_value`. Nada de consultas por línea de documento.
- Sin `frappe.db.sql` (usa `frappe.qb` o `frappe.get_all`) y sin `frappe.db.commit()`.
- Todo `@frappe.whitelist()` con type hints y comprobación explícita de permisos o rol. Los que modifican datos, `methods=["POST"]`. Los que llaman a la AEAT, a un banco o a una plataforma comprueban el permiso por empresa (un certificado por empresa).
- Una compañía sin la activación correspondiente se comporta exactamente como ERPNext estándar.

## Convenciones

- Identificadores en **inglés**. Labels, mensajes y documentación en **es-ES**. Las claves del protocolo AEAT se guardan tal cual.
- Prefijo **`ES`** en doctypes y módulos (`ES Settings`, `ES Verifactu …`) y **`es_`** en custom fields y carpetas de módulo. Los nombres de campo en español de las specs son descriptivos: tradúcelos al inglés con `es_` (p. ej. `calificacion_iva` → `es_vat_classification`).
- Configuración global en `ES Settings`; la de cada empresa en la pestaña "Spain Compliance" de Company.
- Mensajes de error que dicen qué pasa **y cómo arreglarlo**.

## Tests y CI

- Cada criterio de aceptación de la spec tiene un test. Los tests van en el mismo PR que el código.
- Nunca contra servicios reales de la AEAT ni de bancos: usa el cliente simulado de `aeat/tests/`.
- Antes de abrir el PR: `ruff check`, `ruff format --check`, Semgrep con `frappe/semgrep-rules` y las reglas propias de `.semgrep/`, y `bench --site <test> run-tests --app erpnext_spain`.

## Definición de terminado

Criterios de aceptación cubiertos por tests en verde en el CI; instalación y desinstalación limpias; una compañía sin activar no cambia de comportamiento; documentación de usuario actualizada.

## Orden de trabajo

Fase 0 primero (spec 01): renombrado a `erpnext_spain`, `SC` → `ES`, CI y correcciones H1–H5 del inventario. Después, las fases del maestro §4.
