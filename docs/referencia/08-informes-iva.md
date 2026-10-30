# 8. Generación de Informes de IVA (Modelos AEAT)

[← Volver al índice](00-maestro.md)

## Objetivo

Generar los modelos de IVA que se presentan periódicamente a la AEAT a partir de los datos ya registrados en ERPNext (Sales Invoice, Purchase Invoice, GL Entry).

## Contexto normativo

- **Modelo 303**: autoliquidación trimestral/mensual de IVA.
- **Modelo 347**: declaración anual de operaciones con terceros (>3.005,06 € por cliente/proveedor).
- **Modelo 349**: declaración de operaciones intracomunitarias.
- **Modelo 390**: resumen anual de IVA.

## Alcance

- Cálculo y agregación de bases imponibles y cuotas por tipo de IVA, periodo y compañía.
- Generación de los ficheros/formularios en el formato exigido por la AEAT para cada modelo (o al menos un informe interno que facilite la presentación manual, según prioridad).
- Conciliación de los totales con el libro mayor de IVA repercutido/soportado.

## Estado actual / referencias

*(Pendiente — enlazar aquí repos propios si ya hay trabajo adelantado en generación de modelos AEAT)*

## Diseño técnico propuesto

*(Por completar)*

## Dudas abiertas

- ¿Se apunta a generar el fichero en formato de presentación directa (BOE/AEAT) o a un informe intermedio que el asesor fiscal traslada manualmente? (nivel de ambición distinto por modelo)
- ¿Qué modelo se prioriza primero — 303 por ser el más recurrente (trimestral)?
- Relación con el modelo 347 y el umbral de 3.005,06 € — ¿cálculo automático desde el arranque o revisión manual asistida?

## Tareas para agentes

- [ ] Definir report builder (o Query Report) para el Modelo 303 a partir de GL Entry / Tax Template.
- [ ] Definir report builder para el Modelo 347 (agregación anual por tercero con umbral).
- [ ] Definir report builder para el Modelo 349 (operaciones intracomunitarias).
- [ ] Evaluar generación del Modelo 390 como resumen derivado de los 303 del ejercicio.
