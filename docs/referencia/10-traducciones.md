# 10. Buenas Traducciones (es-ES)

[← Volver al índice](00-maestro.md)

## Objetivo

Asegurar que ERPNext tenga una traducción al español completa, coherente y con terminología contable/fiscal correcta para España — no una traducción genérica o mezclada con español latinoamericano, y sin cadenas sin traducir en las áreas clave (contabilidad, facturación, informes).

## Contexto

- Se ha detectado que la traducción española de ERPNext tiene huecos (issue abierto en el propio repo de ERPNext sobre traducciones españolas ausentes).
- La terminología contable española tiene matices frente al español genérico o latinoamericano (ej. "IVA" vs. otros impuestos al valor agregado, nombres de informes, terminología del PGC).

## Alcance

- Auditoría de cadenas sin traducir o mal traducidas en los módulos de Accounts, Selling, Buying, Stock relevantes para el uso en España.
- Traducción/corrección con terminología contable española correcta (alineada con el PGC y los modelos AEAT).
- Traducciones propias de los DocTypes y campos nuevos que añada esta app custom.

## Estado actual / referencias

*(Pendiente — enlazar aquí el hilo de Crowdin de Frappe (es-ES) y cualquier trabajo propio ya iniciado en traducciones)*

## Diseño técnico propuesto

*(Por completar — decidir si se contribuye directamente al proyecto de traducción de Frappe/Crowdin, o si se mantiene un fichero de traducciones propio dentro de la app custom para no depender de los tiempos de merge upstream)*

## Dudas abiertas

- ¿Contribuir upstream (Crowdin) para que beneficie a toda la comunidad, o mantener overrides locales para tener control total del timing?
- ¿Alcance solo de las áreas usadas por esta app (contabilidad/fiscal) o traducción completa del sistema?

## Tareas para agentes

- [ ] Auditar cadenas sin traducir en es-ES en los módulos relevantes (usar `bench` de exportación de mensajes).
- [ ] Priorizar corrección de terminología contable/fiscal antes que cobertura completa.
- [ ] Añadir traducciones de los DocTypes/campos nuevos de esta app desde el primer commit (no dejarlo para el final).
