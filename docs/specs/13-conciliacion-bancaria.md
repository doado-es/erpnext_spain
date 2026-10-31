# 13 — Conciliación bancaria: Norma 43 y conexión por API

Fase 4 · Depende de: 02, 09 · Relacionada con: 11, 12

> **Estado (31/10/2026): implementado** en el módulo ES Bancos: lector de Norma 43 con comprobación de totales y saldo final, `ES Norma43 Import`, deduplicación por `transaction_id`, tercero por IBAN y conciliación automática por `EndToEndId`; adaptador de agregador con interfaz común y adaptador simulado (`ES Bank Aggregator`, credenciales en `Password`), sincronización cada 6 horas y aviso de caducidad del consentimiento. Tests en `es_bancos/tests/test_banking.py` (criterios 1-7, el 1 con ficheros sintéticos). Pendiente: A8 (agregador real), camt.053.

## Objetivo

Traer los movimientos bancarios a ERPNext, por fichero **Norma 43** (cuaderno 43 de AEB, CECA y UNACC) o por **API** a través de un agregador de información de cuentas (PSD2), y conciliarlos con la herramienta nativa de ERPNext v16.

## 1. Qué trae ERPNext v16 [verificado v16]

| Pieza | Contenido |
|---|---|
| `Bank Transaction` | Fecha, cuenta, depósito o retirada, descripción, referencia, `transaction_id`, tercero, `bank_party_name`, `bank_party_iban`, `transaction_type`, comisiones incluidas y excluidas, estado y pagos asignados. |
| `Bank Statement Import` | Importación desde CSV o Excel, y desde **MT940** (convierte el fichero a CSV antes de importar). **No lee Norma 43 ni camt.053.** |
| `Bank Transaction Rule` | Reglas automáticas por tipo, rango de importe y condiciones sobre la descripción, que clasifican el movimiento como Bank Entry, Payment Entry o Transfer contra una cuenta o un tercero. |
| `Bank Reconciliation Tool` y la nueva interfaz de banca de v16 | Conciliación de movimientos con pagos, asientos y facturas. |
| `Bank Account` | Campos `integration_id` y `last_integration_date`, que usa la integración de Plaid. |
| Plaid | Única integración bancaria incluida **[verificar cobertura de bancos españoles]**. |

Conclusión: la conciliación, las reglas y la interfaz ya existen. Lo que falta es **traer los movimientos** desde los formatos y canales españoles.

## 2. Norma 43

Formato **[verificado en el cuaderno 43, versión de junio de 2012, Circular 1767]**:

- Registros de longitud fija de 80 posiciones, en ASCII.
- Tipos de registro: 11 cabecera de cuenta (entidad, oficina, cuenta, fechas, saldo inicial con signo, divisa, modalidad); 22 movimiento (oficina de origen, fecha de operación y fecha valor AAMMDD, concepto común de 2 posiciones, concepto propio de 3, debe o haber, importe de 14 posiciones con 2 decimales, número de documento, referencias 1 y 2); 23 conceptos complementarios (hasta 5, 2 × 38 posiciones; el anexo 4 los usa para datos SEPA); 24 equivalencia de divisa; 33 final de cuenta (número y totales de apuntes, saldo final); 88 fin de fichero.
- Conceptos comunes 01 a 17, 98 y 99 (p. ej. 03 recibos domiciliados, 04 transferencias, 12 tarjetas, 14 devoluciones e impagados, 17 intereses y comisiones).

Diseño:

- Acción "Importar Norma 43" en `Bank Account` (o en un doctype ligero "Importación Norma 43", nombre final `ES Norma43 Import`, en el módulo ES Bancos, con el fichero, el resultado y el log). **Crea `Bank Transaction` directamente**, sin pasar por Bank Statement Import, porque el formato no es tabular.
- Un fichero puede traer varias cuentas: se asocia cada bloque 11–33 a la `Bank Account` de la compañía por entidad, oficina y número de cuenta (o IBAN derivado). Bloques de cuentas desconocidas: error claro, el resto se importa.
- Comprobaciones: saldo inicial + movimientos = saldo final del registro 33; totales y número de apuntes; registro 88.
- Duplicados: `transaction_id` estable calculado con cuenta, fecha de operación, fecha valor, importe, signo, número de documento, referencias y posición dentro del día. Reimportar el mismo fichero no crea duplicados.
- Mapeo: descripción = concepto propio + conceptos complementarios; `transaction_type` = concepto común; `reference_number` = referencias y, si hay datos SEPA en los complementarios, el `EndToEndId` o la referencia del mandato (spec 11) para casar automáticamente.
- Reglas de partida (spec 09): `Bank Transaction Rule` para comisiones e intereses (concepto 17) a 626/669 y 769, a revisar por la compañía.

## 3. Conexión por API (PSD2, información de cuentas)

- La compañía no accede directamente a la API de cada banco: se integra con un **agregador con licencia de proveedor de servicios de información sobre cuentas** (decisión A8; candidatos como Tink, Salt Edge, Enable Banking o GoCardless Bank Account Data **[verificar cobertura de bancos españoles, condiciones y precio]**).
- **Adaptador** con interfaz común: `iniciar_consentimiento(bank_account)`, `renovar_consentimiento`, `obtener_movimientos(desde, hasta)`, `obtener_saldo`. Cambiar de agregador solo cambia el adaptador.
- Doctype de configuración por compañía con las credenciales del agregador en campos `Password` (R6, R8).
- Consentimiento: flujo de redirección del agregador desde `Bank Account`; se guarda el identificador en `integration_id` y la fecha de la última sincronización en `last_integration_date` (campos nativos). Aviso antes de que caduque el consentimiento (las normas técnicas de la PSD2 piden renovar la autenticación reforzada periódicamente **[verificar plazo vigente]**).
- Sincronización: job programado (p. ej. cada 6 horas) por cuenta conectada, que crea `Bank Transaction` con la misma deduplicación por `transaction_id` del agregador.
- Comisiones del agregador: fuera de la app; documentarlas.

## 4. Conciliación

- Se usa la herramienta nativa de v16.
- La app ayuda al emparejamiento automático con lo que ya conoce:
  - `EndToEndId` de transferencias y adeudos (spec 11) y referencias de remesas de confirming (spec 12), guardados en los pagos y presentes en las referencias del movimiento.
  - IBAN del tercero (`bank_party_iban`) contra `Bank Account` de clientes y proveedores para proponer el tercero.
- Esa ayuda se implementa como `doc_event` de `Bank Transaction` (`before_insert`/`validate`) que rellena tercero y referencias, sin tocar la lógica de conciliación de ERPNext (R2).

## Criterios de aceptación

1. Un fichero Norma 43 real de al menos dos entidades se importa; el saldo final de cada cuenta coincide con el registro 33.
2. Reimportar el mismo fichero no crea movimientos nuevos.
3. Un fichero con dos cuentas, una desconocida, importa la conocida e informa de la otra.
4. Un adeudo cobrado (spec 11) se casa automáticamente con su Payment Entry por el `EndToEndId`.
5. Un movimiento cuyo IBAN pertenece a un proveedor propone ese proveedor.
6. Con el adaptador de pruebas del agregador, una sincronización crea los movimientos y una segunda sin cambios no crea nada.
7. Las credenciales del agregador no aparecen en ninguna respuesta de la API.

## Pendiente de verificar o decidir

- **A8**: agregador (cobertura española, licencia, coste, modelo de consentimiento).
- Cobertura de Plaid en España, por si basta con la integración nativa.
- Variantes de Norma 43 por entidad (registros 23 con datos SEPA).
- Si se añade camt.053 además de Norma 43 (algunas entidades ya lo ofrecen).
