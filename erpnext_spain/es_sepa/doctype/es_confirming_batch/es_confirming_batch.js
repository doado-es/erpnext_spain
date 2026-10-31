// Remesa de confirming (spec 12).

frappe.ui.form.on("ES Confirming Batch", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Traer facturas de confirming"), () =>
				frappe.call({
					method: "erpnext_spain.es_sepa.confirming.get_invoices",
					args: {
						company: frm.doc.company,
						from_due_date: frm.doc.from_due_date,
						to_due_date: frm.doc.to_due_date,
					},
					callback(r) {
						frm.clear_table("lines");
						for (const row of r.message || []) frm.add_child("lines", row);
						frm.refresh_field("lines");
					},
				})
			);
		}
		if (frm.doc.docstatus === 1) {
			if (frm.doc.confirming_file) {
				frm.add_custom_button(__("Descargar fichero"), () =>
					window.open(frm.doc.confirming_file)
				);
			}
			if (!frm.doc.maturity_registered) {
				frm.add_custom_button(__("Registrar cargo al vencimiento"), () =>
					frappe.prompt(
						{
							fieldname: "charge_date",
							label: __("Fecha del cargo"),
							fieldtype: "Date",
							reqd: 1,
							default: frappe.datetime.get_today(),
						},
						(values) =>
							frappe.call({
								method: "erpnext_spain.es_sepa.confirming.register_maturity",
								type: "POST",
								args: { batch: frm.doc.name, charge_date: values.charge_date },
								freeze: true,
								callback() {
									frm.reload_doc();
								},
							}),
						__("Cargo al vencimiento")
					)
				);
			}
		}
	},
});
