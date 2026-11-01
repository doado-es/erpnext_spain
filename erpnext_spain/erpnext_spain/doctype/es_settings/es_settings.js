// Ajustes de España: acceso al mapa de cuentas de impuestos de cada compañía.

frappe.ui.form.on("ES Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Mapa de cuentas de impuestos"), () =>
			frappe.set_route("query-report", "ES Tax Accounts")
		);
	},
});
