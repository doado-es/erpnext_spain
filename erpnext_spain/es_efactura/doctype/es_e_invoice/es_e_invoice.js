// ERPNext Spain · ES E-Invoice — descarga y registro manual en FACe (spec 10 §4).

frappe.ui.form.on("ES E-Invoice", {
	refresh(frm) {
		if (frm.doc.file) {
			frm.add_custom_button(__("Descargar XML firmado"), () => window.open(frm.doc.file));
		}
		const call = (method, args) =>
			frappe.call({
				method: `erpnext_spain.es_efactura.api.${method}`,
				type: "POST",
				args: { e_invoice: frm.doc.name, ...args },
				callback: () => frm.reload_doc(),
			});
		if (frm.doc.status === "Generada") {
			frm.add_custom_button(
				__("Registrar en FACe"),
				() =>
					frappe.prompt(
						[
							{
								fieldname: "registry_number",
								label: __("Número de registro en FACe"),
								fieldtype: "Data",
								reqd: 1,
							},
							{
								fieldname: "registry_date",
								label: __("Fecha de registro"),
								fieldtype: "Datetime",
								default: frappe.datetime.now_datetime(),
							},
						],
						(values) => call("register_in_face", values),
						__("Registrar en FACe"),
						__("Registrar")
					),
				__("FACe")
			);
		}
		if (
			frm.doc.face_registry_number &&
			!["Pagada", "Anulada", "Rechazada"].includes(frm.doc.status)
		) {
			frm.add_custom_button(
				__("Cambiar estado"),
				() =>
					frappe.prompt(
						[
							{
								fieldname: "status",
								label: __("Estado en FACe"),
								fieldtype: "Select",
								options: "Contabilizada\nPagada\nRechazada\nAnulada",
								reqd: 1,
							},
							{
								fieldname: "note",
								label: __("Observaciones"),
								fieldtype: "Small Text",
							},
						],
						(values) => call("set_status", values),
						__("Estado en FACe"),
						__("Guardar")
					),
				__("FACe")
			);
		}
	},
});
