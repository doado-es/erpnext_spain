// Pestaña «VeriFactu / SII» de Sales Invoice y «SII / Factura electrónica» de
// Purchase Invoice (revisión del 31/10/2026).
//
// El historial llega con el documento (`__onload.es_fiscal`, ver
// es_facturacion/fiscal_tab.py). Sin VeriFactu ni SII en la compañía y sin
// historial, la pestaña no se muestra: la factura se ve como en ERPNext estándar.

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

erpnext_spain.fiscal_tab.text = function (value) {
	return frappe.utils.escape_html(value === null || value === undefined ? "" : String(value));
};

erpnext_spain.fiscal_tab.label = function (value) {
	return erpnext_spain.fiscal_tab.LABELS[value] || value;
};

erpnext_spain.fiscal_tab.status = function (value) {
	if (!value) {
		return "";
	}
	const color = erpnext_spain.fiscal_tab.COLORS[value] || "orange";
	return `<span class="indicator-pill ${color}">${erpnext_spain.fiscal_tab.text(
		erpnext_spain.fiscal_tab.label(value)
	)}</span>`;
};

erpnext_spain.fiscal_tab.link = function (doctype, name) {
	const href = frappe.utils.get_form_link(doctype, name);
	return `<a href="${encodeURI(href)}">${erpnext_spain.fiscal_tab.text(name)}</a>`;
};

erpnext_spain.fiscal_tab.date = function (value) {
	return erpnext_spain.fiscal_tab.text(value ? frappe.datetime.str_to_user(value) : "");
};

erpnext_spain.fiscal_tab.error = function (code, message) {
	return erpnext_spain.fiscal_tab.text([code, message].filter(Boolean).join(": "));
};

erpnext_spain.fiscal_tab.BLOCKS = [
	{
		key: "verifactu",
		title: __("Registros VeriFactu"),
		doctype: "ES Verifactu Billing Record",
		columns: [
			[
				__("Registro"),
				(r) => erpnext_spain.fiscal_tab.link("ES Verifactu Billing Record", r.name),
			],
			[
				__("Tipo"),
				(r) =>
					erpnext_spain.fiscal_tab.text(erpnext_spain.fiscal_tab.label(r.record_type)),
			],
			[__("Estado"), (r) => erpnext_spain.fiscal_tab.status(r.status)],
			[__("Fecha"), (r) => erpnext_spain.fiscal_tab.date(r.creation)],
			[
				__("Error"),
				(r) => erpnext_spain.fiscal_tab.error(r.response_error_code, r.response_error_msg),
			],
		],
	},
	{
		key: "sii",
		title: __("Registros del SII"),
		doctype: "ES Sii Record",
		columns: [
			[__("Registro"), (r) => erpnext_spain.fiscal_tab.link("ES Sii Record", r.name)],
			[__("Comunicación"), (r) => erpnext_spain.fiscal_tab.text(r.communication)],
			[__("Estado"), (r) => erpnext_spain.fiscal_tab.status(r.status)],
			[__("Plazo"), (r) => erpnext_spain.fiscal_tab.date(r.deadline)],
			[__("Último intento"), (r) => erpnext_spain.fiscal_tab.date(r.last_attempt)],
			[__("CSV"), (r) => erpnext_spain.fiscal_tab.text(r.csv)],
			[
				__("Error"),
				(r) => erpnext_spain.fiscal_tab.error(r.error_code, r.error_description),
			],
		],
	},
	{
		key: "einvoice",
		title: __("Factura electrónica"),
		doctype: "ES E-Invoice",
		columns: [
			[__("Documento"), (r) => erpnext_spain.fiscal_tab.link("ES E-Invoice", r.name)],
			[__("Formato"), (r) => erpnext_spain.fiscal_tab.text(r.format)],
			[__("Canal"), (r) => erpnext_spain.fiscal_tab.text(r.channel)],
			[__("Estado"), (r) => erpnext_spain.fiscal_tab.status(r.status)],
			[__("Registro FACe"), (r) => erpnext_spain.fiscal_tab.text(r.face_registry_number)],
			[__("Modificado"), (r) => erpnext_spain.fiscal_tab.date(r.modified)],
		],
	},
];

erpnext_spain.fiscal_tab.render = function (data) {
	const blocks = erpnext_spain.fiscal_tab.BLOCKS.filter(
		(block) => (data[block.key] || []).length
	);
	if (!blocks.length) {
		return `<p class="text-muted">${__("Sin envíos todavía.")}</p>`;
	}
	return blocks
		.map((block) => {
			const head = block.columns
				.map(([label]) => `<th>${erpnext_spain.fiscal_tab.text(label)}</th>`)
				.join("");
			const rows = data[block.key]
				.map(
					(row) =>
						`<tr>${block.columns
							.map(([, cell]) => `<td>${cell(row)}</td>`)
							.join("")}</tr>`
				)
				.join("");
			return `<h6 class="mt-3">${erpnext_spain.fiscal_tab.text(block.title)}</h6>
				<div class="table-responsive"><table class="table table-bordered table-sm">
				<thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
		})
		.join("");
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

	const wrapper =
		frm.fields_dict.es_fiscal_history && frm.fields_dict.es_fiscal_history.$wrapper;
	if (wrapper) {
		wrapper.html(show_history ? erpnext_spain.fiscal_tab.render(data) : "");
	}
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
