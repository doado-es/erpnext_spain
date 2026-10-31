# Plan de desarrollo autónomo

Encargo del usuario (31/10/2026): desarrollar todas las specs, con tests, tomando las mejores decisiones y documentándolas para revisarlas después. Este documento fija el orden, las reglas de trabajo y dónde se documenta cada decisión.

## Reglas de trabajo

1. **Un apartado de spec por rama** (`feat/<spec>-<apartado>`), tests en verde en `test.es.localhost` y merge `--ff-only` a `version-16` (no hay remoto). Commits convencionales, sin atribución.
2. **Nada de lo prohibido por el maestro** (R1–R12): sin monkey patching, sin `override_doctype_class`/`extend_doctype_class`, custom fields por código, `doc_events` con salida temprana cacheada, sin `frappe.db.sql` ni `commit`, endpoints con tipos, permisos y `POST` si escriben.
3. **Cada decisión que tome el agente** (algo que la spec deja abierto, una contradicción, una verificación en el código de ERPNext) se anota en [`decisiones.md`](decisiones.md) con fecha, spec, decisión, alternativas y cómo revertirla. Las que dependen de un contable o de un asesor se marcan **[revisar]**.
4. **Lo que no se pueda terminar** (falta un PDF oficial, un certificado, un servicio externo) se deja con la interfaz y un cliente simulado, y se anota en [`pendientes.md`](pendientes.md).
5. **Sin servicios reales**: AEAT, FACe, bancos y VIES solo con clientes simulados en los tests.
6. Al terminar cada bloque: suite completa (`bench --site test.es.localhost run-tests --app erpnext_spain`), `ruff check`, actualizar el estado en la spec y en `pendientes.md`.

## Orden

| Bloque | Contenido | Specs |
|---|---|---|
| 1 | Restos de la fase 0: H7 (XSD locales, quitar `zeep<4.3.3`), H8 (tests con datos propios), H5 (`rectify` POST, Property Setter al desinstalar, guía con fixtures), errores de `ruff` heredados, workflow de CI (fichero listo para cuando haya remoto), workspace y onboarding; validación de cuentas PGC | 01 §6–§8, 02 §4 |
| 2 | Clasificación al validar la factura; retenciones practicadas (categorías, grupos, cuentas, validación del proveedor, inmuebles, informes); resto de datos iniciales (festivos, condiciones de pago, formato de dirección, reglas bancarias) | 03 §5, 08, 09 |
| 3 | Numeración fiscal al emitir sin VeriFactu; bloqueo de *amend*; situación de cobro (dudoso cobro, pérdida); formato de factura único | 05 |
| 4 | Registro Fiscal IVA, autorrepercusión (confirmar la opción de plantillas), reconstrucción, libros de expedidas y recibidas, borrador de liquidación; desglose para VeriFactu en lugar del stub | 06 |
| 5 | Modelos Abreviado y Normal; reclasificación por signo de clientes, proveedores y bancos; sumas y saldos; libro diario; traspaso 8/9; regularización de existencias | 04 |
| 6 | SEPA (transferencias y adeudos, mandatos, respuestas); Norma 43 y adaptador de agregador bancario; confirming (estructura a falta del PDF de la AEF) | 11, 13, 12 |
| 7 | SII: libros, cola, plazos, cuadre (cliente simulado); factura electrónica B2B (adaptador, UBL) y recepción; modelos 303 y 111 | 14, 10, 07 |
| 8 | Funcionalidades: facturación masiva de albaranes de venta y de compra, envío masivo de facturas, validador de NIF y VIES | F1–F4 |
| 9 | Traducciones de todo lo nuevo; revisión es-ES de las cadenas compuestas de ERPNext | — |

## Entorno

- Bench `~/es` (Frappe 16.50, ERPNext 16.51, Python 3.14). Sitio de desarrollo `es.localhost` (compañía `ctg` con datos de prueba, servidor en el puerto 8021) y sitio de tests `test.es.localhost`.
- Los tests crean sus propios datos (`erpnext_spain/tests/fixtures.py`, H8): no dependen de los datos de demostración del sitio.
- Tras cambiar `hooks.py`: `bench --site <sitio> clear-cache`. Tras añadir doctypes nuevos, `migrate` puede necesitar dos pasadas.
- Scripts de desarrollo fuera del repo: `~/es/specs/dev/`.
