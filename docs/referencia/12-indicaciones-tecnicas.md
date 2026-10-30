# 12. Indicaciones Técnicas Generales (basadas en el patrón India Compliance)

[← Volver al índice](00-maestro.md)

> ⚠️ Nota de fuentes: lo que sigue está verificado contra el código fuente de `resilient-tech/india-compliance`, el código de `frappe/erpnext`, la documentación oficial de hooks de Frappe y DeepWiki. **No he podido acceder al contenido de la charla de YouTube "Building Compliance Software" (Nikhil Kothari, Frappe Build)** — el fetch directo devuelve error 429 y no hay transcripción indexada disponible. Si tienes acceso, pasa los puntos clave que quieras incorporar y los añadimos a este documento.

## 1. El patrón `@erpnext.allow_regional` + `regional_overrides`

Este es el mecanismo central que usa el propio ERPNext (no una invención de India Compliance, aunque India Compliance y HRMS lo usan extensivamente) para inyectar lógica específica de país sin tocar el core:

- **Decorador**: las funciones "regionalizables" del core se marcan con `@erpnext.allow_regional` (definido en `erpnext/__init__.py`).
- **Detección**: en tiempo de ejecución, `erpnext.get_region()` identifica el país activo a partir de la `Company` o de `System Settings`.
- **Enrutado**: el decorador consulta `frappe.get_hooks("regional_overrides")`. Si existe una entrada para el país detectado, ejecuta esa función en lugar de (o adicionalmente a) la implementación estándar.

Ejemplo real tomado del `hooks.py` de ERPNext:

```python
regional_overrides = {
    "France": {
        "erpnext.tests.test_regional.test_method": "erpnext.regional.france.utils.test_method",
    },
    "United Arab Emirates": {
        "erpnext.controllers.taxes_and_totals.update_itemised_tax_data":
            "erpnext.regional.united_arab_emirates.utils.update_itemised_tax_data",
        "erpnext.accounts.doctype.purchase_invoice.purchase_invoice.make_regional_gl_entries":
            "erpnext.regional.united_arab_emirates.utils.make_regional_gl_entries",
    },
    "Italy": {
        "erpnext.controllers.taxes_and_totals.update_itemised_tax_data":
            "erpnext.regional.italy.utils.update_itemised_tax_data",
    },
}
```

**Implicación para nuestra app**: en vez de reescribir controladores de Sales Invoice / Purchase Invoice / Payment Entry, identificamos qué puntos del core ya están marcados como regionalizables (`get_itemised_tax_breakup_header`, `make_regional_gl_entries`, etc.) y registramos nuestras propias implementaciones para `"Spain"` en el `regional_overrides` de nuestra app. Si un punto que necesitamos NO está ya decorado con `@allow_regional` en el core, no podemos enganchar ahí con este mecanismo — hay que usar `doc_events` u otro hook en su lugar (ver punto 2).

**Tarea para agentes**: auditar qué funciones del core de ERPNext ya están decoradas con `@allow_regional` (buscar el decorador en el código fuente) y hacer un mapeo de cuáles nos sirven directamente para: impuestos (punto 7 del documento maestro), asientos contables regionales (retenciones, punto 9), y desgloses de factura.

### Confirmación con capturas reales de la charla: el lado del "core" y el lado de India Compliance

Estas dos diapositivas de la charla muestran los dos lados exactos del mismo mecanismo.

**Lado core** — así se ve el decorador aplicado a una función del propio ERPNext (ejemplo real, `payment_reconciliation.py`):

```python
@erpnext.allow_regional
def adjust_allocations_for_taxes(doc):
    pass
```

Es decir: el core define la función con un cuerpo vacío (`pass`) marcado como punto de extensión, y deja que sea la app regional quien aporte la implementación real.

**Lado India Compliance** — el `regional_overrides` real y completo tal como aparece en su `hooks.py` (más extenso que el ejemplo genérico que ya teníamos, y confirma el patrón de nombrado `ruta.completa.origen: ruta.completa.override`):

```python
regional_overrides = {
    "India": {
        "erpnext.controllers.taxes_and_totals.get_regional_round_off_accounts": (
            "india_compliance.gst_india.overrides.transaction.get_regional_round_off_accounts"
        ),
        "erpnext.controllers.accounts_controller.update_gl_dict_with_regional_fields": (
            "india_compliance.gst_india.overrides.gl_entry.update_gl_dict_with_regional_fields"
        ),
        "erpnext.controllers.accounts_controller.get_advance_payment_entries_for_regional": (
            "india_compliance.gst_india.overrides.payment_entry.get_advance_payment_entries_for_regional"
        ),
        "erpnext.controllers.buying_controller.update_regional_item_valuation_rate": (
            "india_compliance.gst_india.overrides.ineligible_itc.update_valuation_rate"
        ),
        "erpnext.accounts.doctype.payment_reconciliation.payment_reconciliation.adjust_allocations_for_taxes": (
            "india_compliance.gst_india.overrides.payment_entry.adjust_allocations_for_taxes_in_payment_reconciliation"
        ),
    },
}
```

**Lectura para nuestra app**: el patrón de nombrado de módulos de India Compliance es `<app>.<módulo_país>.overrides.<área>.<función>` (ej. `india_compliance.gst_india.overrides.gl_entry.update_gl_dict_with_regional_fields`). Deberíamos adoptar una convención equivalente, por ejemplo `<nuestra_app>.spain.overrides.<área>.<función>` (`...overrides.gl_entry...`, `...overrides.payment_entry...`, `...overrides.transaction...`), para que el mapeo sea inmediatamente legible y coherente con el ecosistema.

## 2. `doc_events`: enganchar el ciclo de vida de documentos

Donde no hay un punto `@allow_regional` disponible, el patrón estándar (usado también por India Compliance para GST, e-invoice, etc.) es `doc_events` en `hooks.py`:

```python
doc_events = {
    "Sales Invoice": {
        "validate": "custom_app.overrides.sales_invoice.validate",
        "on_submit": "custom_app.overrides.sales_invoice.on_submit",
    },
    "Purchase Invoice": {
        "before_save": "custom_app.overrides.purchase_invoice.calculate_retencion",
    },
}
```

Esto es lo que usaremos para: generación del registro VeriFactu al emitir factura, cálculo de retenciones IRPF, validaciones de NIF-IVA, etc.

> **Orden de ejecución verificado en Frappe v16** (`Document.hook.compose`, `frappe/model/document.py`): el método del controller del core corre SIEMPRE primero y los handlers de `doc_events` después, en la misma llamada. Implicaciones: (1) es estructuralmente imposible saltarse la lógica del core (un `override_doctype_class` que olvide `super().on_submit()` sí puede — se detectó ese defecto exacto en la app de referencia); (2) los handlers ven el documento DESPUÉS de la lógica del core de ese evento, pero ANTES del siguiente evento del ciclo (p.ej. un handler `before_submit` corre antes de que el core escriba el documento y ejecute su `on_submit`).

**Ejemplo real de India Compliance** (confirma el patrón anterior, enganchando `GL Entry`):

```python
doc_events = {
    "GL Entry": "some_custom_function"
}
```

Y el cuerpo típico de una función de validación enganchada así — nótese el patrón de "salir pronto si no aplica" seguido de una validación dura con `frappe.throw` cuando sí aplica:

```python
def validate(doc, method=None):
    if doc.company_gstin or not is_indian_registered_company(doc):
        return

    gst_accounts = get_all_gst_accounts(doc.company)
    if doc.account not in gst_accounts:
        return

    frappe.throw(
        _(
            "Company GSTIN is a mandatory field for accounting of GST Accounts."
            " Run `Update GSTIN` patch from GST Balance Report to update GSTIN in all transactions."
        )
    )
```

**Aplicación para nosotros**: este es el molde a seguir para nuestras propias validaciones de campo obligatorio — por ejemplo, exigir NIF-IVA en operaciones intracomunitarias, o exigir que el certificado VeriFactu esté configurado antes de permitir el envío de una factura. Dos detalles a replicar: (1) las condiciones de salida temprana (`return`) van primero y son baratas de evaluar; (2) el mensaje de error en `frappe.throw` no solo dice qué falta, sino que indica el remedio concreto (qué patch o acción ejecutar) — no un error genérico.

## 3. `override_doctype_class` vs. `extend_doctype_class`

Dos mecanismos distintos, con implicaciones de diseño distintas:

- **`override_doctype_class`**: sustituye completamente la clase Python de un DocType. Lo usa el propio ERPNext para extender clases de Frappe (ej. `Address`). Si dos apps intentan hacer `override_doctype_class` sobre el mismo DocType, hay conflicto.
- **`extend_doctype_class`**: añade mixins a la clase ya (potencialmente) sobreescrita. Es el mecanismo recomendado cuando **solo necesitamos añadir funcionalidad** (campos virtuales, propiedades calculadas, métodos nuevos) sin reemplazar el comportamiento existente — y es compatible con que otras apps hagan lo mismo.

**Decisión de diseño para nuestra app**: usar `extend_doctype_class` por defecto sobre los DocTypes de ERPNext (Sales Invoice, Purchase Invoice, Payment Entry, Account...) y reservar `override_doctype_class` solo si es estrictamente necesario, precisamente para no bloquear la coexistencia con otras apps de terceros que el cliente pueda instalar.

La propia charla lo remarca explícitamente en el título de la diapositiva correspondiente: **"Class Overrides — Use only if necessary"**, con este ejemplo real de India Compliance (usado para su funcionalidad de audit trail, un caso genuinamente excepcional que sí requiere reemplazar la clase completa):

```python
override_doctype_class = {
    "Customize Form": ("india_compliance.audit_trail.overrides.customize_form.CustomizeForm"),
}
```

Confirma la regla: incluso el propio India Compliance, que sí usa `override_doctype_class`, lo hace en un único caso muy puntual (Customize Form, para su feature de audit trail) y no como mecanismo por defecto. Para nuestra app, el criterio debería ser el mismo — reservarlo para casos donde de verdad no hay alternativa con `extend_doctype_class` o `doc_events`.

## 4. Custom Fields y Fixtures, no forks

Los campos específicos de España (NIF-IVA, tipo de retención, mandato SEPA, etc.) se añaden como **Custom Fields** definidos vía **fixtures**, exportables a JSON y versionables en el repo de la app — nunca editando directamente el DocType core.

Flujo estándar:
1. Crear el Custom Field desde la UI en un bench de desarrollo.
2. Exportarlo como fixture (`bench --site <site> export-fixtures` o declarándolo en `hooks.py` con `fixtures = [...]`).
3. Versionarlo en el repo de la app para que se instale automáticamente en cualquier bench donde se instale la app.

## 5. Un DocType de "Settings" tipo Single por bloque funcional

> **Revisión posterior (decisión de producto, ver maestro)**: el esquema adoptado es un híbrido — `SC Settings` (Single hub) para lo genérico/global de cada funcionalidad en secciones, y lo por-empresa en un tab "Spain Compliance" del doctype Company (Custom Fields + child tables + `doc_events`). El espíritu anti-monolito de este punto se preserva por el eje global vs per-company.

Patrón observado en ERPNext (`Accounts Settings`, `Stock Settings`, `Buying Settings`) y replicado por India Compliance para su configuración (endpoints de API, credenciales, features on/off). Para nuestra app, en vez de un único DocType de configuración masivo, conviene un Single por bloque:

- `Spain Compliance Settings` (o similar) para lo transversal (certificado digital, modo test/producción).
- Configuración específica anidada donde tenga sentido (ej. credenciales SII separadas de VeriFactu, aunque compartan el certificado).

Esto es coherente con la decisión pendiente ya anotada en el documento maestro sobre "estrategia de configuración".

## 6. Estructura de módulos: un submódulo por funcionalidad, no un monolito

India Compliance separa claramente GST e-Invoice, e-Way Bill, GSTR-1, reconciliación GSTR-2A/2B como áreas funcionales independientes dentro de la misma app, cada una con sus propios DocTypes, reports y lógica — no todo mezclado en un único módulo "India".

**Aplicado a nuestra app**: cada fichero de funcionalidad del documento maestro (plan contable, SEPA, Norma 43, VeriFactu, SII, eFactura, impuestos, informes IVA, retenciones, facturación masiva) debería mapear a su propio submódulo Frappe dentro de la app, con naming consistente. Facilita mantenimiento, testing aislado, y activar/desactivar funcionalidades por cliente si en el futuro se empaqueta comercialmente.

## 7. Scheduler events para sincronización con APIs externas

Para llamadas periódicas a servicios externos (comprobación de estado de envíos SII, refresco de validación VIES, reintentos de envío a VeriFactu), usar `scheduler_events` en `hooks.py` en vez de lógica ad-hoc:

```python
scheduler_events = {
    "hourly": ["custom_app.tasks.retry_pending_sii_submissions"],
    "daily": ["custom_app.tasks.sync_verifactu_status"],
}
```

## 8. Dependencias de app: `required_apps`

Declarar en `hooks.py` de qué apps depende la nuestra, para que `bench` resuelva la instalación en el orden correcto:

```python
required_apps = ["frappe/erpnext"]
```

Esto asegura que ERPNext (y su versión mínima, ver punto 10) esté presente antes de instalar nuestra app de localización.

## 9. Dependencias condicionales entre apps de terceros (`after_app_install`)

Patrón muy relevante para nosotros: cuando el comportamiento debe reaccionar a qué **otras** apps del ecosistema Frappe/ERPNext están instaladas en el mismo site (HRMS, Education, Healthcare...), India Compliance engancha el hook `after_app_install`, que Frappe dispara cada vez que se instala *cualquier* app en el site — no solo la propia:

```python
def after_app_install(app_name):
    if app_name == "hrms":
        create_hrms_custom_fields()

    if app_name == "education":
        create_education_custom_fields()

    if app_name == "healthcare":
        create_healthcare_custom_fields()
```

**Aplicación directa a nuestra app**: si en el futuro queremos, por ejemplo, añadir campos específicos solo cuando el cliente tiene instalado HRMS (retenciones de nóminas, IRPF de trabajadores) o algún módulo de e-commerce de terceros, este es el mecanismo — no una comprobación manual en cada `doc_event`, sino reaccionar una vez, en la instalación, y crear los campos que correspondan según lo que haya presente.

## 10. Versionado y metadatos en `pyproject.toml`

India Compliance fija la compatibilidad de versión con Frappe directamente en `pyproject.toml`, no solo en `hooks.py`:

```toml
[tool.bench.frappe-dependencies]
frappe = ">=17.0.0-dev,<18.0.0"

[project.urls]
Homepage = "https://indiacompliance.app/"
Repository = "https://github.com/resilient-tech/india-compliance"
"Bug Reports" = "https://github.com/resilient-tech/india-compliance/issues/newtemplate=bug_report.yaml"
```

**Aplicación para nosotros**: fijar desde el principio en `pyproject.toml` el rango de versiones de Frappe/ERPNext soportado (decisión transversal ya pendiente en el documento maestro), y los mismos metadatos de proyecto (homepage, repo, plantilla de bug report) para que la app sea instalable y mantenible igual que cualquier app seria del ecosistema.

## 11. Creación de Custom Fields: patrón exacto de código

El helper estándar es `create_custom_fields` de `frappe.custom.doctype.custom_field.custom_field`, invocado típicamente desde `after_install`:

```python
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def after_install():
    create_custom_fields({
        "Bank Transaction Payments": [
            {
                "fieldname": "reconciliation_type",
                "fieldtype": "Select",
                "label": "Reconciliation Type",
                "options": "Matched\nVoucher Created",
                "insert_after": "clearance_date",
                "read_only": 1,
                "default": "Matched",
            }
        ],
    })
```

Esto confirma y concreta el punto 4 (Custom Fields vía fixtures) del apartado anterior de este documento: en la práctica, el patrón preferido no es solo exportar fixtures desde la UI, sino **declarar los Custom Fields directamente en código Python** dentro de `after_install`, con la estructura `{"DocType": [ {campo...}, ... ]}`. Esto tiene una ventaja importante sobre las fixtures JSON: es más fácil de revisar en un PR, de mantener versionado junto a la lógica que depende de ese campo, y de generar/mantener con ayuda de agentes.

## 12. Limpieza de Custom Fields al desinstalar

Contrapartida necesaria del punto anterior: si la app crea campos en la instalación, debe limpiarlos en la desinstalación. Patrón de India Compliance:

```python
def delete_custom_fields(custom_fields):
    """
    :param custom_fields: a dict like `{'Sales Invoice': [{fieldname: 'test', ...}]}`
    """
    for doctypes, fields in custom_fields.items():
        if isinstance(fields, dict):
            # only one field
            fields = [fields]

        if isinstance(doctypes, str):
            # only one doctype
            doctypes = (doctypes,)

        for doctype in doctypes:
            frappe.db.delete(
                "Custom Field",
                {"fieldname": ("in", [field["fieldname"] for field in fields])},
            )
```

**Aplicación para nosotros**: cualquier Custom Field que añadamos (NIF-IVA, mandato SEPA, tipo de retención, campos VeriFactu/SII) debe tener su contrapartida de limpieza en `before_uninstall`/`after_uninstall`. Esto es especialmente importante en nuestro contexto multi-cliente (bench compartido con ~18 instancias): una desinstalación limpia evita dejar basura de campos huérfanos en benches que ya no usan la app.

## 13. Print Formats vía Property Setter, no hardcoding

Para fijar el print format por defecto de un DocType (ej. que "Sales Invoice" use automáticamente nuestro formato de factura española en vez del genérico), el patrón correcto no es tocar el DocType, sino un `frappe.make_property_setter`:

```python
# print format
frappe.make_property_setter(
    {
        "doctype": "Sales Invoice",
        "doctype_or_field": "DocType",
        "property": "default_print_format",
        "value": "GST Tax Invoice",
    },
    validate_fields_for_doctype=False,
    is_system_generated=False,
)
```

**Aplicación para nosotros**: usar este mismo patrón para fijar, por ejemplo, que el print format por defecto de Sales Invoice sea nuestro formato con QR de VeriFactu, sin tocar el DocType core ni depender de que el usuario lo seleccione manualmente. `is_system_generated=False` es importante — marca el property setter como creado por una app/usuario, no por el propio framework, lo cual afecta a cómo Frappe lo trata en actualizaciones.

## 14. Extender utilidades de impresión vía métodos Jinja

Para exponer funciones Python como helpers utilizables directamente dentro de las plantillas Jinja de los Print Formats (imprescindible para cosas como generar el QR de VeriFactu, calcular el desglose de IVA por tipo, o formatear el IBAN en la plantilla de factura), el hook es `jinja.methods` en `hooks.py`:

```python
jinja = {
    "methods": [
        "india_compliance.gst_india.utils.get_state",
        "india_compliance.gst_india.utils.jinja.add_spacing",
        "india_compliance.gst_india.utils.jinja.get_supply_type",
        "india_compliance.gst_india.utils.jinja.get_sub_supply_type",
        "india_compliance.gst_india.utils.jinja.get_e_waybill_qr_code",
        "india_compliance.gst_india.utils.jinja.get_qr_code",
        "india_compliance.gst_india.utils.jinja.get_transport_type",
        "india_compliance.gst_india.utils.jinja.get_transport_mode",
        "india_compliance.gst_india.utils.jinja.get_e_waybill_document_type",
        "india_compliance.gst_india.utils.jinja.get_ewaybill_barcode",
        "india_compliance.gst_india.utils.jinja.get_e_invoice_item_fields",
        "india_compliance.gst_india.utils.jinja.get_e_invoice_amount_fields",
        "india_compliance.gst_india.utils.jinja.get_gst_breakup",
    ],
}
```

Cada entrada queda disponible en cualquier plantilla de Print Format como una función Jinja normal (ej. `{{ get_gst_breakup(doc) }}`), sin tener que precalcular esos valores en Python antes de renderizar.

**Aplicación directa para nuestra app**: este es exactamente el mecanismo para el QR de VeriFactu (punto 4 del documento maestro) y para el desglose de IVA en la plantilla de factura (punto 8, informes de IVA) — necesitamos algo como `get_verifactu_qr_code`, `get_iva_breakup`, `format_iban` expuestos como métodos Jinja propios, siguiendo la misma convención de nombrado por submódulo (`<nuestra_app>.spain.utils.jinja.<función>`).

## 16. Monkey Patching → "Nope"

Diapositiva con título y respuesta explícitos: **"Monkey Patching — Nope."** Es una regla negativa directa: no reasignar en caliente atributos/funciones de módulos del core como mecanismo de extensión, ni siquiera cuando parece más rápido que registrar un hook formal.

Ejemplo real de la charla, mostrado precisamente como **antipatrón** (monkey patching de una función de setup de impuestos china sobre el módulo `taxes_setup` del core):

```python
import frappe
from erpnext.setup.setup_wizard.operations import taxes_setup
from erpnext.setup.setup_wizard.operations.taxes_setup import setup_taxes_and_charges


def erpnext_china_setup_taxes_and_charges(company_name: str, country: str):
    chart_of_accounts = frappe.db.get_value("Company", company_name, "chart_of_accounts")
    china_coa = ["一般企业会计准则(2024)", "小企业会计准则(2024)", "小企业会计准则", "民间非营利组织会计制度(2025)"]
    if chart_of_accounts and chart_of_accounts in china_coa and country == "China":
        return

    setup_taxes_and_charges(company_name, country)


taxes_setup.setup_taxes_and_charges = erpnext_china_setup_taxes_and_charges
```

La última línea (`taxes_setup.setup_taxes_and_charges = erpnext_china_setup_taxes_and_charges`) es el monkey patch: reasigna directamente el atributo del módulo del core en tiempo de importación, sin pasar por ningún hook de Frappe. Es exactamente lo que la charla señala como práctica a evitar.

**Por qué es un problema real para nosotros**: un monkey patch de este tipo depende de la ruta interna exacta del módulo/función del core en la versión concreta de ERPNext instalada. Si el core cambia esa ruta o firma en una actualización, el patch se rompe silenciosamente o, peor, deja de aplicarse sin error visible. Con `regional_overrides`/`doc_events`/`extend_doctype_class`, Frappe median el acoplamiento a través de un hook declarado, con más superficie de compatibilidad hacia adelante.

**Regla para la app**: si nos encontramos escribiendo `modulo.funcion = nuestra_funcion` en cualquier punto del código, es señal de que estamos violando este principio — hay que buscar el hook correcto (`@allow_regional`, `doc_events`, `extend_doctype_class`, `jinja.methods`, etc.) en vez de reasignar directamente.

## 17. Otros hooks a considerar: exclusión de DocTypes en limpieza de compañía y en borrado en cascada

Tres hooks adicionales, poco vistosos pero relevantes en un contexto multi-cliente como el nuestro:

```python
# DocTypes to be ignored while clearing transactions of a Company
company_data_to_be_ignored = ["GST Account", "GST Credential"]

# Links to these doctypes will be ignored when deleting a document
ignore_links_on_delete = ["e-Waybill Log", "e-Invoice Log"]

accounting_dimension_doctypes = ["Bill of Entry", "Bill of Entry Item"]
```

- **`company_data_to_be_ignored`**: cuando ERPNext ofrece la utilidad de "borrar todas las transacciones de una Company" (útil en entornos de pruebas/demo), esta lista excluye DocTypes de configuración/credenciales que NO deben borrarse junto con las transacciones. **Aplicación para nosotros**: nuestros DocTypes de configuración y credenciales (certificado VeriFactu/SII, configuración SEPA del banco) deberían declararse aquí, para que un reseteo de datos de prueba en un bench cliente no destruya la configuración de cumplimiento normativo.
- **`ignore_links_on_delete`**: evita que Frappe bloquee el borrado de un documento solo porque existe un log histórico enlazado (ej. logs de envío a SII/VeriFactu). **Aplicación para nosotros**: nuestros logs de envío (registro VeriFactu, log de envío SII, log de remesa SEPA) deberían ir aquí si no queremos que impidan borrar la factura o el pago original en escenarios legítimos de corrección.
- **`accounting_dimension_doctypes`**: declara DocTypes adicionales que participan en las dimensiones contables de ERPNext (más allá de los estándar). Relevante si en algún momento el plan contable español (punto 1 del maestro) necesita una dimensión propia que no es una Cost Center ni un Project estándar.

## 18. Comprobación de permisos explícita para llamadas a servicios de terceros

Patrón obligatorio para cualquier endpoint whitelisted que llame a un servicio externo (justo nuestro caso con SII, VeriFactu, VIES, bancos):

```python
@frappe.whitelist()
def call_third_party_service(params: dict):
    """
    Call a third party service (for e.g. e-invoicing/tax filing)
    """

    # Check for permissions
    if not has_permission():
        frappe.throw(_("You do not have permission to call this third party service"), frappe.PermissionError)
```

**Aplicación directa para nosotros**: cada endpoint whitelisted que dispare una llamada real a la AEAT (SII, VeriFactu) o a un banco (SEPA) debe verificar permisos explícitamente al principio de la función — no basta con la protección estándar de `@frappe.whitelist()`, porque estas llamadas tienen coste (en el caso de India Compliance, las APIs de GST son de pago) y consecuencias legales/fiscales reales si se disparan sin autorización adecuada. Esto conecta directamente con la pregunta ya abierta en el fichero de VeriFactu sobre gestión de certificado multi-empresa — el chequeo de permisos debe considerar de qué Company/certificado se trata, no solo si el usuario tiene un rol genérico.

## 19. Otras buenas prácticas de código a nivel de framework

Tres reglas sueltas pero explícitas de la charla, con impacto directo en cómo deben escribir código los agentes:

- **No usar SQL crudo vía `frappe.db.sql`** — usar el ORM de Frappe (`frappe.get_all`, `frappe.qb`, métodos de documento) salvo necesidad justificada de rendimiento, y en ese caso, revisar cuidadosamente el escapado de parámetros.
- **Añadir type hints a todos los endpoints whitelisted** — como en el ejemplo del punto 18 (`params: dict`), para que la validación de tipos y la legibilidad para agentes/revisores sean mejores desde el principio.
- **Evitar commits explícitos con `frappe.db.commit`** — Frappe gestiona el ciclo de commit/rollback por request; forzar un commit manual rompe esa gestión transaccional y puede dejar estado inconsistente si algo falla después en el mismo request.

**Aplicación para nosotros**: estas tres reglas deberían ir en cualquier guía de estilo/instrucciones que demos a los agentes que generen código para la app, junto con las convenciones de nombrado de módulos ya establecidas en los puntos anteriores.

## 20. Testing y CI como parte del diseño, no un añadido

India Compliance mantiene tests de servidor con cobertura medida (Codecov) y CI en GitHub Actions desde el principio. Dado que vamos a trabajar con agentes generando código, esto es más importante todavía: cada funcionalidad nueva (generación de un XML, cálculo de una retención, parseo de Norma 43) debería llevar tests unitarios desde el primer commit, no al final.

## Resumen de decisiones de arquitectura para el documento maestro

Estas conclusiones deberían incorporarse a las "Decisiones transversales" del documento maestro:

- Mecanismo de extensión por defecto: `@allow_regional` donde el core ya lo soporte → `doc_events` donde no → nunca editar el core directamente.
- `extend_doctype_class` por defecto; `override_doctype_class` solo si es imprescindible.
- Custom Fields declarados en código Python vía `create_custom_fields` en `after_install`, con su `delete_custom_fields` correspondiente en desinstalación — no solo fixtures JSON sueltas.
- Un Single DocType de Settings por bloque funcional, no uno monolítico.
- Un submódulo Frappe por funcionalidad (que se corresponda con los ficheros 01-11 del documento maestro).
- Sincronizaciones periódicas con AEAT/bancos vía `scheduler_events`, con lógica de reintento explícita.
- `required_apps = ["frappe/erpnext"]` y versión mínima fijada en `pyproject.toml` (`tool.bench.frappe-dependencies`).
- `after_app_install(app_name)` para reaccionar condicionalmente si el cliente tiene instaladas otras apps del ecosistema (HRMS, etc.), en vez de comprobaciones manuales dispersas.
- Print formats por defecto vía `frappe.make_property_setter`, no hardcodeados ni dejados a selección manual del usuario.
- Convención de nombrado de módulos tipo `<nuestra_app>.spain.overrides.<área>.<función>` y `<nuestra_app>.spain.utils.jinja.<función>`, calcada de `india_compliance.gst_india.overrides.*` / `...utils.jinja.*`.
- Funciones helper para Print Formats (QR VeriFactu, desglose de IVA, formato IBAN) expuestas vía el hook `jinja.methods`, no precalculadas en Python antes de renderizar.
- `override_doctype_class`: confirmado como excepcional incluso en India Compliance (un único caso, Customize Form/audit trail) — no usar como mecanismo por defecto.
- **Nunca monkey patching** (reasignar atributos de módulos del core en tiempo de importación) — usar siempre el hook formal correspondiente.
- Declarar nuestros DocTypes de configuración/credenciales en `company_data_to_be_ignored`, nuestros logs de envío (SII/VeriFactu/SEPA) en `ignore_links_on_delete`, y cualquier dimensión contable adicional en `accounting_dimension_doctypes`.
- Toda llamada a un servicio de terceros (SII, VeriFactu, VIES, bancos) desde un endpoint whitelisted debe comprobar permisos explícitamente al principio de la función, considerando de qué Company/certificado se trata.
- No usar `frappe.db.sql` crudo salvo necesidad justificada; type hints en todos los endpoints whitelisted; nunca `frappe.db.commit` explícito.
- Tests desde el primer commit de cada funcionalidad.

## Fuente

Puntos 8-20 de este documento están tomados directamente de capturas de la charla "Building Compliance Software" (Nikhil Kothari, Frappe Build) aportadas por Alberto, y contrastados/ampliados contra el patrón ya verificado de `resilient-tech/india-compliance`. Los ejemplos reales de `regional_overrides`, `doc_events`, `override_doctype_class` y el decorador `@erpnext.allow_regional` en los puntos 1-3 también proceden de esas capturas y sustituyen a los ejemplos genéricos usados en la primera versión de este documento. El resto (4-7) provienen de la revisión directa del código fuente de `frappe/erpnext` y la documentación de hooks de Frappe.

## Pendiente

- [ ] Si aparecen más capturas o notas de la charla, seguir ampliando este documento.
- [ ] Confirmar si algún repo propio ya sigue (o contradice) alguno de estos patrones, para no tener que migrar código ya escrito.
