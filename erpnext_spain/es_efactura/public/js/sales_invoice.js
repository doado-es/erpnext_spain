// ERPNext Spain · ES Efactura — botón «Generar Facturae» en la factura de venta (spec 10).

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.es_einvoice) {
			frm.add_custom_button(
				__("Ver factura electrónica"),
				() => frappe.set_route("Form", "ES E-Invoice", frm.doc.es_einvoice),
				__("Factura electrónica")
			);
		}
		if (
			!["Registrada en FACe", "Contabilizada", "Pagada"].includes(frm.doc.es_einvoice_status)
		) {
			frm.add_custom_button(
				__("Generar Facturae"),
				() =>
					frappe.call({
						method: "erpnext_spain.es_efactura.api.generate_facturae",
						type: "POST",
						args: { sales_invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Generando y firmando el Facturae…"),
						callback(r) {
							if (r.message) frappe.set_route("Form", "ES E-Invoice", r.message);
						},
					}),
				__("Factura electrónica")
			);
		}
	},
});
