# TODO — spain_compliance

Pendientes y mejoras abiertas tras la v1 del módulo VeriFactu.

---

## Impuestos por cliente (spec 07)

### Contexto

ERPNext **no** asigna automáticamente una *Sales Taxes and Charges
Template* en función del cliente al crear una *Sales Invoice*. Lo único
automático (`accounts_controller.py:1284`) es:

```python
self.taxes_and_charges = frappe.db.get_value(
	"Sales Taxes and Charges Template",
	{"is_default": 1, "company": self.company},
)
```

Busca la template con `is_default=1` de la empresa. No mira el
*Customer*, no mira `tax_category`, no invoca *Tax Rule*.

El *Tax Rule* (doctype que SÍ mapea customer → `sales_tax_template`)
existe y su función `get_tax_template(posting_date, args)` hace match
por customer/customer_group/tax_category/billing_country, pero
**no se llama automáticamente** en el ciclo de vida de *Sales Invoice*
— la función vive en `erpnext.accounts.party` sin ningún caller desde
el form/create de la factura.

El `tax_category` del *Customer* se usa para filtrar el **Item Tax
Template** (vía `transaction.js:3094`), no el *Sales Taxes and Charges
Template*.

### Mejora propuesta

Implementar asignación automática de la plantilla de impuestos por
cliente. Dos opciones:

1. **Tax Rule + doc_event**: un `doc_event` nuestro en `Sales Invoice`
   que, al seleccionar el customer (o al crear), invoque
   `get_tax_template(posting_date, {customer, company, ...})` y setee
   `taxes_and_charges` con el resultado. Reutiliza la infraestructura
   nativa de Tax Rule que ya existe.

2. **Custom field en Customer**: un Link `sc_sales_tax_template` en
   *Customer* que apunte directamente a la *Sales Taxes and Charges
   Template*; un `doc_event` lo lee al seleccionar el customer y lo
   asigna. Más simple, no depende de Tax Rule.

### Spec 07 — la fuente de verdad fiscal

Independientemente del mecanismo de asignación (template manual, Tax
Rule, o Item Tax Template), el spec 07 debe leer la tasa fiscal de
**campos estructurados** (`account_head` + `rate` de la fila de
impuestos), no de la `description` parseada con string-matching
(`"IVA - 21"`). La `description` es el punto débil del stub actual:
string-typing fiscal, frágil, depende de convención humana.

Alternativas para el spec 07:

- **Item Tax Template**: la tasa vive en el item; ERPNext calcula las
  filas de impuestos. El spec 07 lee `item_tax_rate` (JSON en cada fila
  de items) para reconstruir el desglose AEAT.
- **Cuenta contable**: parsear la tasa del nombre del account_head
  ("IVA repercutido 21%" → 21), o añadir un custom field `sc_tax_rate`
  en *Account* para metadata fiscal explícita.
- **Item Tax Template Detail** (`tax_type` + `tax_rate`): fuente de
  verdad directa de la tasa por item, sin depender de descriptions.

### Prioridad

Mejora — no bloquea la v1 (el stub con `"IVA - 21"` funciona para el
entorno de pruebas). Implementar junto con el spec 07.

---

## Otros pendientes (heredados del desarrollo VeriFactu)

### Normativa

- [ ] Verificación del perfil de firma (MTLS vs XAdES) contra la Orden
      HAC/1177/2024.
- [ ] Catálogos completos L8A (claves de régimen) y L10 (causas de
      exención) — verificar contra el texto oficial.
- [ ] Formato exacto del QR (`ValidarQR?nif=&fecha=&importe=&numserie=`).
- [ ] Ventana de remisión consecutiva de la AEAT.
- [ ] Catálogo completo de códigos de error AEAT (confirmados en vivo:
      1100, 1112, 1238, 2004, 3000; el resto pendiente).

### Producto

- [ ] `rectify()` debe cubrir registros pendientes estructuralmente
      rotos (hoy exige `curable=1`; un pendiente con fallo local de
      serialización no se puede rectificar sin cirugía manual).
- [ ] Doble pill en el list view de Sales Invoice (Status de pago +
      Estado VeriFactu) — affinar para evitar redundancia.
- [ ] Paginación de `SC Verifactu Aeat Query` (IndicadorPaginacion /
      ClavePaginacion, tope 10000/periodo).
- [ ] Query: botón JS oculto cuando el usuario no tiene permiso AEAT.

### Infraestructura

- [ ] Configurar *Outgoing Email Account* en el site para que el canal
      de incidencias por email funcione (hoy se aísla con log_error).
- [ ] Flake recurrente (primera corrida post-cambios): hipótesis =
      scheduler drain colisiona con tests durante la suite; propuesta:
      detener el scheduler durante `run-tests` o aislar tests de data
      viva.
- [ ] Investigar mecanismo de desaparición de `SC AEAT Response` docs
      durante migrates+tests (log_error commitea dentro de transacciones
      de test?).

### Especs pendientes de detallar

- [ ] Spec 05 (SII) — segundo consumidor de la capa AEAT.
- [ ] Spec 07 (impuestos por defecto) — dueño del contrato
      `get_spain_tax_breakup`; reemplazar el stub.
- [ ] Spec 02 (SEPA) — módulo «SC Sepa» (convención de nombres).
- [ ] Spec 09 (retenciones IRPF) — ver sección específica abajo.
- [ ] Specs 01, 03, 06, 08, 10, 11.

---

## Spec 09 — Retenciones IRPF

### Contexto

El IRPF español funciona al **REVÉS** del TDS (Tax Deducted at Source)
indio: el PROFESIONAL (emisor) **se autoretiene** al emitir la factura —
el cliente paga el total, pero el profesional ingresa solo el neto
(total − retención) y la retención la paga a Hacienda él mismo.

ERPNext tiene Tax Withholding nativo (doctype `Tax Withholding Category`
+ `Tax Withholding Entry`) orientado al TDS indio: el COMPRADOR retiene
al VENDEDOR al pagar. Los campos existen en Sales Invoice
(`tax_withholding_category`, `tax_withholding_entries`, `apply_tds`) y
en Customer, pero el controlador de cálculo
(`TaxWithholdingController.calculate` en `tax_withholding_entry.py`) está
diseñado para Purchase Invoice, no para Sales.

### Enfoques propuestos

| Enfoque | Para | Cómo | Pros | Contras |
|---------|------|------|------|---------|
| **B: Sales Taxes con tasa negativa** | Sales (autoretención al emitir) | Fila en la SI: `charge_type: "On Net Total"`, `rate: -15`, `account_head: "473 IRPF"` | Simple, funciona hoy, el GL cuadra (ingresos − retención = neto) | Sin umbrales ni acumulados (no se necesitan en IRPF español) |
| **A: Tax Withholding nativo** | Purchase (retención al pagar a profesionales) | TWC con tasa IRPF, asignar al Supplier, `TaxWithholdingController` calcula | Infraestructura nativa, umbrales, acumulados | Orientado a Purchase; el flujo de Sales necesita ajustes |
| **C: Híbrido** | Ambos lados | B para Sales + A para Purchase | Cubre emisión y recepción | Doble mecanismo |

Recomendación: **B para Sales + A para Purchase**.

### Interacción con VeriFactu / SII

- **VeriFactu (spec 04 §7)**: el IRPF **NO va en DetalleDesglose** (la
  AEAT lo excluye explícitamente del RegistroAlta). Solo afecta:
  - `ImporteTotal` = `rounded_total` (incluye la retención — el importe
    que paga el cliente).
  - `CuotaTotal` = `total_taxes_and_charges` (SOLO IVA, sin IRPF — la
    AEAT quiere la cuota de IVA, no las retenciones).
  - El contrato `get_spain_tax_breakup` debe EXCLUIR las filas de IRPF
    (cuentas de tipo retención) del desglose AEAT — solo incluir IVA/IPS/IGIC.
- **SII (spec 05)**: el IRPF sí se reporta en el SII como
  `CuotaRetencion` (ImporteTotal incluye retención; el SII desglosa
  IVA + retención por separado). El spec 05 debe exponer el IRPF en su
  propio campo, no mezclado con el desglose IVA.
- **Identificación de retención**: la cuenta contable del PGC (account_head)
  determina si una fila de impuestos es IVA (cuenta 4770) o IRPF
  (cuenta 4730). El spec 07 / 09 debe clasificar por account_head, no
  por description.

### Pendiente

- [ ] Detallar spec 09 (`specs/09-retenciones.md`).
- [ ] Decidir: ¿fila negativa manual (enfoque B) o Tax Withholding
      nativo adaptado a Sales?
- [ ] Contrato con spec 07: `get_spain_tax_breakup` debe filtrar IRPF
      (solo IVA/IPS/IGIC van al Desglose AEAT).
- [ ] Contrato con spec 05 (SII): exponer IRPF como `CuotaRetencion`
      separada del desglose IVA.
