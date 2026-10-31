// Spain Compliance · VeriFactu — list view de Sales Invoice (spec 04 §15).
//
// DOS cosas aquí:
//
// 1. PÍLDORA DE ESTADO VERIFACTU en la columna propia «Estado VeriFactu»
//    (Select fieldtype con in_list_view=1). Frappe YA renderiza los Select
//    como pill automática en las columnas Field del list view
//    (list_view.js:989 — `indicator-pill guess_colour(value)`), pero los
//    colores son genéricos (hash del string). Para colores intencionales
//    (verde=Aceptada, naranja=Con Errores, etc.) usamos
//    `settings.formatters["es_verifactu_status"]` que devuelve el HTML de
//    la pill con NUESTRO color + filtro clickable.
//
//    La columna «Status» nativa de ERPNext (Paid/Unpaid/Overdue) queda
//    INTACTA — NO tocamos get_indicator (que era lo que pisaba la pill de
//    pago con la de VeriFactu). Cada columna muestra lo suyo.
//
// 2. ESTILADO DE BORRADOR-* (el nombre temporal NO es una factura).
//
// MERGE, NO CLOBBER — frappe concatena el _list.js del doctype (el de
// ERPNext) y DESPUÉS los archivos de doctype_list_js de los hooks
// (frappe/desk/form/meta.py:_add_code). Una asignación
// `frappe.listview_settings["Sales Invoice"] = {...}` SOBREESCRIBE el
// objeto entero de ERPNext. El patrón correcto es extender el objeto
// existente y ENCADENAR los callbacks previos (mismo patrón que
// india_compliance).

frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};

const es_lvs = frappe.listview_settings["Sales Invoice"];

// --- Formatter: pill coloreada para la columna «Estado VeriFactu» --------
// Reemplaza el rendering automático del Select (guess_colour genérico) por
// colores intencionales por estado. El formato debe ser HTML de pill con
// `filterable` + `data-filter` para que el click filtre el list view.
es_lvs.formatters = es_lvs.formatters || {};

es_lvs.formatters["es_verifactu_status"] = function (value, df, doc) {
	if (!value) {
		return "";
	}
	const colors = {
		"Pendiente Envío": "yellow",
		"Alta Aceptada": "green",
		"Alta Con Errores": "orange",
		Anulada: "gray",
	};
	const color = colors[value] || "blue";
	return `<span class="filterable indicator-pill ${color} ellipsis"
		data-filter="es_verifactu_status,=,${value}">
		<span class="ellipsis"> ${__(value)} </span>
	</span>`;
};

// --- Estilado de BORRADOR-* (el nombre temporal NO es una factura) --------
const es_prev_onload = es_lvs.onload;

es_lvs.onload = function (listview) {
	if (es_prev_onload) {
		es_prev_onload(listview);
	}
	if (document.getElementById("es-verifactu-draft-style")) {
		return;
	}
	const style = document.createElement("style");
	style.id = "es-verifactu-draft-style";
	style.textContent = `
		/* BORRADOR-* en el list view: nombre atenuado + píldora «borrador» */
		.list-row-container a[data-name^="BORRADOR-"] {
			color: var(--text-muted, #8d99a6) !important;
		}
		.list-row-container a[data-name^="BORRADOR-"]::after {
			content: "${__("borrador")}";
			margin-left: 6px;
			font-size: 10px;
			font-weight: 500;
			line-height: 1.6;
			color: var(--text-muted, #8d99a6);
			border: 1px solid var(--border-color, #d1d8dd);
			border-radius: 4px;
			padding: 0 4px;
			vertical-align: middle;
		}
	`;
	document.head.appendChild(style);
};
