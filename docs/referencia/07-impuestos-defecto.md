# 7. Automatización de Tipos de Impuesto por Defecto

[← Volver al índice](00-maestro.md)

## Objetivo

Que ERPNext aplique automáticamente el tipo de IVA (y en su caso IRPF) correcto por defecto según el tipo de item, cliente/proveedor y operación (nacional, intracomunitaria, exportación, inversión del sujeto pasivo), sin que el usuario tenga que seleccionar manualmente la plantilla de impuestos en cada documento.

## Contexto normativo

- Tipos de IVA español: general 21%, reducido 10%, superreducido 4%, exento.
- Casuísticas especiales: operaciones intracomunitarias (inversión del sujeto pasivo), exportaciones (exentas), recargo de equivalencia, régimen de agencias de viaje, etc.

## Alcance

- Reglas de asignación automática de Tax Template según: categoría de item, país/NIF-IVA del cliente o proveedor, tipo de documento.
- Detección de operaciones intracomunitarias (NIF-IVA validado vía VIES) para aplicar inversión del sujeto pasivo.
- Configuración de tipo de IVA por defecto a nivel de Item / Item Group.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en reglas de impuestos. Referencia de partida: `data/spain_wise_tax.json` del app previo — categorías de IVA, tax templates y plan contable)*

> **Dependencia activa**: VeriFactu (04, §7) define el contrato `get_spain_tax_breakup(invoice)` — el mapeo Tax Template → semántica fiscal española (claves de régimen L8A, causas de exención L10, calificación de operación, tipo impositivo) es propiedad de ESTE módulo. Detallarlo en esta spec cuando toque. El enrutamiento usa el detector de NIF español del verificador transversal ([14-verificador-nif.md](14-verificador-nif.md)); la validación de NIFs intracomunitarios (formato UE + VIES) es de ESTE módulo, no del 14.
>
> **VIES (WSDL verificado — ver 14 §Servicios web)**: `checkVat` / `checkVatApprox` (con match de datos del operador + `requestIdentifier`). Al detallar este spec: caching obligatorio (rate-limits documentados en los faults), guardar el `requestIdentifier` como evidencia de diligencia en exenciones intracomunitarias, y recordar que VIES solo cubre el ROI (NIFs registrados como operadores intracomunitarios) — un NIF español doméstico corriente NO está en VIES.

## Diseño técnico propuesto

*(Por completar — evaluar si se apoya en el motor de "Tax Rule" ya existente en ERPNext, extendiéndolo, o si requiere lógica propia por las casuísticas españolas)*

## Dudas abiertas

- ¿El motor nativo de Tax Rule de ERPNext cubre suficientes casos o hace falta lógica adicional en `validate`/`before_save`?
- ¿Validación de NIF-IVA contra VIES en tiempo real (llamada externa) o solo como aviso/checklist manual?
- ¿Cómo se gestionan los regímenes especiales (recargo de equivalencia, agencias de viaje) — como casos raros manuales o automatizados también?

## Tareas para agentes

- [ ] Auditar el motor de Tax Rule nativo de ERPNext y sus límites.
- [ ] Diseñar matriz de reglas (tipo de item × origen/destino × tipo de operación) → Tax Template.
- [ ] Implementar validación de NIF-IVA intracomunitario (VIES) si se decide automatizar.
