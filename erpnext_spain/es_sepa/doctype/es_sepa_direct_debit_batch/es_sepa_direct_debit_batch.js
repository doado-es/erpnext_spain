// Remesa de adeudos SEPA.

frappe.ui.form.on("ES Sepa Direct Debit Batch", {
	refresh(frm) {
		frm.set_df_property("lines", "cannot_add_rows", true);
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Añadir efectos"), () =>
				erpnext_spain.es_sepa.add_effects(frm)
			);
		}
		if (frm.doc.docstatus === 1) {
			if (frm.doc.sepa_file) {
				frm.add_custom_button(__("Descargar fichero SEPA"), () =>
					window.open(frm.doc.sepa_file)
				);
			}
			frm.add_custom_button(__("Importar respuesta del banco (pain.002)"), () =>
				erpnext_spain.es_sepa.import_batch_status(frm)
			);
			frm.add_custom_button(__("Registrar devolución"), () =>
				erpnext_spain.es_sepa.register_return(frm)
			);
		}
	},
});

frappe.ui.form.on("ES Sepa Direct Debit Line", {
	lines_remove: (frm) => erpnext_spain.es_sepa.set_lines_total(frm),
	amount: (frm) => erpnext_spain.es_sepa.set_lines_total(frm),
});

frappe.provide("erpnext_spain.es_sepa");

erpnext_spain.es_sepa.add_effects = function (frm) {
	if (!frm.doc.company) {
		frappe.msgprint(__("Elija primero la compañía."));
		return;
	}
	frappe.require("/assets/erpnext_spain/js/effects_dialog.js", () =>
		erpnext_spain.effects_dialog.open(frm, {
			method: "erpnext_spain.es_sepa.direct_debit.get_effects",
			party: { fieldname: "customers", doctype: "Customer", label: __("Clientes") },
			args: (frm) => ({ company: frm.doc.company, scheme: frm.doc.scheme || "CORE" }),
			columns: [
				{
					fieldname: "sales_invoice",
					label: __("Factura"),
					fieldtype: "Link",
					options: "Sales Invoice",
				},
				{ fieldname: "customer_name", label: __("Cliente"), fieldtype: "Data" },
				{ fieldname: "payment_term", label: __("Vencimiento"), fieldtype: "Data" },
				{ fieldname: "due_date", label: __("Fecha"), fieldtype: "Date" },
				{ fieldname: "amount", label: __("Pendiente"), fieldtype: "Currency" },
				{ fieldname: "iban", label: __("IBAN"), fieldtype: "Data" },
			],
			key: (row) => `${row.sales_invoice}|${row.payment_term || ""}`,
			to_line: (row) => ({
				sales_invoice: row.sales_invoice,
				customer: row.customer,
				payment_term: row.payment_term,
				due_date: row.due_date,
				bank_account: row.bank_account,
				amount: row.amount,
			}),
		})
	);
};

erpnext_spain.es_sepa.import_batch_status = function (frm) {
	new frappe.ui.FileUploader({
		restrictions: { allowed_file_types: [".xml"] },
		on_success(file) {
			frappe.call({
				method: "erpnext_spain.es_sepa.status.import_direct_debit_status",
				type: "POST",
				args: { batch: frm.doc.name, file_url: file.file_url },
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

erpnext_spain.es_sepa.register_return = function (frm) {
	const lines = (frm.doc.lines || []).filter((row) => row.status === "Enviada");
	if (!lines.length) {
		frappe.msgprint(__("No hay adeudos enviados que se puedan devolver."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Registrar devolución"),
		fields: [
			{
				fieldname: "line",
				label: __("Factura"),
				fieldtype: "Select",
				options: lines.map((row) => ({
					value: row.name,
					label: `${row.sales_invoice} · ${row.customer}`,
				})),
				reqd: 1,
			},
			{
				fieldname: "reason_code",
				label: __("Código de motivo (p. ej. AM04, MD06)"),
				fieldtype: "Data",
			},
			{ fieldname: "charges", label: __("Gastos de devolución"), fieldtype: "Currency" },
		],
		primary_action_label: __("Registrar"),
		primary_action(values) {
			frappe.call({
				method: "erpnext_spain.es_sepa.status.register_return",
				type: "POST",
				args: {
					batch: frm.doc.name,
					line_name: values.line,
					reason_code: values.reason_code,
					charges: values.charges || 0,
				},
				freeze: true,
				callback() {
					dialog.hide();
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
};

erpnext_spain.es_sepa.set_lines_total = function (frm) {
	const total = (frm.doc.lines || []).reduce((sum, row) => sum + flt(row.amount), 0);
	frm.set_value("total_amount", total);
};
