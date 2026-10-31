// Avisos al cambiar el modo de VeriFactu y del SII en la compañía.
//
// Cada sistema tiene tres estados: desactivado, pruebas y producción. Al pasar de
// uno a otro se pide confirmación con un aviso claro (activar, pasar a producción,
// volver a pruebas, desactivar); si se cancela, el campo vuelve a su valor. Los
// cambios quedan además en el historial de la compañía (Track Changes: quién y
// cuándo).

frappe.provide("erpnext_spain.modes");

erpnext_spain.modes.OFF = "off";
erpnext_spain.modes.TEST = "Pruebas";
erpnext_spain.modes.PRODUCTION = "Producción";

erpnext_spain.modes.HISTORY_NOTE = __(
	"El cambio queda registrado en el historial de la compañía (quién y cuándo)."
);

erpnext_spain.modes.SYSTEMS = {
	verifactu: {
		enabled: "es_verifactu_enabled",
		mode: "es_verifactu_test_mode",
		messages: {
			activate_test: [
				__("Activar VeriFactu en modo pruebas"),
				__(
					"Desde la fecha de activación, cada factura de venta que emita generará un registro de facturación encadenado que se enviará al <b>entorno de pruebas</b> de la AEAT."
				),
				__(
					"En pruebas los envíos <b>no tienen validez fiscal</b>, pero los registros quedan en el libro de la empresa y no se pueden borrar. Use una serie de facturas de prueba y anule esas facturas al terminar."
				),
			],
			to_production: [
				__("Pasar VeriFactu a PRODUCCIÓN"),
				__(
					"<b>Las facturas de venta se enviarán a la AEAT con plena validez fiscal.</b> Cada factura emitida queda registrada en la AEAT: no se podrá borrar ni modificar, solo anular o rectificar con otra factura."
				),
				__(
					"Compruebe antes el certificado de la empresa, el NIF y la razón social, la fecha de activación y las series de facturas, y que no quedan registros de prueba pendientes de envío. No use producción para hacer pruebas."
				),
			],
			to_test: [
				__("Volver VeriFactu a modo pruebas"),
				__(
					"<b>Las facturas que emita dejarán de enviarse a la AEAT con validez fiscal</b>: irán al entorno de pruebas."
				),
				__(
					"Si la empresa está obligada a usar VeriFactu, sus facturas reales deben enviarse en producción."
				),
			],
			deactivate: [
				__("Desactivar VeriFactu"),
				__(
					"<b>Las facturas nuevas no generarán registro de facturación ni se enviarán a la AEAT.</b> Los registros ya generados que estén pendientes se seguirán enviando."
				),
				__(
					"Si la empresa está obligada a usar un sistema de facturación verificable, necesitará otro (o el SII, si le corresponde)."
				),
			],
		},
	},
	sii: {
		enabled: "es_sii_enabled",
		mode: "es_sii_test_mode",
		messages: {
			activate_test: [
				__("Activar el SII en modo pruebas"),
				__(
					"Las facturas emitidas y recibidas con fecha de registro contable desde la fecha de inicio se enviarán al <b>entorno de pruebas</b> del SII, según la estrategia de envío de la compañía."
				),
				__("En pruebas los envíos <b>no tienen validez fiscal</b>."),
			],
			to_production: [
				__("Pasar el SII a PRODUCCIÓN"),
				__(
					"<b>Los libros registro de IVA se llevarán por el SII con plena validez fiscal:</b> cada factura enviada queda presentada ante la AEAT y rigen los plazos legales (4 días hábiles; las recibidas, como tarde el día 15 del mes siguiente)."
				),
				__(
					"Compruebe antes el certificado de la empresa, el NIF, las fechas de inicio y fin y la estrategia de envío. No use producción para hacer pruebas."
				),
			],
			to_test: [
				__("Volver el SII a modo pruebas"),
				__(
					"<b>Las facturas dejarán de presentarse ante la AEAT</b>: irán al entorno de pruebas."
				),
				__(
					"Si la empresa está obligada al SII, sus facturas reales deben enviarse en producción dentro de plazo."
				),
			],
			deactivate: [
				__("Desactivar el SII"),
				__(
					"<b>Las facturas nuevas no se enviarán al SII.</b> Los registros ya generados siguen en la lista de registros del SII."
				),
				__(
					"Si la empresa está obligada al SII, deberá presentar sus libros registro por otra vía y dentro de plazo."
				),
			],
		},
	},
};

erpnext_spain.modes.state = function (doc, system) {
	if (!doc[system.enabled]) return erpnext_spain.modes.OFF;
	return doc[system.mode] === erpnext_spain.modes.PRODUCTION
		? erpnext_spain.modes.PRODUCTION
		: erpnext_spain.modes.TEST;
};

erpnext_spain.modes.transition = function (before, after) {
	const { OFF, PRODUCTION } = erpnext_spain.modes;
	if (before === after) return null;
	if (after === OFF) return "deactivate";
	if (after === PRODUCTION) return "to_production";
	return before === OFF ? "activate_test" : "to_test";
};

// Estado confirmado de cada sistema: el guardado y, tras aceptar un aviso, el nuevo.
erpnext_spain.modes.remember = function (frm) {
	frm.__es_modes = {};
	for (const [key, system] of Object.entries(erpnext_spain.modes.SYSTEMS)) {
		frm.__es_modes[key] = {
			state: erpnext_spain.modes.state(frm.doc, system),
			enabled: frm.doc[system.enabled],
			mode: frm.doc[system.mode],
		};
	}
};

erpnext_spain.modes.on_change = function (frm, key) {
	if (frm.__es_reverting || !frm.__es_modes) return;
	const system = erpnext_spain.modes.SYSTEMS[key];
	const confirmed = frm.__es_modes[key];
	const after = erpnext_spain.modes.state(frm.doc, system);
	const transition = erpnext_spain.modes.transition(confirmed.state, after);
	if (!transition) return;

	const [title, ...paragraphs] = system.messages[transition];
	const body = [...paragraphs, erpnext_spain.modes.HISTORY_NOTE]
		.map((p) => `<p>${p}</p>`)
		.join("");
	let accepted = false;
	const dialog = frappe.warn(
		title,
		body,
		() => {
			accepted = true;
			frm.__es_modes[key] = {
				state: after,
				enabled: frm.doc[system.enabled],
				mode: frm.doc[system.mode],
			};
		},
		__("Sí, continuar"),
		false,
		__("No, dejarlo como estaba")
	);
	dialog.onhide = () => {
		if (accepted) return;
		frm.__es_reverting = true;
		Promise.all([
			frm.set_value(system.enabled, confirmed.enabled),
			frm.set_value(system.mode, confirmed.mode),
		]).finally(() => {
			frm.__es_reverting = false;
		});
	};
};

frappe.ui.form.on("Company", {
	refresh: (frm) => erpnext_spain.modes.remember(frm),
	after_save: (frm) => erpnext_spain.modes.remember(frm),
	es_verifactu_enabled: (frm) => erpnext_spain.modes.on_change(frm, "verifactu"),
	es_verifactu_test_mode: (frm) => erpnext_spain.modes.on_change(frm, "verifactu"),
	es_sii_enabled: (frm) => erpnext_spain.modes.on_change(frm, "sii"),
	es_sii_test_mode: (frm) => erpnext_spain.modes.on_change(frm, "sii"),
});
