# 01 — Fundamentos de la app

Fase 0 · Depende de: nada · Bloquea: todas las demás

## Objetivo

Dejar `erpnext_spain` con la estructura, el ciclo de instalación, el mecanismo de activación por compañía y el CI que exigen las reglas del maestro (R1–R12), antes de añadir funcionalidad.

## Alcance

1. Renombrado `spain_compliance` → `erpnext_spain`.
2. Metadatos y dependencias.
3. Módulos y estructura de carpetas.
4. Ciclo de instalación y desinstalación.
5. Configuración por compañía y función de gating.
6. Workspace y onboarding.
7. CI.
8. Correcciones del código base (hallazgos H1–H5 del inventario).

Se parte del código de `ct-Galega/spain_compliance` (rama `version-16`): capa AEAT, verificador de NIF y Verifactu v1 se conservan (maestro D8).

Fuera de alcance: cualquier lógica contable o fiscal (specs 02–07).

## 1. Renombrado

Afecta a:

- Carpeta del paquete Python, `name` en `pyproject.toml`, `app_name` y `app_title` ("ERPNext Spain") en `hooks.py`.
- `modules.txt`, carpetas de módulo y el campo `module` dentro de cada DocType, Report, Workspace, Print Format y Financial Report Template.
- Rutas con puntos en `hooks.py` (`doc_events`, `regional_overrides`, `scheduler_events`, `after_install`…), `patches.txt` e imports.
- Rutas `/assets/<app>/…` en `app_include_js`/`doctype_js`, carpeta `public`, salida del build del frontend, rutas `www`.
- Traducciones, nombre del repo, configuración del CI.
- `app_publisher`, `app_email` y las URLs de `pyproject.toml` (hoy apuntan a `github.com/ctgalega/spain_compliance`).

**Prefijo `SC` → `ES`** en todo el código base, en el mismo paso que el renombrado de la app:

- Doctypes y módulos: `SC Settings` → `ES Settings`, `SC AEAT Credential` → `ES AEAT Credential`, `SC AEAT Response` y su línea, `SC NIF Checkup`, `SC Verifactu` y sus doctypes (`… Billing Record`, `… Notification Role`, `… Aeat Query` y su línea).
- `SC Verifactu Invoice Type` y `SC Verifactu Series` pasan **directamente** a sus nombres finales, `ES Invoice Type` y `ES Invoice Series` (spec 05 §1), igual que sus custom fields (`sc_verifactu_series` → `es_invoice_series`, `sc_verifactu_draft_series` → `es_draft_series`, `sc_verifactu_invoice_type` → `es_invoice_type`, `sc_verifactu_external_rectified_*` → `es_external_rectified_*`), para no renombrarlos dos veces: la numeración fiscal deja de ser de Verifactu ya en esta fase (H1). Pueden quedarse en el módulo `ES Verifactu` hasta que exista `es_facturacion` (spec 05); mover un doctype de módulo es un cambio de código sin datos que migrar.
- Custom fields `sc_*` → `es_*` (69 identificadores en el código base) y la pestaña de Company (`sc_tab` → `es_tab`).
- Carpetas y rutas Python (`sc_verifactu/` → `es_verifactu/`), `modules.txt`, el campo `module` de cada JSON, `hooks.py` (`doc_events`, `jinja`, `doctype_js`, `company_data_to_be_ignored`, `ignore_links_on_delete`, `user_data_fields`), los JS y el print format.
- Sin datos que migrar (maestro D3): se renombra en el código, no con patches.

**Se eliminan**, porque no hay sitios que migrar (maestro D3): los patches que existen para sitios ya instalados (`create_*_module_def`, `rename_spanish_r1`–`r3`, `fix_exempt_cause_options`), y las menciones a la coexistencia con la app v1 `spanish_compliance` en las specs del repo. `patches.txt` arranca vacío.

En sitios de desarrollo: desinstalar la app antigua e instalar `erpnext_spain` desde cero.

**Aceptación**: `grep -ri "spain_compliance"` y `grep -rE '\bSC |\bsc_'` sobre el código del repo (excluida la carpeta `docs/`, que describe el código base con sus nombres antiguos) no devuelven nada; instalación en sitio limpio sin errores; ningún registro con el nombre antiguo en Module Def, Custom Field ni Property Setter; los 259 tests existentes pasan tras el renombrado.

## 2. Metadatos y dependencias

- `hooks.py`: `required_apps = ["frappe/erpnext"]` (ya está así en el código base).
- Dependencias Python del código base que se mantienen: `python-stdnum` (NIF), `zeep` (SOAP AEAT), `segno` (QR). `requires-python >= 3.14`. `zeep>=4.3.3`: el cliente AEAT sirve el WSDL y sus XSD desde `erpnext_spain/schemas` con `forbid_external` activo (H7, §8).
- `pyproject.toml`:

  ```toml
  [tool.bench.frappe-dependencies]
  frappe = ">=16.50.0,<17.0.0"
  erpnext = ">=16.50.0,<17.0.0"
  ```

  La línea de `frappe` sigue el formato que usa ERPNext v16 **[verificado v16]**. La de `erpnext` ya la usa el código base. Hoy declaran `>=16.0.0-dev`: se suben a `>=16.50.0` (maestro D1).
- Ramas `version-16` y `develop`.

## 3. Estructura

Un módulo Frappe por funcionalidad, con prefijo `ES` (maestro §3). Cada módulo tiene su propio `setup.py` con sus custom fields y su limpieza, como ya hacen `nif` y `es_verifactu`.

El **módulo base** es el que crea `bench new-app`: módulo `ERPNext Spain`, carpeta `erpnext_spain/erpnext_spain/`. Sustituye al módulo `Spain Compliance` del código base (carpeta `spain_compliance/spain_compliance/`) y contiene `ES Settings` y lo transversal sin módulo propio. Es la única excepción al prefijo `ES`: lleva el nombre de la app, que ya es único, y así el criterio de aceptación del §1 (`grep spain_compliance` vacío) se puede cumplir.

```
erpnext_spain/
  hooks.py
  install.py                 # orquesta el setup de cada módulo: after_install, after_migrate, before_uninstall, after_app_install
  utils/
    gating.py                # is_pgc_company() y activaciones por funcionalidad, con caché
  erpnext_spain/             # módulo base "ERPNext Spain" (ES Settings); sustituye al módulo "Spain Compliance" del código base
  aeat/                      # existente: capa AEAT (credenciales, cliente SOAP, respuestas, outbox)
  nif/                       # existente: verificador de NIF/CIF
  es_verifactu/              # existente: Verifactu v1
  es_contabilidad/           # nuevo: plan PGC, estados financieros, libros (specs 02, 04)
  es_impuestos/              # nuevo: clasificación, plantillas, datos iniciales (specs 03, 09)
  es_facturacion/            # nuevo: numeración fiscal, rectificativas, cobro (spec 05)
  es_iva/                    # nuevo: Registro Fiscal IVA, libros, liquidación (spec 06)
  es_retenciones/            # nuevo: spec 08
  es_efactura/               # nuevo: spec 10
  es_sepa/                   # nuevo: specs 11 y 12
  es_bancos/                 # nuevo: spec 13
  es_sii/                    # nuevo: spec 14
```

Los nombres de módulo nuevos son una propuesta; lo obligatorio es el prefijo.

## 4. Ciclo de instalación

| Hook | Hace |
|---|---|
| `after_install` | Crea custom fields y property setters. Crea los roles propios si los hay. |
| `after_migrate` | Vuelve a ejecutar la creación de custom fields con `update=True`. Llama a `sync_financial_report_templates()` **[verificado v16]**: es pública y solo inserta las plantillas que no existen. |
| `before_uninstall` | Borra custom fields (`delete_custom_fields`) y property setters propios. No borra datos fiscales generados (el usuario debe exportarlos antes; se avisa en la documentación). |
| `after_app_install` | Si se instala HRMS después, crea los custom fields que dependen de HRMS (R11). |

`hooks.py` declara `company_data_to_be_ignored` con los doctypes de configuración por compañía que defina la app (R8). El Registro Fiscal IVA **no** va en esa lista: debe borrarse con las transacciones.

## 5. Configuración por compañía y gating

Se sigue el esquema del código base: **`ES Settings`** (Single) para lo global de cada funcionalidad, en secciones, y la pestaña **"Spain Compliance"** de Company (`es_tab`, ya existente) para lo de cada empresa, con una sección por funcionalidad. Los campos de abajo van en una sección "Contabilidad y fiscalidad" de esa pestaña (fieldnames finales en inglés con `es_`, maestro §3):

| Campo | Fieldname | Tipo | Uso |
|---|---|---|---|
| `pgc_aplicado` | `es_pgc_applied` | Check, solo lectura | Lo marca la acción "Aplicar plan PGC" (spec 02). Activa lo que depende del plan contable (specs 02–06, 08, 09, 13). |
| `numeracion_fiscal` | `es_fiscal_numbering` | Check | Numeración al emitir y series por tipo de factura (spec 05 §1), con Verifactu o sin él. |
| `modelo_plan` | `es_chart_model` | Select: Normal / PYMES, solo lectura | Plan aplicado. |
| `modelo_cuentas_anuales` | `es_annual_accounts_model` | Select: Normal / Abreviado / PYMES | Plantillas de estados por defecto. |
| `regimen_iva` | `es_vat_regime` | Select: General / Criterio de caja / Recargo de equivalencia / Simplificado | Registro fiscal y modelos. |
| `periodicidad_303` | `es_vat_return_frequency` | Select: Trimestral / Mensual | Modelos. |
| `prorrata_general` | `es_general_prorata` | Percent, vacío = 100 % | Registro fiscal. |
| `exigir_clasificacion_fiscal` | `es_require_tax_classification` | Check | Spec 03. |
| `version_datos_iniciales` | `es_initial_data_version` | Int, solo lectura | Versión de los registros de arranque de la compañía (spec 09 S5). |

Las funcionalidades con conexión a terceros mantienen su propia activación por empresa, como ya hace Verifactu (`es_verifactu_enabled`): SII (`es_sii_enabled`, excluyente con Verifactu, spec 14 §1), factura electrónica, SEPA, conexión bancaria.

Funciones de gating en `utils/gating.py`:

```python
def is_pgc_company(company: str | None) -> bool:
    """True solo si la compañía es de España y tiene el plan PGC aplicado."""

def is_feature_enabled(company: str | None, flag: str) -> bool:
    """True si la compañía tiene activado el flag de esa funcionalidad (p. ej. es_verifactu_enabled)."""
```

- Usan `frappe.get_cached_value` (el código base usa hoy `frappe.db.get_value` en sus salidas tempranas: H5).
- Devuelven `False` sin error si la compañía no existe o los campos aún no están creados (instalación a medias).
- **Todo** `doc_event`, regional override y endpoint de la app llama a la que corresponda como primera instrucción y sale si es `False`.

## 6. Workspace y onboarding

Requisito de la guía de Frappe: un workspace "España" con ajustes, maestros, transacciones, informes y ayuda, y un onboarding paso a paso:

1. Datos fiscales de la compañía (NIF, régimen de IVA).
2. **Aplicar plan PGC** (spec 02).
3. Revisar plantillas de impuestos (spec 03).
4. Configurar series de facturación (spec 05).
5. Primer informe: Balance con plantilla PGC (spec 04).

## 7. CI (GitHub Actions)

| Job | Contenido |
|---|---|
| Lint | `ruff check` y `ruff format --check`; prettier/eslint para JS. |
| Semgrep | Reglas `frappe/semgrep-rules` + reglas propias en `.semgrep/`: (a) prohibir `override_doctype_class` en `hooks.py`; (b) prohibir asignaciones a atributos de módulos importados de `frappe`/`erpnext` (patrón `$MOD.$ATTR = ...`); (c) prohibir `frappe.db.sql(` y `frappe.db.commit(` fuera de `patches/`. |
| Tests | Servicios MariaDB y Redis, bench con Frappe y ERPNext v16 (≥16.50), sitio de pruebas, `bench --site test run-tests --app erpnext_spain`. Incluye los 259 tests existentes. El TODO del código base señala fallos intermitentes por el scheduler durante los tests: en el CI el scheduler va desactivado (`bench --site test disable-scheduler`). Los tests contra la AEAT usan el cliente simulado que ya existe (`aeat/tests/mock_aeat_client.py`); nunca el entorno real. |
| Build | `bench build --app erpnext_spain` si hay frontend. |

El código base no tiene CI (solo pre-commit con ruff, eslint, prettier y pyupgrade): este apartado es nuevo.

## 8. Correcciones del código base

Del inventario (hallazgos H1–H5) y de la primera ejecución de los tests tras el renombrado (H7–H8; H6 es una corrección al TODO del código base, sin cambio de código). Van antes que cualquier funcionalidad nueva.

| Id | Corrección |
|---|---|
| H1 | **Hecho (30/10/2026)** para VeriFactu: el `autoname` solo asigna nombre temporal con `es_verifactu_enabled`; sin él, Frappe aplica la `naming_series`. Un borrador con nombre temporal que se valida tras desactivar VeriFactu recibe el número de su `naming_series` (`invoice.release_draft_name`). Pendiente (spec 05 §1): activar la numeración al emitir con `es_fiscal_numbering` sin VeriFactu, que requiere separar el renombrado a la serie fiscal del módulo VeriFactu. Texto original: La numeración al emitir (nombre temporal del borrador y renombrado a la serie fiscal al validar) solo se aplica en compañías con `numeracion_fiscal` activo. En las demás, el `autoname` no asigna nombre y Frappe sigue con `naming_series` **[verificado: `set_new_name` cae a las opciones de naming si `autoname` no asigna nombre]**. Hoy el nombre temporal se aplica a todas y, sin Verifactu, la factura validada lo conserva (test `test_inactive_company_submit_untouched`). Detalle en spec 05 §1. |
| H2 | **Hecho (30/10/2026)**: `autoname` como `doc_event`; `hooks.py` sin `extend_doctype_class`. Texto original: Quitar `extend_doctype_class` (mixin `SalesInvoiceVerifactuMixin`): el `autoname` pasa a `doc_events = {"Sales Invoice": {"autoname": ...}}`. Frappe lo ejecuta aunque el controlador no defina `autoname`, porque `run_method` compone los `doc_events` del método **[verificado en Frappe v16]**. R2 queda sin excepciones. |
| H3 | **Hecho (30/10/2026)**: los PEM van a `sites/<sitio>/private/es_keys` (fuera de `private/files`), directorio 0700 y ficheros 0600 escritos con `os.open`. Texto original: Clave privada del certificado: hoy `ES AEAT Credential` la escribe sin cifrar en `private/files/<empresa>-<propósito>-key.pem`. Pasa a un directorio propio del sitio fuera de `private/files` (excluido de las copias de ficheros públicos y privados), con permisos `0600`, o a un temporal `0600` por envío. Test que compruebe los permisos. |
| H4 | CI (§7). |
| H5 | **Hecho (31/10/2026)**: `rectify` con `methods=["POST"]`; `es_verifactu/printing.cleanup_printing` borra en `before_uninstall` el Property Setter si sigue apuntando al formato de la app; §4 de `docs/referencia/12-indicaciones-tecnicas.md` corregido. Texto original: `frappe.get_cached_value` en las salidas tempranas; `rectify` solo `POST`; dependencias `>=16.50.0`; borrar en `before_uninstall` el Property Setter del formato de impresión predeterminado; corregir el §4 de la guía técnica del repo, que aún recomienda fixtures. |
| H7 | **Hecho (31/10/2026)**: el WSDL de VeriFactu, sus cinco XSD y `xmldsig-core-schema.xsd` están en `erpnext_spain/schemas` (idénticos a los publicados; xmldsig compartido con Facturae). Con la URL oficial de ES Settings, el cliente carga la copia local y `aeat/wsdl.LocalSchemaTransport` redirige el import de xmldsig a su copia; `forbid_external` sigue activo y la dependencia pasa a `zeep>=4.3.3,<5`. Test `aeat/tests/test_wsdl.py` sin red. Texto original: **`zeep` ≥ 4.3.3 no carga el WSDL de la AEAT** (detectado al ejecutar los tests tras el renombrado). Desde 4.3.3, `Settings(forbid_external=True)` también bloquea los imports transitivos por http(s), y el WSDL de Verifactu importa `xmldsig-core-schema.xsd` de w3.org: falla `test_contrato_wsdl` y, con la misma configuración, el cliente real de `aeat/client.py`. Paliativo aplicado (§2): `zeep>=4.3,<4.3.3`. Corrección definitiva, junto con el CI (H4): incluir en la app los XSD externos que importa el WSDL y resolverlos en local, sin relajar `forbid_external`, y quitar el límite superior. |
| H8 | **Hecho (31/10/2026)**: `erpnext_spain/tests/fixtures.py` crea de forma idempotente la compañía `_Test ES Company` (España, EUR, CIF válido), el cliente `_Test ES Customer`, el artículo `_Test ES Item` y la identidad SIF (solo los campos vacíos); `aeat/tests/helpers.test_company()` los asegura todos y ningún test usa ya datos de demostración ni la primera compañía del sitio. Texto original: **Tests que dependen del estado del sitio** (detectado en el mismo paso). Los tests de Verifactu necesitan el cliente "Palmer Productions Ltd." y el artículo "SKU010" de los datos de demostración de ERPNext, la identidad SIF rellena en `ES Settings`, los índices que crea `after_migrate` y usan la primera compañía del sitio (`aeat/tests/helpers.test_company`). En un CI limpio fallan. Corrección, junto con H4: cada clase crea sus propios datos (compañía española, cliente, artículo, identidad SIF) y no depende de la compañía real del sitio. |

## Criterios de aceptación

1. Instalación y desinstalación en un sitio v16 limpio sin errores ni restos.
2. En un sitio con dos compañías (una española con `pgc_aplicado`, otra de otro país), ningún `doc_event` de la app modifica documentos de la segunda (test explícito).
3. Las reglas Semgrep propias detectan un `override_doctype_class` y un monkey patch introducidos a propósito en un fichero de prueba del CI.
4. El job de tests se ejecuta en cada PR.
5. En una compañía sin `numeracion_fiscal`, una factura validada tiene el nombre de su `naming_series` (H1); el test `test_inactive_company_submit_untouched` se reescribe en ese sentido.
6. `hooks.py` no contiene `extend_doctype_class` ni `override_doctype_class` (H2).
7. El fichero de clave privada tiene permisos `0600` y no está bajo `private/files` (H3).

## Pendiente de verificar

- Que el onboarding de Frappe v16 permita un paso que llame a un endpoint propio (si no, el paso abre el formulario de Company con la acción visible).

## Requisito de instalación

El país del sistema (System Settings) debe ser España. Algunos regional overrides de ERPNext se resuelven por ese país cuando ERPNext no fija la compañía (spec 06 §3). El instalador avisa si no lo es.

