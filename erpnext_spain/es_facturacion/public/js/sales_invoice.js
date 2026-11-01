// ERPNext Spain · ES Facturacion — situación de cobro en la factura de venta (spec 05 §4).

frappe.provide("erpnext_spain.es_facturacion");

erpnext_spain.es_facturacion.COLLECTION_ACTIONS = [
	{
		label: __("Pasar a dudoso cobro"),
		method: "mark_doubtful",
		when: (doc) => !doc.es_collection_status || doc.es_collection_status === "Normal",
		needs_outstanding: true,
		confirm: __(
			"Se traspasa el importe pendiente de la 4300 a la 4360 (clientes de dudoso cobro)."
		),
	},
	{
		label: __("Dotar deterioro"),
		method: "provision_impairment",
		when: (doc) => doc.es_collection_status === "Dudoso cobro" && !doc.es_impairment_entry,
		confirm: __("Se contabiliza el deterioro del crédito: 6940 a 4900."),
	},
	{
		label: __("Declarar pérdida definitiva"),
		method: "declare_loss",
		when: (doc) => doc.es_collection_status === "Dudoso cobro",
		confirm: __(
			"Se da de baja el crédito (6500 a 4360) y se revierte el deterioro si lo hay."
		),
	},
	{
		label: __("Recuperar"),
		method: "recover",
		when: (doc) => doc.es_collection_status === "Dudoso cobro",
		confirm: __(
			"La factura vuelve a situación normal: 4300 a 4360 y reversión del deterioro."
		),
	},
];

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.is_return) return;
		if (!frappe.user.has_role(["Accounts Manager", "System Manager"])) return;
		for (const action of erpnext_spain.es_facturacion.COLLECTION_ACTIONS) {
			if (!action.when(frm.doc)) continue;
			if (action.needs_outstanding && !(frm.doc.outstanding_amount > 0)) continue;
			frm.add_custom_button(
				action.label,
				() =>
					frappe.confirm(action.confirm, () =>
						frappe.call({
							method: `erpnext_spain.es_facturacion.collection.${action.method}`,
							type: "POST",
							args: { invoice: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frappe.show_alert({
									message: __("Asiento {0} creado", [r.message]),
									indicator: "green",
								});
								frm.reload_doc();
							},
						})
					),
				__("Situación de cobro")
			);
		}
	},
});

// --- TPV y tipo de factura por defecto -------------------------------------
//
// Al validar, el borrador se renombra al número fiscal. Frappe avisa en tiempo
// real del cambio de nombre a quien tenga abierto el borrador y ese aviso
// llevaría al cajero del TPV al formulario de la factura. El TPV deja de
// escuchar el borrador antes de validar y, al terminar, escucha el nombre nuevo
// (el formulario ya lo tiene: el servidor devuelve el nombre anterior en
// `localname`, es_facturacion/numbering.rename_document).

erpnext_spain.es_facturacion.is_pos_form = (frm) => frm.doc.is_pos && !frm.in_form;

frappe.ui.form.on("Sales Invoice", {
	before_submit(frm) {
		if (erpnext_spain.es_facturacion.is_pos_form(frm)) {
			frappe.realtime.doc_unsubscribe(frm.doctype, frm.docname);
		}
	},
	on_submit(frm) {
		if (erpnext_spain.es_facturacion.is_pos_form(frm)) {
			frappe.realtime.doc_subscribe(frm.doctype, frm.docname);
		}
	},
	async customer(frm) {
		// El servidor aplica el mismo criterio al guardar (es_facturacion/pos.py).
		if (!frm.is_new() || !frm.doc.customer || !frm.fields_dict.es_invoice_type) return;
		const { message } = await frappe.db.get_value(
			"Customer",
			frm.doc.customer,
			"es_invoice_type"
		);
		const invoice_type = message && message.es_invoice_type;
		if (!invoice_type || invoice_type === frm.doc.es_invoice_type) return;
		const type = await frappe.db.get_value("ES Invoice Type", invoice_type, "is_simplified");
		if (type.message && type.message.is_simplified && !frm.doc.is_pos) return;
		frm.set_value("es_invoice_type", invoice_type);
	},
});
