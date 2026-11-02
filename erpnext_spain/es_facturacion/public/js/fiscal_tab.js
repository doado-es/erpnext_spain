// Pestaña «AEAT» de Sales Invoice y «SII / Factura electrónica» de
// Purchase Invoice (revisión del 31/10/2026).
//
// El historial llega con el documento (`__onload.es_fiscal`, ver
// es_facturacion/fiscal_tab.py) y se pinta con frappe.ui.EmbeddedList (una lista
// por bloque: registros VeriFactu, registros del SII, facturas electrónicas), sin
// consultas extra. EmbeddedList va en un bundle aparte que se carga bajo demanda.
// Frappe lo incluye desde v16.50; en versiones anteriores se pinta una tabla
// sencilla con las mismas columnas (`simple_list`).
// Sin VeriFactu ni SII en la compañía y sin historial, la pestaña no se muestra:
// la factura se ve como en ERPNext estándar.

frappe.provide("erpnext_spain.fiscal_tab");

erpnext_spain.fiscal_tab.LABELS = {
	RegistroAlta: __("Alta"),
	RegistroAnulacion: __("Anulación"),
	PendienteEnvio: __("Pendiente de envío"),
	AceptadoConErrores: __("Aceptado con errores"),
};

erpnext_spain.fiscal_tab.COLORS = {
	Correcto: "green",
	"Registrada en FACe": "green",
	Contabilizada: "green",
	Pagada: "green",
	Incorrecto: "red",
	Rechazada: "red",
	Anulada: "red",
	Anulado: "gray",
	Sustituido: "gray",
};

erpnext_spain.fiscal_tab.label = function (value) {
	return erpnext_spain.fiscal_tab.LABELS[value] || value;
};

erpnext_spain.fiscal_tab.date = function (value) {
	return value ? frappe.datetime.str_to_user(value) : "";
};

erpnext_spain.fiscal_tab.error = function (code, message) {
	return [code, message].filter(Boolean).join(": ");
};

// Columnas de EmbeddedList: `badge` y el texto plano ya se escapan en el
// componente; los valores calculados se preparan en `prepare`.
erpnext_spain.fiscal_tab.link_column = function (label, doctype) {
	return { label, fieldname: "name", type: "link", route: (row) => ["Form", doctype, row.name] };
};

erpnext_spain.fiscal_tab.status_column = function () {
	return {
		label: __("Estado"),
		fieldname: "_status",
		type: "badge",
		color: (row) => erpnext_spain.fiscal_tab.COLORS[row.status] || "orange",
	};
};

erpnext_spain.fiscal_tab.BLOCKS = [
	{
		key: "verifactu",
		title: __("Registros VeriFactu"),
		// La sección VeriFactu ya existe (sus campos): la lista va al final.
		section: "es_verifactu_seccion",
		html: "es_verifactu_history",
		visible: (frm, data) =>
			frm.doctype === "Sales Invoice" &&
			(data.system === "VeriFactu" ||
				!!frm.doc.es_verifactu_mode ||
				(data.verifactu || []).length > 0),
		prepare: (row) => ({
			_type: erpnext_spain.fiscal_tab.label(row.record_type),
			_date: erpnext_spain.fiscal_tab.date(row.creation),
			_error: erpnext_spain.fiscal_tab.error(
				row.response_error_code,
				row.response_error_msg
			),
		}),
		columns: () => [
			erpnext_spain.fiscal_tab.link_column(__("Registro"), "ES Verifactu Billing Record"),
			{ label: __("Tipo"), fieldname: "_type" },
			erpnext_spain.fiscal_tab.status_column(),
			{ label: __("Fecha"), fieldname: "_date" },
			{ label: __("Error"), fieldname: "_error" },
		],
	},
	{
		key: "sii",
		title: __("Registros del SII"),
		section: "es_sii_history_section",
		html: "es_sii_history",
		visible: (frm, data) =>
			!frm.is_new() && (data.system === "SII" || (data.sii || []).length > 0),
		prepare: (row) => ({
			_send_on: erpnext_spain.fiscal_tab.date(row.send_on),
			_deadline: erpnext_spain.fiscal_tab.date(row.deadline),
			_last_attempt: erpnext_spain.fiscal_tab.date(row.last_attempt),
			_error: erpnext_spain.fiscal_tab.error(row.error_code, row.error_description),
		}),
		columns: () => [
			erpnext_spain.fiscal_tab.link_column(__("Registro"), "ES Sii Record"),
			{ label: __("Comunicación"), fieldname: "communication" },
			erpnext_spain.fiscal_tab.status_column(),
			{ label: __("Enviar a partir del"), fieldname: "_send_on" },
			{ label: __("Plazo"), fieldname: "_deadline" },
			{ label: __("Último intento"), fieldname: "_last_attempt" },
			{ label: __("CSV"), fieldname: "csv" },
			{ label: __("Error"), fieldname: "_error" },
		],
	},
	{
		key: "einvoice",
		title: __("Factura electrónica"),
		section: "es_einvoice_history_section",
		html: "es_einvoice_history",
		visible: (frm, data) =>
			!frm.is_new() &&
			((data.einvoice || []).length > 0 || !!frm.doc.es_einvoice || !!frm.doc.es_e_invoice),
		prepare: (row) => ({ _modified: erpnext_spain.fiscal_tab.date(row.modified) }),
		columns: () => [
			erpnext_spain.fiscal_tab.link_column(__("Documento"), "ES E-Invoice"),
			{ label: __("Formato"), fieldname: "format" },
			{ label: __("Canal"), fieldname: "channel" },
			erpnext_spain.fiscal_tab.status_column(),
			{ label: __("Registro FACe"), fieldname: "face_registry_number" },
			{ label: __("Modificado"), fieldname: "_modified" },
		],
	},
];

erpnext_spain.fiscal_tab.make_list = function ($parent, title, columns, rows) {
	const list = new frappe.ui.EmbeddedList({
		wrapper: $("<div class='mb-4'></div>").appendTo($parent),
		title: title,
		columns: columns,
		show_search: false,
		empty_message: __("Sin envíos todavía."),
		get_data: () => Promise.resolve(rows),
	});
	list.refresh();
	return list;
};

// Sustituto de EmbeddedList para Frappe < v16.50: tabla de solo lectura.
erpnext_spain.fiscal_tab.simple_list = function ($parent, title, columns, rows) {
	const escape = frappe.utils.escape_html;
	const cell = (column, row) => {
		const raw = row[column.fieldname];
		const value = raw == null ? "" : String(raw);
		if (column.type === "link") {
			const route = column.route(row);
			return `<a href="${escape(frappe.utils.get_form_link(route[1], route[2]))}">${escape(
				value
			)}</a>`;
		}
		if (column.type === "badge") {
			const color = column.color ? column.color(row) : "gray";
			return `<span class="indicator-pill ${escape(color)}">${escape(value)}</span>`;
		}
		return escape(value);
	};
	const $block = $("<div class='mb-4'></div>").appendTo($parent);
	$("<h6 class='mb-2'></h6>").text(title).appendTo($block);
	if (!rows.length) {
		$("<p class='text-muted'></p>").text(__("Sin envíos todavía.")).appendTo($block);
		return;
	}
	const head = columns.map((column) => `<th>${escape(column.label)}</th>`).join("");
	const body = rows
		.map(
			(row) =>
				`<tr>${columns.map((column) => `<td>${cell(column, row)}</td>`).join("")}</tr>`
		)
		.join("");
	$block.append(
		`<div class="table-responsive"><table class="table table-bordered table-sm">` +
			`<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
	);
};

// ¿Hay EmbeddedList en este Frappe (ya cargado o como bundle)?
erpnext_spain.fiscal_tab.has_embedded_list = function () {
	return (
		!!frappe.ui.EmbeddedList ||
		!!(frappe.boot.assets_json && frappe.boot.assets_json["embedded_list.bundle.js"])
	);
};

erpnext_spain.fiscal_tab.render = function (frm, block, data) {
	const field = frm.fields_dict[block.html];
	if (!field) return;
	field.$wrapper.empty();
	const rows = (data[block.key] || []).map((row) =>
		Object.assign({}, row, block.prepare(row), {
			_status: erpnext_spain.fiscal_tab.label(row.status),
		})
	);
	const make = frappe.ui.EmbeddedList
		? erpnext_spain.fiscal_tab.make_list
		: erpnext_spain.fiscal_tab.simple_list;
	make(field.$wrapper, block.title, block.columns(), rows);
};

erpnext_spain.fiscal_tab.apply = function (frm, data) {
	const shown = [];
	for (const block of erpnext_spain.fiscal_tab.BLOCKS) {
		if (!frm.fields_dict[block.section]) continue;
		const visible = block.visible(frm, data);
		frm.toggle_display(block.section, visible);
		if (frm.fields_dict[block.html]) frm.fields_dict[block.html].$wrapper.empty();
		if (visible) shown.push(block);
	}
	frm.toggle_display("es_fiscal_tab", shown.length > 0);
	// Las listas solo con el documento guardado (el historial llega con él).
	const lists = !frm.is_new() && data.loaded ? shown : [];
	if (!lists.length) return;
	if (!erpnext_spain.fiscal_tab.has_embedded_list()) {
		lists.forEach((block) => erpnext_spain.fiscal_tab.render(frm, block, data));
		return;
	}
	frappe
		.require("embedded_list.bundle.js")
		.then(() => lists.forEach((block) => erpnext_spain.fiscal_tab.render(frm, block, data)))
		.catch(() =>
			lists.forEach((block) =>
				frm.fields_dict[block.html].$wrapper.text(
					__("No se pudo cargar el historial. Recargue la página.")
				)
			)
		);
};

erpnext_spain.fiscal_tab.refresh = function (frm) {
	const loaded = (frm.doc.__onload || {}).es_fiscal;
	if (loaded && !frm.is_new()) {
		erpnext_spain.fiscal_tab.apply(frm, Object.assign({ loaded: true }, loaded));
		return;
	}
	// Documento nuevo o sin historial: solo cuenta si la compañía usa VeriFactu
	// (los datos de la sección se rellenan antes de emitir).
	erpnext_spain.fiscal_tab.apply(frm, {});
	if (!frm.doc.company) {
		return;
	}
	frappe.db
		.get_value("Company", frm.doc.company, ["es_verifactu_enabled", "es_sii_enabled"])
		.then((r) => {
			const company = (r && r.message) || {};
			const verifactu = !!company.es_verifactu_enabled && !company.es_sii_enabled;
			erpnext_spain.fiscal_tab.apply(frm, { system: verifactu ? "VeriFactu" : null });
		});
};

// El mismo fichero se carga con los dos formularios: los eventos se registran
// una sola vez y llaman siempre a la última definición.
if (!erpnext_spain.fiscal_tab_events) {
	erpnext_spain.fiscal_tab_events = true;
	["Sales Invoice", "Purchase Invoice"].forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh: (frm) => erpnext_spain.fiscal_tab.refresh(frm),
			company: (frm) => erpnext_spain.fiscal_tab.refresh(frm),
		});
	});
}
