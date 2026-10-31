// Pestaña «VeriFactu / SII» de Sales Invoice y «SII / Factura electrónica» de
// Purchase Invoice (revisión del 31/10/2026).
//
// El historial llega con el documento (`__onload.es_fiscal`, ver
// es_facturacion/fiscal_tab.py) y se pinta con frappe.ui.EmbeddedList (una lista
// por bloque: registros VeriFactu, registros del SII, facturas electrónicas), sin
// consultas extra. EmbeddedList va en un bundle aparte que se carga bajo demanda.
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
		prepare: (row) => ({
			_deadline: erpnext_spain.fiscal_tab.date(row.deadline),
			_last_attempt: erpnext_spain.fiscal_tab.date(row.last_attempt),
			_error: erpnext_spain.fiscal_tab.error(row.error_code, row.error_description),
		}),
		columns: () => [
			erpnext_spain.fiscal_tab.link_column(__("Registro"), "ES Sii Record"),
			{ label: __("Comunicación"), fieldname: "communication" },
			erpnext_spain.fiscal_tab.status_column(),
			{ label: __("Plazo"), fieldname: "_deadline" },
			{ label: __("Último intento"), fieldname: "_last_attempt" },
			{ label: __("CSV"), fieldname: "csv" },
			{ label: __("Error"), fieldname: "_error" },
		],
	},
	{
		key: "einvoice",
		title: __("Factura electrónica"),
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

erpnext_spain.fiscal_tab.render = function ($wrapper, data) {
	$wrapper.empty();
	const blocks = erpnext_spain.fiscal_tab.BLOCKS.filter(
		(block) => (data[block.key] || []).length
	);
	if (!blocks.length) {
		erpnext_spain.fiscal_tab.make_list($wrapper, __("Historial de envíos"), [], []);
		return;
	}
	blocks.forEach((block) => {
		const rows = data[block.key].map((row) =>
			Object.assign({}, row, block.prepare(row), {
				_status: erpnext_spain.fiscal_tab.label(row.status),
			})
		);
		erpnext_spain.fiscal_tab.make_list($wrapper, block.title, block.columns(), rows);
	});
};

erpnext_spain.fiscal_tab.apply = function (frm, data) {
	const is_sales = frm.doctype === "Sales Invoice";
	const show_verifactu =
		is_sales && (data.system === "VeriFactu" || !!frm.doc.es_verifactu_mode);
	const show_history = !frm.is_new() && !!data.loaded;

	if (is_sales) {
		frm.toggle_display("es_verifactu_seccion", show_verifactu);
	}
	frm.toggle_display("es_fiscal_history_section", show_history);
	frm.toggle_display("es_fiscal_tab", show_verifactu || show_history);

	const field = frm.fields_dict.es_fiscal_history;
	if (!field) {
		return;
	}
	field.$wrapper.empty();
	if (!show_history) {
		return;
	}
	frappe
		.require("embedded_list.bundle.js")
		.then(() => erpnext_spain.fiscal_tab.render(field.$wrapper, data))
		.catch(() =>
			field.$wrapper.text(__("No se pudo cargar el historial. Recargue la página."))
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
