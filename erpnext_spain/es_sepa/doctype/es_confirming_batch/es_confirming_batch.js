// Remesa de confirming.

frappe.ui.form.on("ES Confirming Batch", {
	refresh(frm) {
		frm.set_df_property("lines", "cannot_add_rows", true);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Añadir efectos"), () =>
				erpnext_spain.es_sepa.add_confirming_effects(frm)
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

frappe.ui.form.on("ES Confirming Line", {
	lines_remove: (frm) => erpnext_spain.es_sepa.set_lines_total(frm),
	amount: (frm) => erpnext_spain.es_sepa.set_lines_total(frm),
});

frappe.provide("erpnext_spain.es_sepa");

erpnext_spain.es_sepa.add_confirming_effects = function (frm) {
	if (!frm.doc.company) {
		frappe.msgprint(__("Elija primero la compañía."));
		return;
	}
	frappe.require("/assets/erpnext_spain/js/effects_dialog.js", () =>
		erpnext_spain.effects_dialog.open(frm, {
			method: "erpnext_spain.es_sepa.confirming.get_effects",
			party: { fieldname: "suppliers", doctype: "Supplier", label: __("Proveedores") },
			args: (frm) => ({ company: frm.doc.company }),
			columns: [
				{
					fieldname: "purchase_invoice",
					label: __("Factura"),
					fieldtype: "Link",
					options: "Purchase Invoice",
				},
				{ fieldname: "supplier_name", label: __("Proveedor"), fieldtype: "Data" },
				{ fieldname: "bill_no", label: __("N.º del proveedor"), fieldtype: "Data" },
				{ fieldname: "payment_term", label: __("Vencimiento"), fieldtype: "Data" },
				{ fieldname: "due_date", label: __("Fecha"), fieldtype: "Date" },
				{ fieldname: "amount", label: __("Pendiente"), fieldtype: "Currency" },
			],
			key: (row) => `${row.purchase_invoice}|${row.payment_term || ""}`,
			to_line: (row) => ({
				purchase_invoice: row.purchase_invoice,
				supplier: row.supplier,
				payment_term: row.payment_term,
				bill_no: row.bill_no,
				bill_date: row.bill_date,
				due_date: row.due_date,
				amount: row.amount,
			}),
		})
	);
};

erpnext_spain.es_sepa.set_lines_total = function (frm) {
	const total = (frm.doc.lines || []).reduce((sum, row) => sum + flt(row.amount), 0);
	frm.set_value("total_amount", total);
};
