# Registro de decisiones

Decisiones tomadas durante el desarrollo, para revisarlas. Las marcadas **[revisar]** dependen de criterio contable, fiscal o del usuario. Formato: fecha · spec · decisión · alternativas · cómo revertirla.

## Tomadas con el usuario

| Fecha | Spec | Decisión |
|---|---|---|
| 30/10/2026 | 00 A3 | Inventario administrativo: `enable_perpetual_inventory = 0`, regularización al cierre (spec 04 §7). |
| 30/10/2026 | 02 | Opción B: hojas de 4 dígitos (`xxx0` bajo las cuentas de 3 dígitos sin subcuentas). |
| 30/10/2026 | 14 | SII y VeriFactu como dos casillas excluyentes (opción A), con validación en Company y comprobación en tiempo de ejecución. |
| 30/10/2026 | 01 H1 | Sin VeriFactu no hay numeración de borrador; se usa la `naming_series`. |
| 31/10/2026 | 10 | Facturae primero para FACe, subida manual, mismo certificado de la empresa, rectificativas incluidas, doctype propio + campos de solo lectura en la factura. |

## Tomadas por el agente

| Fecha | Spec | Decisión | Alternativas | Revertir |
|---|---|---|---|---|
| 30/10/2026 | 02 | Reparto de ramas alineado con el lado en que los modelos oficiales de balance presentan cada cuenta (406, 437, 1034, 1044, 19, 555, 5595, 5598). **[revisar]** | Reparto de la propuesta inicial de la spec 02. | `ROOT_RULES` en `chart_of_accounts/generate.py` y subir `VERSION`. |
| 30/10/2026 | 02 §3 | Cuentas por defecto: diferencias de cambio 6680, redondeo y cancelación 6590, amortización acumulada 2819, bajas 6710, inmovilizado en curso vacía. **[revisar]** | 7680/7710 según signo; cuentas propias de redondeo. | `DEFAULT_ACCOUNTS` en `es_contabilidad/pgc.py`. |
| 30/10/2026 | 03 | Calificación y exención en un solo campo; E7, E8 y clave 21 no se ofrecen hasta verificarlos. IVA no deducible a la 6310. **[revisar]** | Dos campos separados como en el XSD. | `es_impuestos/codes.py`, `initial_data.py`. |
| 30/10/2026 | 06 | Autorrepercusión de ISP y adquisiciones intracomunitarias con dos filas en la plantilla de compra (+4720 / −4770), sin regional override. **[revisar con el usuario]** | Regional override `make_regional_gl_entries` (depende del país del sistema). | Plantillas de compra en `initial_data.py`. |
| 30/10/2026 | 04 | Cuentas que el modelo PYMES del BOE no recoge, asignadas a la partida más próxima y marcadas en la columna `nota` del mapeo. **[revisar]** | Dejarlas fuera (el balance no cuadraría). | `statements/epigrafe_mapping.csv`. |
| 31/10/2026 | 10 | Facturae: precio unitario neto (sin descuentos separados), solo euros, sin redondeo del total. | Desglosar descuentos por línea y generales. | `es_efactura/facturae.py`. |
| 31/10/2026 | 01 H7 | WSDL de VeriFactu, sus XSD y `xmldsig-core-schema.xsd` versionados en `erpnext_spain/schemas` (compartidos con Facturae). Si la URL de ES Settings es la oficial, el cliente usa la copia local; `aeat/wsdl.LocalSchemaTransport` redirige solo los imports remotos conocidos y `forbid_external` sigue activo. `zeep>=4.3.3,<5`. Si la AEAT publica un WSDL nuevo hay que actualizar la copia. | Relajar `forbid_external`; mantener `zeep<4.3.3`; descargar y cachear el WSDL en el sitio. | `aeat/wsdl.py`, `aeat/client.py` y la dependencia en `pyproject.toml`. |
| 31/10/2026 | 01 H8 | Datos de test propios en `erpnext_spain/tests/fixtures.py` (compañía `_Test ES Company` con plan *Standard*, cliente, artículo, identidad SIF solo en campos vacíos). Se crean una vez y se reutilizan por nombre (crear una compañía es lento); `test_company()` asegura todos. | Crear y borrar los datos en cada clase; usar los `_Test Company` de ERPNext (no son españolas). | `tests/fixtures.py` y `aeat/tests/helpers.test_company`. |
| 31/10/2026 | 01 H5 | Al desinstalar solo se borra el Property Setter del formato predeterminado si sigue apuntando a "Factura España VeriFactu"; si el usuario eligió otro, se respeta. El Print Format lo borra Frappe con el módulo. | Borrar siempre el Property Setter. | `es_verifactu/printing.cleanup_printing`. |
