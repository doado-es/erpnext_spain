// Remesa de adeudos SEPA (spec 11 §5-§6).

frappe.ui.form.on("ES Sepa Direct Debit Batch", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Traer facturas domiciliadas"), () =>
				frappe.call({
					method: "erpnext_spain.es_sepa.direct_debit.get_invoices",
					args: {
						company: frm.doc.company,
						scheme: frm.doc.scheme,
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

frappe.provide("erpnext_spain.es_sepa");

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
