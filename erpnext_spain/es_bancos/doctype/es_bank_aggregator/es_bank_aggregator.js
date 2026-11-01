// Agregador bancario: función experimental.

frappe.ui.form.on("ES Bank Aggregator", {
	refresh(frm) {
		frm.set_intro(
			__(
				"Función experimental: solo existe el proveedor simulado para pruebas. No la use con cuentas reales."
			),
			"orange"
		);
	},
});
