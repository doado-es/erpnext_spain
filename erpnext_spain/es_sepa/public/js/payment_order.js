// ERPNext Spain · ES Sepa — fichero de transferencias de la orden de pago (spec 11 §4).

frappe.ui.form.on("Payment Order", {
	refresh(frm) {
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
