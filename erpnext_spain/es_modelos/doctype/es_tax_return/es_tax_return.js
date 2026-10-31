// Declaraciones de modelos AEAT (spec 07).

frappe.ui.form.on("ES Tax Return", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && !frm.is_new()) {
			frm.add_custom_button(__("Recalcular"), () =>
				frappe.call({
					method: "erpnext_spain.es_modelos.returns.recalculate",
					type: "POST",
					args: { name: frm.doc.name },
					freeze: true,
					callback() {
						frm.reload_doc();
					},
				})
			);
		}
		if (frm.doc.aeat_file) {
			frm.add_custom_button(__("Descargar fichero AEAT"), () =>
				window.open(frm.doc.aeat_file)
			);
		}
	},
});
