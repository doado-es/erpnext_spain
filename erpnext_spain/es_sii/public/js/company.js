// ERPNext Spain · ES Sii — aviso de modo pruebas en Company (spec 14 §1).
// Solo aparece si el SII está activado y en modo pruebas.

frappe.ui.form.on("Company", {
	refresh(frm) {
		if (frm.doc.es_sii_enabled && frm.doc.es_sii_test_mode === "Pruebas") {
			frm.set_intro(__("SII en modo pruebas"), "red");
		}
	},
});
