// Clientes y proveedores: datos fiscales frente a la AEAT.
//
// 1. Persona física: aviso del formato de nombre para los suministros a la AEAT
//    (VeriFactu, SII). La AEAT contrasta NIF y nombre con su censo, que guarda a
//    las personas físicas como «APELLIDO APELLIDO NOMBRE»; con otro orden VeriFactu
//    rechaza el envío (error 103 «NIF no identificado»). Es persona física si el
//    tipo de persona es «Física» o, sin tipo, si el NIF es un DNI o un NIE.
// 2. Indicador del contraste con el censo de la AEAT junto al NIF (verde, naranja,
//    rojo o gris), botón «Contrastar con la AEAT» y, si el censo tiene otro
//    nombre, «Usar el nombre del censo» (nif/aeat_census.py).

frappe.provide("erpnext_spain.nif");

erpnext_spain.nif.NAME_FIELDS = { Customer: "customer_name", Supplier: "supplier_name" };

erpnext_spain.nif.NAME_FORMAT_HINTS = {
	Customer: __(
		"A efectos de suministros tributarios, el formato de nombre de cliente debe ser APELLIDO APELLIDO NOMBRE."
	),
	Supplier: __(
		"A efectos de suministros tributarios, el formato de nombre de proveedor debe ser APELLIDO APELLIDO NOMBRE."
	),
};

erpnext_spain.nif.STATUS_COLORS = {
	Identificado: "green",
	"Nombre distinto": "orange",
	"No identificado": "red",
	"Respuesta no reconocida": "orange",
};

erpnext_spain.nif.clean_nif = function (tax_id) {
	return (tax_id || "")
		.toUpperCase()
		.replace(/[^0-9A-Z]/g, "")
		.replace(/^ES(?=.{9}$)/, "");
};

erpnext_spain.nif.is_spanish = function (tax_id) {
	return /^([0-9]{8}[A-Z]|[KLMXYZ][0-9]{7}[A-Z]|[A-HJNP-SUVW][0-9]{7}[0-9A-J])$/.test(
		erpnext_spain.nif.clean_nif(tax_id)
	);
};

erpnext_spain.nif.is_individual = function (doc) {
	if (doc.es_person_type) {
		return doc.es_person_type === "Física";
	}
	return /^([0-9]{8}[A-Z]|[KLMXYZ][0-9]{7}[A-Z])$/.test(erpnext_spain.nif.clean_nif(doc.tax_id));
};

erpnext_spain.nif.toggle_name_hint = function (frm) {
	const hint = erpnext_spain.nif.is_individual(frm.doc)
		? erpnext_spain.nif.NAME_FORMAT_HINTS[frm.doctype]
		: "";
	frm.set_df_property(erpnext_spain.nif.NAME_FIELDS[frm.doctype], "description", hint);
};

// Indicador junto al NIF (descripción del campo tax_id).
erpnext_spain.nif.show_census_indicator = function (frm) {
	if (!erpnext_spain.nif.is_spanish(frm.doc.tax_id)) {
		frm.set_df_property("tax_id", "description", "");
		return;
	}
	const status = frm.doc.es_aeat_status;
	let label = __("Sin contrastar con la AEAT");
	let color = "gray";
	if (status) {
		color = erpnext_spain.nif.STATUS_COLORS[status] || "orange";
		const detail = [
			frm.doc.es_aeat_source,
			frappe.datetime.str_to_user(frm.doc.es_aeat_checked_on),
		]
			.filter(Boolean)
			.join(" · ");
		label = __("AEAT: {0}", [__(status)]) + (detail ? ` (${detail})` : "");
	}
	frm.set_df_property(
		"tax_id",
		"description",
		`<span class="indicator-pill ${color}">${frappe.utils.escape_html(label)}</span>`
	);
};

erpnext_spain.nif.add_census_buttons = function (frm) {
	if (frm.is_new() || !erpnext_spain.nif.is_spanish(frm.doc.tax_id)) {
		return;
	}
	frm.add_custom_button(
		__("Contrastar con la AEAT"),
		() =>
			frappe.call({
				method: "erpnext_spain.nif.aeat_census.check_parties",
				type: "POST",
				args: { doctype: frm.doctype, names: [frm.doc.name] },
				freeze: true,
				freeze_message: __("Consultando el censo de la AEAT..."),
				callback: () => frm.reload_doc(),
			}),
		__("Acciones")
	);
	const census_name = frm.doc.es_aeat_census_name;
	if (frm.doc.es_aeat_status === "Nombre distinto" && census_name) {
		frm.add_custom_button(
			__("Usar el nombre del censo"),
			() =>
				frappe.confirm(
					__("¿Cambiar el nombre a «{0}», como figura en el censo de la AEAT?", [
						frappe.utils.escape_html(census_name),
					]),
					() => {
						frm.set_value(erpnext_spain.nif.NAME_FIELDS[frm.doctype], census_name);
						frm.save();
					}
				),
			__("Acciones")
		);
	}
};

erpnext_spain.nif.refresh = function (frm) {
	erpnext_spain.nif.toggle_name_hint(frm);
	erpnext_spain.nif.show_census_indicator(frm);
	erpnext_spain.nif.add_census_buttons(frm);
};

erpnext_spain.nif.on_tax_id = function (frm) {
	erpnext_spain.nif.toggle_name_hint(frm);
	erpnext_spain.nif.show_census_indicator(frm);
};

// El mismo fichero se carga con los dos formularios: eventos una sola vez.
if (!erpnext_spain.nif_party_events) {
	erpnext_spain.nif_party_events = true;
	["Customer", "Supplier"].forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh: (frm) => erpnext_spain.nif.refresh(frm),
			tax_id: (frm) => erpnext_spain.nif.on_tax_id(frm),
			es_person_type: (frm) => erpnext_spain.nif.toggle_name_hint(frm),
		});
	});
}
