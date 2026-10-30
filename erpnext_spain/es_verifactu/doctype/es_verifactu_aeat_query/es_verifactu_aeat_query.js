// Botón «Consultar AEAT» del form de ES Verifactu Aeat Query (spec 04 §10):
// llama al whitelisted consultar(name) y recarga el doc para mostrar el
// crudo y las filas devueltas por la AEAT.
//
// Cableado del doctype JS: este archivo vive en la carpeta del doctype con
// el nombre EXACTO del doctype scrubbed — frappe lo inyecta SOLO al form de
// «ES Verifactu Aeat Query» (frappe/desk/form/meta.py add_code:
// <doctype>.js). El hook `doctype_js` de hooks.py es para doctypes de OTRAS
// apps (Company, Sales Invoice): apuntarlo AQUÍ además cargaría el script
// dos veces (dos botones).

frappe.ui.form.on("ES Verifactu Aeat Query", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Consultar AEAT"), () => {
			frappe.call({
				method: "erpnext_spain.es_verifactu.doctype.es_verifactu_aeat_query.es_verifactu_aeat_query.query_aeat",
				args: { name: frm.doc.name },
				freeze: true,
				freeze_message: __("Consultando los registros de facturación en la AEAT…"),
				callback(r) {
					if (!r.exc) {
						frm.reload_doc();
					}
				},
			});
		});
	},
});
