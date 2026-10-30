# 14. Verificador de NIF/CIF (transversal)

[← Volver al índice](00-maestro.md)

## Objetivo

Validar formato y dígito/letra de control de los números de identificación fiscal españoles (NIF de persona física, NIE de extranjeros, NIF/CIF de entidades) **en el punto de entrada de datos** (Customer, Supplier, Company) y como **última compuerta antes de generar registros AEAT** (Sales Invoice en VeriFactu, y en el futuro Purchase/Sales en SII), evitando de raíz la clase entera de rechazos AEAT por NIF mal formado.

## Contexto normativo / técnico

- **NIF persona física (DNI)**: 8 dígitos + letra de control, `"TRWAGMYFPDXBNJZSQVHLCKE"[número % 23]`.
- **NIE (extranjeros residentes)**: X/Y/Z + 7 dígitos + letra; X→0, Y→1, Z→2 como prefijo numérico, luego el mismo algoritmo mod-23.
- **NIF/CIF de entidad**: letra de organización (`A B C D E F G H J N P Q R S U V W`) + 7 dígitos + control. El control NUMÉRICO es **Luhn** sobre los 7 dígitos; si el control es LETRA, se toma de `'JABCDEFGHI'[dígito_luhn]` — **NO** la tabla mod-23 del DNI (error común al implementarlo de memoria). Nota: las fuentes oficiales discrepan históricamente sobre qué tipos de entidad llevan control letra vs dígito; la referencia de implementación acepta ambos.
- **NIFs extranjeros** (formato IVA intracomunitario etc.): fuera del alcance de este verificador — son territorio de 07 (enrutamiento fiscal + VIES).

## Alcance

- Utilidad transversal de validación de NIF español (formato + control) usada por: 04 (VeriFactu — última compuerta en Sales Invoice), 05 (SII — ídem cuando exista), 07 (detección de "NIF español" para enrutamiento de impuestos), y validación en ciclo de vida de terceros y compañía.
- Validación en `validate` de Customer y Supplier: si `tax_id` presente Y (patrón español O país España) → debe ser válido.
- Validación en `validate` de Company (España + `tax_id` presente → válido) + compuerta en activación VeriFactu (presente, único, **válido**).
- Report "SC NIF Checkup": higiene de datos pre-go-live (terceros/company con NIF ausente o inválido).
- Configurable en `SC Settings`: modo de validación en terceros (`Bloquear` | `Solo avisar`).

Fuera de alcance v1: validación de NIFs extranjeros contra su formato nacional (→ 07 con stdnum por país), VIES (→ 07, ver abajo), y validación contra el censo AEAT ("Validación de NIF" — posible futuro driver sobre la capa 13, no requerido: la AEAT no rechaza registros VeriFactu por destinatario inexistente en censo, solo por mal formados).

### Servicios web de validación existentes (verificado)

**VIES (Comisión Europea)** — WSDL verificado (`checkVatService`):
- Operaciones: `checkVat` (countryCode + vatNumber → `valid` + nombre/dirección opcionales) y `checkVatApprox` (además compara datos del operador y devuelve códigos de match `VALID/INVALID/NOT_PROCESSED` + `requestIdentifier` — identificador de consulta).
- Sin certificado; SOAP (y existe API REST); con rate-limits documentados en los faults: `GLOBAL_MAX_CONCURRENT_REQ`, `MS_MAX_CONCURRENT_REQ`, `MS_UNAVAILABLE`, `TIMEOUT` → **caching obligatorio** en quien lo use.
- **Restricción legal de uso** (texto del propio WSDL, art. 31 Reglamento 904/2010): solo para verificar operaciones intracomunitarias — cualquier otro uso y la retransmisión están prohibidos. No usar VIES como verificador general de NIFs.
- **Limitación de cobertura**: VIES solo contiene los NIFs registrados en el ROI (operadores intracomunitarios) — un NIF español corriente no registrado para operaciones intracomunitarias NO aparece como válido. VIES no es, ni puede ser, el validador doméstico español.

**Validación de NIF contra censo (AEAT)**: el servicio de consulta de datos de identificación existe históricamente (requiere certificado, orientado a KYC). Los dominios de documentación originales (`www.agenciatributaria.gob.es` / `.es`) se cerraron el 13-12-2022 en favor de `sede.agenciatributaria.gob.es` — verificar endpoint/condiciones actuales contra la nueva sede si se decide implementar (driver futuro sobre la capa 13).

**Estrategia de capas** (por qué no todo online): local stdnum = captura typos en origen (gratis, instantáneo, offline — la clase de rechazo que VeriFactu penaliza); VIES = existencia intracomunitaria (07, con cache + guardar `requestIdentifier` como evidencia de diligencia en exenciones intracomunitarias); censo AEAT = opcional futuro. Cada capa responde a un problema distinto.

## Estado actual / referencias

- La referencia (`spanish_compliance`) NO tiene validador de NIF: solo exige **presencia** del NIF al generar el registro (línea de deuda añadida en 04). No se reutiliza nada de ahí.
- **Decisión de dependencia**: usar `python-stdnum` (`stdnum.es.nif/nie/cif`, `stdnum.es.vat` dispatcher) — verificada como la implementación a la que el propio **core de Odoo delega** la validación española (`base_vat/models/res_partner.py` → `stdnum.util.get_cc_module('es', 'vat')`). Librería pura-Python, mantenida, con la tabla de control del CIF implementada (incluida la leniencia "acepta dígito o letra" documentada en su fuente). Nunca algoritmo casero para esto.
- Se añade `stdnum` (rango fijado, ej. `>=1.19`) a `[project] dependencies` de `pyproject.toml` de la app.

## Diseño técnico propuesto

### 1. Módulo

```
spain_compliance/nif/
├── validator.py   # puro (importable sin frappe): wrappers sobre stdnum
└── party.py       # doc_events de Customer/Supplier/Company (frappe glue)
```

`validator.py` (funciones puras, testeables sin site):
- `validate_spanish_tax_id(tax_id) -> ValidatedTaxID` — compacta, valida vía stdnum, devuelve tipo detectado (`dni`/`nie`/`cif`), número normalizado; lanza `InvalidTaxID(tipo_error)` con mensajes preparados.
- `looks_spanish(tax_id) -> bool` — detección por patrón (8+letra, X/Y/Z+7+letra, letra-org + 7 + control) para decidir si aplicar validación española.
- Errores con remedio (doc 12 §2): "La letra de control no coincide: ¿quisiste decir `X`?" — el validador puede sugerir la letra correcta calculada (feedback inmediato del typo típico).

### 2. Puntos de validación

| Punto | Regla | Efecto |
|---|---|---|
| `Customer.validate` / `Supplier.validate` (doc_event) | `tax_id` presente Y (`looks_spanish` O país==España) → `validate_spanish_tax_id` | throw (modo `Bloquear`, default) o msgprint (`Solo avisar`, configurable en SC Settings). NIF **ausente no bloquea** (se captura en la compuerta de la factura) — minimiza el dolor en imports de datos legacy |
| `Company.validate` (doc_event) | país España + `tax_id` presente → válido | throw con remedio |
| Activación VeriFactu (04 §2.1) | NIF presente + único entre companies + **válido** | throw |
| `Sales Invoice.validate` (04 §4.2 — companies VeriFactu, no-POS) | `company_tax_id` y `tax_id` del cliente válidos (presencia ya la exigía la referencia; ahora también validez) | throw |

### 3. Report "SC NIF Checkup"

Query report: Customers/Suppliers/Companies con NIF ausente o inválido (patrón español), con el tipo de defecto (formato / letra de control / ausente). Es la lista de tareas ANTES de activar VeriFactu en una empresa (higiene de go-live). Enlazado desde el flujo de activación en docs (tarea).

### 4. Cumplimiento del patrón 12

- `doc_events` para Customer/Supplier/Company (sin overrides).
- Funciones puras separadas de la capa frappe → tests unitarios sin site (doc 12 §20).
- Mensajes de error con remedio; early-exits baratos (nada de patrón español → return).
- Config en `SC Settings` (hub genérico): `modo_validacion_nif` (`Bloquear` | `Solo avisar`).

### 5. Tests

- Vectores: DNI válido/letra-errónea (con sugerencia de letra correcta), NIE (X/Y/Z), CIF con control dígito, CIF con control letra, CIF letra-org inválida, caso K/L/M (formatos antiguos — ver dudas), ausente→skip, extranjero→skip, país España + NIF raro→throw.
- Doc_events con site de pruebas: customer inválido bloquea (y sugiere letra), modo `Solo avisar` no bloquea, SI last-gate con VeriFactu activo.

## Modelo de nombres de terceros: razón social vs nombre comercial

**`customer_name` / `supplier_name` = razón social (nombre fiscal).** Es la identidad que casa con el NIF en el censo, fluye nativamente a las facturas, y es la que va a TODOS los registros oficiales: `NombreRazon` del destinatario en VeriFactu (ya lo hacía la referencia — verificado en su adapter), contraparte en SII (05), y party naming de Facturae (06). Asunción explícita y documentada — no se crea ningún campo "nombre fiscal" alternativo.

**`sc_nombre_comercial`** (Data, opcional) en **Customer y Supplier**: nombre comercial / marca. Transversal (`sc_`, no `sc_verifactu_` — v1 lo tenía mal scoped). Consumidores definidos (v1 lo creó en Company+Customer y jamás lo usó — código muerto, verificado por grep):
- Print formats vía jinja method (`get_sc_display_name`): patrón típico español "NombreComercial (RazónSocial)" en cabecera + razón social en el bloque legal.
- **Invariante**: NUNCA fluye a registros AEAT/eFactura — solo display.
- Company NO lleva el campo: `company_name` = razón social (asunción documentada — de ahí salen `NombreRazonEmisor` y `Cabecera.ObligadoEmision.NombreRazon`, como en la referencia) y el branding comercial de compañía lo cubre el mecanismo nativo **Letter Head** (cabeceras de impresión) — no duplicamos conceptos del framework.
- Subsanación de destinatario (nombre/NIF): la verdad del sistema es `customer_name` (patrón `_get_system_customer_denominacion_fiscal` de la referencia) — el registro se regenera contra el nombre fiscal, nunca contra el comercial.
- Migración opcional desde v1 (si algún site llenó los campos muertos): patch `sc_verifactu_customer_commercial_name` → `sc_nombre_comercial`.

## Dudas abiertas

- **Formatos antiguos K/L/M** (NIFs personales pre-1995, raros): stdnum no los acepta como CIF. Si aparece un caso real: valorar excepción documentada o bypass puntual. No diseñar para el caso raro ahora.
- ¿Modo `Solo avisar` también para Company, o Company siempre bloqueante? (Recomendación: Company siempre bloqueante — el NIF del emisor es el más crítico del sistema.)

## Tareas para agentes

- [ ] Añadir dependencia `stdnum` a `pyproject.toml` y verificar instalación vía bench.
- [ ] Implementar `nif/validator.py` (wrappers + sugerencia de letra) + tests de vectores.
- [ ] Implementar `nif/party.py` (doc_events Customer/Supplier/Company) + `modo_validacion_nif` en SC Settings + tests.
- [ ] Compuerta en Sales Invoice (04 §4.2) — junto al módulo verifactu.
- [ ] Report "SC NIF Checkup" + enlace en flujo de activación.

## Dependencias con otros specs

- **[04-verifactu.md](04-verifactu.md)** — consumidor principal: última compuerta en Sales Invoice + compuerta de activación.
- **[05-sii.md](05-sii.md)** — mismo verificador para sus registros (emitidas/recibidas — Purchase Invoice necesita NIF de proveedor).
- **[07-impuestos-defecto.md](07-impuestos-defecto.md)** — usa `looks_spanish` como detección para enrutamiento fiscal; NIFs intracomunitarios (formato UE + VIES) son de 07, no de este verificador.
