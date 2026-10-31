// Cliente persona física: aviso del formato de nombre para los suministros a la
// AEAT (VeriFactu, SII). La AEAT contrasta NIF y nombre con su censo, que guarda a
// las personas físicas como «APELLIDO APELLIDO NOMBRE»; con otro orden rechaza el
// envío (error 103 «NIF no identificado»).
//
// Es persona física si el tipo de persona es «Física» o, sin tipo, si el NIF es un
// DNI o un NIE (mismo criterio que es_efactura y nif/validator.py).

frappe.provide("erpnext_spain.nif");

erpnext_spain.nif.NAME_FORMAT_HINT = __(
	"A efectos de suministros tributarios, el formato de nombre de cliente debe ser APELLIDO APELLIDO NOMBRE."
);

erpnext_spain.nif.is_individual = function (doc) {
	if (doc.es_person_type) {
		return doc.es_person_type === "Física";
	}
	const tax_id = (doc.tax_id || "")
		.toUpperCase()
		.replace(/[\s.-]/g, "")
		.replace(/^ES/, "");
	return /^[0-9]{8}[A-Z]$/.test(tax_id) || /^[KLMXYZ][0-9]{7}[A-Z]$/.test(tax_id);
};

erpnext_spain.nif.toggle_name_hint = function (frm) {
	const hint = erpnext_spain.nif.is_individual(frm.doc)
		? erpnext_spain.nif.NAME_FORMAT_HINT
		: "";
	frm.set_df_property("customer_name", "description", hint);
};

frappe.ui.form.on("Customer", {
	refresh: erpnext_spain.nif.toggle_name_hint,
	tax_id: erpnext_spain.nif.toggle_name_hint,
	es_person_type: erpnext_spain.nif.toggle_name_hint,
});
