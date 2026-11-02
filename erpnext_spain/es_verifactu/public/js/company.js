// Spain Compliance · VeriFactu — UX del form de Company (spec 04 §2.1, §15).
//
// Único JS del lote de configuración: los behaviors del lado Company.
// La visibilidad por activación la resuelven los `depends_on` declarativos de
// los Custom Fields; aquí van los avisos legales del toggle (la frontera
// dura son las validaciones server), el banner discreto de modo pruebas y la
// congelación read-only de la fecha de activación.
//
// Nota anti-bucle (defecto de la referencia corregido): revertir el checkbox
// con frm.set_value re-dispara ESTE handler; se guarda con un flag para no
// encadenar diálogos infinitos.

frappe.provide("erpnext_spain.es_verifactu");

let reverting = false;

erpnext_spain.es_verifactu.revert_enabled = function (frm, value) {
	reverting = true;
	frm.set_value("es_verifactu_enabled", value);
};

erpnext_spain.es_verifactu.activation_message = function () {
	return (
		__("Va a activar VeriFactu para esta empresa. Consecuencias legales:") +
		"<br><br>" +
		[
			__(
				"Desde la fecha de activación, toda factura emitida genera registros de facturación encadenados (huellas criptográficas) que se remiten a la AEAT."
			),
			__(
				"Los borradores pasarán a nombre temporal: el número fiscal solo se asigna al emitir."
			),
			__("No se podrán fechar facturas hacia atrás."),
			__(
				"Los amendments quedan bloqueados: para corregir una factura emitida se usan facturas rectificativas (R1–R5)."
			),
			__("Se inicia una cadena que queda como libro inmutable."),
		]
			.map((item) => "• " + item)
			.join("<br>") +
		"<br><br>" +
		__("¿Desea continuar?")
	);
};

erpnext_spain.es_verifactu.deactivation_message = function (pending) {
	let msg =
		__("Va a desactivar VeriFactu. Tenga presente:") +
		"<br><br>" +
		[
			__(
				"Si la empresa está legalmente obligada a VeriFactu, desactivarlo supone incumplimiento (facturas emitidas sin registro ni remisión)."
			),
			__("La cadena se congela: al reactivar se CONTINÚA la misma cadena, no empieza otra."),
			__("Los registros pendientes de envío seguirán remitiéndose a la AEAT."),
			__(
				"Las facturas emitidas durante el período activo siguen siendo anulables con su Registro de Anulación: el libro no desaparece."
			),
		]
			.map((item) => "• " + item)
			.join("<br>");

	if (pending > 0) {
		msg +=
			"<br><br>" +
			__("Hay {0} registros pendientes de envío, que seguirán drenándose.", [pending]);
	}

	return msg + "<br><br>" + __("¿Desea continuar?");
};

erpnext_spain.es_verifactu.test_mode_banner = function (frm) {
	if (frm.doc.es_verifactu_enabled && frm.doc.es_verifactu_test_mode === "Pruebas") {
		frm.set_intro(__("Verifactu en modo pruebas"), "red");
	}
};

erpnext_spain.es_verifactu.freeze_activation_date = function (frm) {
	if (frm.doc.__islocal || !frm.doc.es_verifactu_activation_date) {
		return;
	}
	frappe.call({
		method: "erpnext_spain.es_verifactu.api.verifactu_status",
		args: { company: frm.doc.name },
		callback: function (r) {
			if (r.message && r.message.frozen) {
				frm.set_df_property("es_verifactu_activation_date", "read_only", 1);
			}
		},
	});
};

erpnext_spain.es_verifactu.confirm_deactivation = function (frm) {
	const confirm = function (pending) {
		frappe.confirm(
			erpnext_spain.es_verifactu.deactivation_message(pending || 0),
			function () {},
			function () {
				erpnext_spain.es_verifactu.revert_enabled(frm, 1);
			}
		);
	};

	if (frm.doc.__islocal || !frm.doc.name) {
		confirm(0);
		return;
	}
	frappe.call({
		method: "erpnext_spain.es_verifactu.api.verifactu_status",
		args: { company: frm.doc.name },
		callback: function (r) {
			confirm(r.message ? r.message.pending : 0);
		},
		error: function () {
			confirm(0);
		},
	});
};

frappe.ui.form.on("Company", {
	refresh: function (frm) {
		erpnext_spain.es_verifactu.test_mode_banner(frm);
		erpnext_spain.es_verifactu.freeze_activation_date(frm);
	},
	es_verifactu_enabled: function (frm) {
		if (reverting) {
			reverting = false;
			return;
		}
		if (frm.doc.es_verifactu_enabled) {
			frappe.confirm(
				erpnext_spain.es_verifactu.activation_message(),
				function () {},
				function () {
					erpnext_spain.es_verifactu.revert_enabled(frm, 0);
				}
			);
		} else {
			erpnext_spain.es_verifactu.confirm_deactivation(frm);
		}
	},
});
