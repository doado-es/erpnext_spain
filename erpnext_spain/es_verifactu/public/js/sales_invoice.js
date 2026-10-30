// Spain Compliance · VeriFactu — UX del form de Sales Invoice (spec 04 §15,
// lote 6a). UN solo archivo con TODOS los behaviors del lado factura:
//
// 1. Banner modo pruebas: si la factura SUBMITIDA lleva el snapshot
//    «Verifactu en pruebas» (es_verifactu_mode, congelado al emitir) O es un
//    borrador cuya compañía opera en pruebas (lectura barata del maestro),
//    intro visible: las remisiones NO tienen validez fiscal. Patrón set_intro:
//    limpiar PRIMERO (frm.set_intro("")), refrescar en `refresh` + cambio de
//    `company` (el banner de company.js es el espejo del form de Company).
// 2. Subsanación (spec 04 §9): si el último registro del libro de la factura
//    está marcado «Subsanable» (get_rectification_state), botón «Subsanar» que
//    abre el dialog por código de error (get_dialog_fields, con defaults de
//    la factura) y reenvía vía `rectify` → reload. Los errores del server
//    se muestran tal cual (glue v1).

frappe.provide("erpnext_spain.es_verifactu");

TEST_MODE = "Verifactu en pruebas";

// --- banner modo pruebas (spec 04 §15) ------------------------------------

erpnext_spain.es_verifactu.invoice_test_mode_banner = function (frm) {
	// SIEMPRE limpiar primero: el intro de la petición anterior no debe
	// sobrevivir (patrón set_intro del spec).
	frm.set_intro("");

	if (frm.doc.docstatus === 1 && frm.doc.es_verifactu_mode === TEST_MODE) {
		frm.set_intro(
			__(
				"⚠ Modo VeriFactu EN PRUEBAS — las remisiones van al entorno de pruebas de la AEAT y NO tienen validez fiscal."
			),
			"orange"
		);
		return;
	}

	// Borrador: sin snapshot aún — el modo lo trae la compañía (lectura barata
	// por clave primaria, una sola fila).
	if (frm.doc.docstatus === 0 && frm.doc.company) {
		// Solo si VeriFactu está ACTIVADO: el modo «Pruebas» es el valor por
		// defecto del campo y queda guardado aunque VeriFactu esté apagado.
		frappe.db.get_value("Company", frm.doc.company, ["es_verifactu_enabled", "es_verifactu_test_mode"]).then((r) => {
			const company = (r && r.message) || {};
			if (company.es_verifactu_enabled && company.es_verifactu_test_mode === "Pruebas") {
				// solo si el intro no lo puso ya otra vía (carrera refresh/company)
				frm.set_intro("");
				frm.set_intro(
					__(
						"⚠ Modo VeriFactu EN PRUEBAS — las remisiones van al entorno de pruebas de la AEAT y NO tienen validez fiscal."
					),
					"orange"
				);
			}
		});
	}
};

// --- subsanación (spec 04 §9) ----------------------------------------------

erpnext_spain.es_verifactu.show_rectify_button = function (frm) {
	if (frm.doc.docstatus !== 1) {
		return;
	}
	frappe.call({
		method: "erpnext_spain.es_verifactu.rectification.get_rectification_state",
		args: { invoice: frm.doc.name },
		callback: function (r) {
			const state = r.message;
			if (!state || !state.rectifiable) {
				return;
			}
			frm.add_custom_button(__("Subsanar"), function () {
				erpnext_spain.es_verifactu.open_rectification_dialog(frm, state);
			});
		},
	});
};

erpnext_spain.es_verifactu.open_rectification_dialog = function (frm, state) {
	frappe.call({
		method: "erpnext_spain.es_verifactu.rectification.get_dialog_fields",
		args: { error_code: state.error_code },
		callback: function (r) {
			const fields = r.message || [];

			// Defaults de la factura (la referencia los inyecta en sitio):
			// el registro se regenera desde el estado ACTUAL del doc.
			const defaults = {
				series_number: frm.doc.name,
				customer: frm.doc.customer,
				customer_tax_id: frm.doc.tax_id,
				error_code: state.error_code,
				error_description: state.error_description,
			};
			for (const field of fields) {
				if (field.fieldname && defaults[field.fieldname] != null) {
					field.default = defaults[field.fieldname];
				}
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Subsanar factura {0}", [frm.doc.name]),
				fields: fields,
				primary_action_label: __("Subsanar"),
				primary_action: function () {
					frappe.call({
						method: "erpnext_spain.es_verifactu.rectification.rectify",
						args: { invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Regenerando el registro de la factura…"),
						callback: function () {
							dialog.hide();
							// v16: el API es reload_doc (frm.reload no existe en v16).
							frm.reload_doc();
						},
					});
					// sin handler de error: el server error se muestra tal cual
					// (glue v1) y el dialog queda abierto para corregir y reintentar.
				},
			});
			dialog.show();
		},
	});
};

frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		erpnext_spain.es_verifactu.invoice_test_mode_banner(frm);
		erpnext_spain.es_verifactu.show_rectify_button(frm);
	},
	company: function (frm) {
		erpnext_spain.es_verifactu.invoice_test_mode_banner(frm);
	},
});
