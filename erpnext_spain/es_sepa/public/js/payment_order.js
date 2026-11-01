// Orden de pago: efectos por vencimiento y fichero SEPA de transferencias.

frappe.ui.form.on("Payment Order", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.payment_order_type !== "Payment Request") {
			frm.add_custom_button(__("Añadir efectos"), () =>
				erpnext_spain.es_sepa.add_payment_effects(frm)
			);
		}
		if (frm.doc.docstatus !== 1) return;
		if (!frappe.user.has_role(["Accounts Manager", "System Manager"])) return;
		frm.add_custom_button(
			__("Generar fichero SEPA"),
			() =>
				frappe.call({
					method: "erpnext_spain.es_sepa.credit_transfer.generate_credit_transfer",
					type: "POST",
					args: { payment_order: frm.doc.name },
					freeze: true,
					callback(r) {
						if (r.message) {
							frm.reload_doc();
							window.open(r.message);
						}
					},
				}),
			__("SEPA")
		);
		if (frm.doc.es_sepa_file) {
			frm.add_custom_button(
				__("Importar respuesta del banco (pain.002)"),
				() =>
					erpnext_spain.es_sepa.import_status(
						frm,
						"import_credit_transfer_status",
						"payment_order"
					),
				__("SEPA")
			);
		}
	},
});

frappe.provide("erpnext_spain.es_sepa");

erpnext_spain.es_sepa.import_status = function (frm, method, argument) {
	new frappe.ui.FileUploader({
		folder: "Home/Attachments",
		restrictions: { allowed_file_types: [".xml"] },
		on_success(file) {
			frappe.call({
				method: `erpnext_spain.es_sepa.${
					method === "import_credit_transfer_status" ? "credit_transfer" : "status"
				}.${method}`,
				type: "POST",
				args: { [argument]: frm.doc.name, file_url: file.file_url },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					frappe.msgprint(
						__("Aceptadas: {0}. Rechazadas: {1}.", [
							r.message.accepted,
							r.message.rejected,
						])
					);
					frm.reload_doc();
				},
			});
		},
	});
};

erpnext_spain.es_sepa.add_payment_effects = function (frm) {
	if (!frm.doc.company || !frm.doc.company_bank_account) {
		frappe.msgprint(__("Elija primero la compañía y su cuenta bancaria."));
		return;
	}
	const open = () =>
		frappe.require("/assets/erpnext_spain/js/effects_dialog.js", () =>
			erpnext_spain.effects_dialog.open(frm, {
				method: "erpnext_spain.es_sepa.payment_order.get_effects",
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
					{ fieldname: "iban", label: __("IBAN"), fieldtype: "Data" },
				],
				key: (row) => `${row.purchase_invoice}|${row.payment_term || ""}`,
				on_add: (rows) =>
					frappe
						.call({
							method: "erpnext_spain.es_sepa.payment_order.add_effects",
							type: "POST",
							freeze: true,
							args: {
								effects_to_add: rows.map((row) => ({
									purchase_invoice: row.purchase_invoice,
									supplier: row.supplier,
									payment_term: row.payment_term,
									amount: row.amount,
								})),
								payment_order: frm.is_new() ? null : frm.doc.name,
								company: frm.doc.company,
								company_bank_account: frm.doc.company_bank_account,
								posting_date: frm.doc.posting_date,
								execution_date: frm.doc.es_sepa_execution_date,
							},
						})
						.then((r) => {
							if (frm.is_new()) {
								frappe.set_route("Form", "Payment Order", r.message);
							} else {
								frm.reload_doc();
							}
						}),
			})
		);
	if (!frm.is_new() && frm.is_dirty()) {
		frm.save().then(open);
	} else {
		open();
	}
};
