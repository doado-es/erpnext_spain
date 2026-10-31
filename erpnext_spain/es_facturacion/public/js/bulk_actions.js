// ERPNext Spain — acciones masivas en las listas (spec 15, F1-F4).

frappe.provide("erpnext_spain.es_facturacion");

erpnext_spain.es_facturacion.selected = function (listview) {
	return listview.get_checked_items().map((row) => row.name);
};

erpnext_spain.es_facturacion.report = function (r) {
	if (!r.message) return;
	if (r.message.queued) {
		frappe.show_alert({
			message: __("Se procesará en segundo plano ({0} documentos).", [r.message.count]),
			indicator: "blue",
		});
		return;
	}
	const lines = [];
	if (r.message.invoices)
		lines.push(__("Facturas creadas: {0}", [r.message.invoices.join(", ") || "-"]));
	for (const row of r.message.skipped || []) lines.push(`${row.name}: ${row.reason}`);
	frappe.msgprint(lines.join("<br>") || __("Hecho"));
};

erpnext_spain.es_facturacion.invoice_delivery_notes = function (listview) {
	const names = erpnext_spain.es_facturacion.selected(listview);
	if (!names.length) return frappe.msgprint(__("Seleccione albaranes."));
	frappe.prompt(
		[
			{ fieldname: "group_by_period", label: __("Una factura por mes"), fieldtype: "Check" },
			{ fieldname: "submit", label: __("Validar las facturas"), fieldtype: "Check" },
		],
		(values) =>
			frappe.call({
				method: "erpnext_spain.es_facturacion.bulk.invoice_delivery_notes",
				type: "POST",
				args: { delivery_notes: names, ...values },
				freeze: true,
				callback: erpnext_spain.es_facturacion.report,
			}),
		__("Facturar albaranes")
	);
};

erpnext_spain.es_facturacion.invoice_purchase_receipts = function (listview) {
	const names = erpnext_spain.es_facturacion.selected(listview);
	if (!names.length) return frappe.msgprint(__("Seleccione albaranes de compra."));
	frappe.prompt(
		[
			{
				fieldname: "bill_no",
				label: __("Número de la factura del proveedor"),
				fieldtype: "Data",
				reqd: 1,
			},
			{
				fieldname: "bill_date",
				label: __("Fecha de la factura"),
				fieldtype: "Date",
				reqd: 1,
			},
			{ fieldname: "submit", label: __("Validar la factura"), fieldtype: "Check" },
		],
		(values) =>
			frappe.call({
				method: "erpnext_spain.es_facturacion.bulk.invoice_purchase_receipts",
				type: "POST",
				args: { purchase_receipts: names, ...values },
				freeze: true,
				callback(r) {
					if (r.message) frappe.set_route("Form", "Purchase Invoice", r.message);
				},
			}),
		__("Registrar factura del proveedor")
	);
};

erpnext_spain.es_facturacion.send_invoices = function (listview) {
	const names = erpnext_spain.es_facturacion.selected(listview);
	if (!names.length) return frappe.msgprint(__("Seleccione facturas."));
	frappe.prompt(
		[
			{
				fieldname: "group_by_customer",
				label: __("Un correo por cliente"),
				fieldtype: "Check",
			},
			{ fieldname: "resend", label: __("Reenviar las ya enviadas"), fieldtype: "Check" },
		],
		(values) =>
			frappe.call({
				method: "erpnext_spain.es_facturacion.mailing.send_invoices",
				type: "POST",
				args: { sales_invoices: names, ...values },
				callback: erpnext_spain.es_facturacion.report,
			}),
		__("Enviar facturas por correo")
	);
};

erpnext_spain.es_facturacion.check_tax_ids = function (listview) {
	const names = erpnext_spain.es_facturacion.selected(listview);
	if (!names.length) return frappe.msgprint(__("Seleccione terceros."));
	frappe.call({
		method: "erpnext_spain.nif.vies.check_parties",
		type: "POST",
		args: { doctype: listview.doctype, names: names },
		freeze: true,
		callback(r) {
			if (r.message && r.message.queued) return erpnext_spain.es_facturacion.report(r);
			listview.refresh();
			frappe.show_alert({ message: __("NIF comprobados"), indicator: "green" });
		},
	});
};

erpnext_spain.es_facturacion.send_to_sii = function (listview) {
	const names = erpnext_spain.es_facturacion.selected(listview);
	if (!names.length) return frappe.msgprint(__("Seleccione facturas."));
	frappe.call({
		method: "erpnext_spain.es_sii.outbox.send_invoices",
		type: "POST",
		args: { doctype: listview.doctype, names: names },
		freeze: true,
		freeze_message: __("Enviando al SII..."),
		callback(r) {
			if (!r.message) return;
			if (r.message.queued) return erpnext_spain.es_facturacion.report(r);
			const counts = {};
			for (const status of Object.values(r.message))
				counts[status] = (counts[status] || 0) + 1;
			const summary = Object.entries(counts)
				.map(([status, count]) => `${__(status)}: ${count}`)
				.join(" · ");
			frappe.show_alert({ message: __("SII: {0}", [summary]), indicator: "blue" }, 8);
			listview.refresh();
		},
	});
};

const ES_PARTY_ACTIONS = [[__("Comprobar NIF"), "check_tax_ids"]];

const ES_BULK_ACTIONS = {
	"Delivery Note": [[__("Facturar seleccionados"), "invoice_delivery_notes"]],
	"Purchase Receipt": [[__("Registrar factura del proveedor"), "invoice_purchase_receipts"]],
	"Sales Invoice": [
		[__("Enviar por correo"), "send_invoices"],
		[__("Enviar al SII"), "send_to_sii"],
	],
	"Purchase Invoice": [[__("Enviar al SII"), "send_to_sii"]],
	Customer: ES_PARTY_ACTIONS,
	Supplier: ES_PARTY_ACTIONS,
};

for (const [doctype, actions] of Object.entries(ES_BULK_ACTIONS)) {
	frappe.listview_settings[doctype] = frappe.listview_settings[doctype] || {};
	const settings = frappe.listview_settings[doctype];
	// El fichero se carga con la lista de cada uno de estos doctypes: sin repetir acciones.
	if (settings.__es_bulk_actions) continue;
	settings.__es_bulk_actions = true;
	const previous = settings.onload;
	settings.onload = function (listview) {
		if (previous) previous(listview);
		for (const [label, method] of actions) {
			listview.page.add_actions_menu_item(
				label,
				() => erpnext_spain.es_facturacion[method](listview),
				false
			);
		}
	};
}
