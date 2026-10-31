// Importación de extractos Norma 43 (spec 13 §2).

frappe.ui.form.on("ES Norma43 Import", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.norma43_file) return;
		frm.add_custom_button(__("Importar movimientos"), () =>
			frappe.call({
				method: "erpnext_spain.es_bancos.importer.run_norma43_import",
				type: "POST",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __("Importando movimientos…"),
				callback() {
					frm.reload_doc();
				},
			})
		).addClass("btn-primary");
	},
});
