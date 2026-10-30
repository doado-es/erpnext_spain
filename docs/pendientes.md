# Pendientes

Lista única de lo que falta, para ir cerrándolo por orden. Cada punto remite a su spec. Actualizado el 30/10/2026.

## Funcionalidades nuevas (no son de cumplimiento)

Peticiones del usuario del 30/10/2026. Cada una tendrá su spec antes de empezar.

| Id | Funcionalidad | Notas |
|---|---|---|
| F1 | **Facturación masiva de albaranes de venta**: crear facturas de venta a partir de varios Delivery Note, agrupadas por cliente (y opcionalmente por periodo, dirección o condiciones de pago). | Ya prevista en la spec 07 ("facturación masiva desde albaranes"). Decidir criterios de agrupación, qué hacer con albaranes con distinta moneda, lista de precios o impuestos, y si se valida la factura o se deja en borrador. Debe respetar la numeración fiscal (spec 05) y VeriFactu. |
| F2 | **Facturación masiva de albaranes de compra**: crear facturas de compra a partir de varios Purchase Receipt del mismo proveedor. | La factura de compra la emite el proveedor: hace falta su número y fecha (`bill_no`, `bill_date`). Posible flujo: seleccionar albaranes de un proveedor y registrar la factura recibida que los agrupa. |
| F3 | **Envío masivo de facturas por correo**: enviar a cada cliente sus facturas validadas (una por correo o agrupadas), con el formato de impresión español y plantilla de correo. | En segundo plano (cola), con registro de lo enviado y de los errores, y sin reenviar lo ya enviado salvo que se pida. Destinatario: contacto de facturación del cliente. |

## Fase 0 — fundamentos (spec 01)

- §6 Workspace "España" y onboarding.
- §7 / H4 CI en GitHub Actions: lint, Semgrep con `frappe/semgrep-rules` y reglas propias, tests en un sitio limpio. Antes hay que tener remoto.
- H7 definitivo: incluir en la app los XSD externos que importa el WSDL de la AEAT y quitar el límite `zeep<4.3.3`.
- H8: que los tests de VeriFactu creen sus propios datos (cliente, artículo, identidad SIF, compañía) y no dependan del sitio.
- ~~H3~~: hecho.
- H5 (resto): `rectify` solo `POST`; borrar al desinstalar el Property Setter del formato de impresión; corregir en `docs/referencia` la guía que recomienda fixtures.
- Errores de `ruff` heredados del código base (47 avisos y 37 ficheros sin formatear).
- El botón "Aplicar plan PGC" de Company no respondía al usuario (aparecía, sin error en consola). Sin diagnosticar.
- URLs del proyecto en `pyproject.toml` cuando haya repositorio remoto; pasar a PR por apartado.

## Plan contable (spec 02)

- §4 Validación de cuentas nuevas en compañías PGC (número obligatorio y coherente con la rama).
- §6 Subcuentas por tercero (decisión A1, opcional).
- Revisión contable del reparto de ramas y de las cuentas por defecto (2819 como amortización acumulada, 406, 6590 para redondeos, 6680 para diferencias de cambio…).
- Verificar en bench compras y ventas de artículos de existencias con el inventario permanente desactivado (A3).

## Impuestos (specs 03 y 09)

- Spec 03 §5: copiar la clasificación de la plantilla si la fila está vacía y exigirla con `es_require_tax_classification`.
- Verificar en la documentación de la AEAT los códigos E7, E8 y la clave de régimen 21, y los textos de las claves de régimen.
- Revisión contable: IVA no deducible a la 6310.
- Spec 09 pendientes: Tax Withholding Group y Category (spec 08), Holiday List de festivos nacionales, Payment Terms Template, Address Template de España, cuentas de retención por compañía, Bank Transaction Rule.

## Estados financieros (spec 04)

- Modelos Abreviado y Normal (Balance y PyG).
- Reclasificación por signo de clientes y proveedores con saldo contrario y de bancos en descubierto.
- Revisar las cuentas añadidas al mapeo PYMES que el modelo del BOE no recoge (columna `nota`: 473, 5585, 550, 554, 137, 15x, 195/197/199, 502, 507, 678, 778).
- §4 Sumas y saldos por niveles; §5 libro diario numerado; §6 traspaso de los grupos 8 y 9; §7 regularización de existencias.

## Facturación (spec 05)

- §1 Numeración fiscal al emitir sin VeriFactu (`es_fiscal_numbering`, hoy sin efecto): separar el renombrado a la serie fiscal del módulo VeriFactu.
- §2 Rectificativas (método y motivo); §4 situación de cobro (dudoso cobro, pérdida); §5 formato de factura único.

## Registro fiscal de IVA (spec 06)

- Todo el doctype y los libros.
- Confirmar la propuesta de autorrepercusión con dos filas en la plantilla de compra (ya implementada en los datos iniciales) frente al regional override.
- Importaciones con DUA.

## Retenciones (spec 08)

- Retenciones practicadas en compras con el mecanismo nativo (categorías, grupos, cuentas 4751), validación del proveedor, inmuebles arrendados e informes para 111, 115, 180 y 190. Decisión A7.

## Comunicación con la AEAT y terceros

- VeriFactu: prueba real en el entorno de pruebas de la AEAT (falta certificado); pendientes del TODO del código base (catálogos L8A y L10, formato del QR, paginación de la consulta, errores).
- SII (spec 14): libros, cola de envío, plazos y cuadre. Hoy solo está la activación.
- Factura electrónica (spec 10), SEPA (spec 11), confirming (spec 12), Norma 43 y conexión bancaria (spec 13).
- Modelos AEAT (spec 07).

## Traducciones

- Revisión es-ES de las cadenas compuestas de ERPNext que siguen con la variante general ("Orden de venta", "Producto"…).
- Regenerar las cadenas que falten tras cada actualización de ERPNext.

## Datos de prueba

- El script de datos de prueba de `ctg` está fuera del repo (`~/es/specs/dev/demo_ctg.py`; se ejecuta copiándolo como módulo temporal de la app y con `bench --site es.localhost execute`). Decidir si se incorpora como herramienta de desarrollo.
