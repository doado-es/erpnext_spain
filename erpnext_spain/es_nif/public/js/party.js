// Clientes y proveedores: datos fiscales frente a la AEAT.
//
// 1. Persona física: aviso del formato de nombre para los suministros a la AEAT
//    (VeriFactu, SII). La AEAT contrasta NIF y nombre con su censo, que guarda a
//    las personas físicas como «APELLIDO APELLIDO NOMBRE»; con otro orden VeriFactu
//    rechaza el envío (error 103 «NIF no identificado»). Es persona física si el
//    NIF es un DNI o un NIE, o si el tipo de cliente o de proveedor es «Individual».
// 2. Marca de verificación dentro del campo NIF (mismo patrón que el botón de los
//    campos URL y Barcode de Frappe). Al pulsarla contrasta el NIF y el nombre del
//    formulario con el censo de la AEAT (es_nif/aeat_census.check_tax_id) y se pinta
//    verde, naranja (el censo tiene otro nombre: se ofrece usarlo) o roja. No se
//    guarda nada; vuelve a gris si cambian el NIF o el nombre.

frappe.provide("erpnext_spain.es_nif");

erpnext_spain.es_nif.NAME_FIELDS = { Customer: "customer_name", Supplier: "supplier_name" };

erpnext_spain.es_nif.NAME_FORMAT_HINTS = {
	Customer: __(
		"A efectos de suministros tributarios, el formato de nombre de cliente debe ser APELLIDO APELLIDO NOMBRE."
	),
	Supplier: __(
		"A efectos de suministros tributarios, el formato de nombre de proveedor debe ser APELLIDO APELLIDO NOMBRE."
	),
};

// Estado de la marca → [icono, color, texto].
erpnext_spain.es_nif.MARKS = {
	unchecked: ["badge-check", "var(--gray-500)", __("Contrastar NIF y nombre con la AEAT")],
	checking: ["loader-circle", "var(--gray-500)", __("Consultando el censo de la AEAT...")],
	Identificado: ["badge-check", "var(--green-500)", __("Identificado en el censo de la AEAT")],
	"Nombre distinto": [
		"badge-alert",
		"var(--orange-500)",
		__("La AEAT tiene otro nombre para este NIF"),
	],
	"No identificado": [
		"badge-x",
		"var(--red-500)",
		__("NIF no identificado en el censo de la AEAT"),
	],
	"Respuesta no reconocida": [
		"badge-alert",
		"var(--orange-500)",
		__("Respuesta no reconocida de la AEAT"),
	],
	error: ["badge-alert", "var(--red-500)", __("No se pudo consultar a la AEAT")],
};

erpnext_spain.es_nif.clean_nif = function (tax_id) {
	return (tax_id || "")
		.toUpperCase()
		.replace(/[^0-9A-Z]/g, "")
		.replace(/^ES(?=.{9}$)/, "");
};

erpnext_spain.es_nif.is_spanish = function (tax_id) {
	return /^([0-9]{8}[A-Z]|[KLMXYZ][0-9]{7}[A-Z]|[A-HJNP-SUVW][0-9]{7}[0-9A-J])$/.test(
		erpnext_spain.es_nif.clean_nif(tax_id)
	);
};

erpnext_spain.es_nif.TYPE_FIELDS = { Customer: "customer_type", Supplier: "supplier_type" };

erpnext_spain.es_nif.is_individual = function (doc) {
	if (doc[erpnext_spain.es_nif.TYPE_FIELDS[doc.doctype]] === "Individual") {
		return true;
	}
	return /^([0-9]{8}[A-Z]|[KLMXYZ][0-9]{7}[A-Z])$/.test(
		erpnext_spain.es_nif.clean_nif(doc.tax_id)
	);
};

// Solo en sitios con alguna compañía con el plan PGC (los terceros no son de una
// compañía): en el resto, el formulario es el estándar de ERPNext.
erpnext_spain.es_nif.active = function () {
	return !!(frappe.boot && frappe.boot.erpnext_spain_pgc);
};

erpnext_spain.es_nif.toggle_name_hint = function (frm) {
	if (!erpnext_spain.es_nif.active()) return;
	const hint = erpnext_spain.es_nif.is_individual(frm.doc)
		? erpnext_spain.es_nif.NAME_FORMAT_HINTS[frm.doctype]
		: "";
	frm.set_df_property(erpnext_spain.es_nif.NAME_FIELDS[frm.doctype], "description", hint);
};

// --- marca de verificación ---------------------------------------------------

erpnext_spain.es_nif.mark_button = function (frm) {
	const field = frm.fields_dict.tax_id;
	if (!field || !field.$wrapper) {
		return null;
	}
	let $button = field.$wrapper.find(".es-aeat-check");
	if (!$button.length) {
		$button = $(
			`<span class="link-btn es-aeat-check"><a class="btn-open no-decoration"></a></span>`
		).appendTo(field.$wrapper.find(".control-input"));
		$button.find("a").on("click", (event) => {
			event.preventDefault();
			erpnext_spain.es_nif.check(frm);
		});
	}
	return $button;
};

erpnext_spain.es_nif.set_mark = function (frm, state, detail) {
	if (!erpnext_spain.es_nif.active()) return;
	const $button = erpnext_spain.es_nif.mark_button(frm);
	if (!$button) {
		return;
	}
	const [icon, color, text] =
		erpnext_spain.es_nif.MARKS[state] || erpnext_spain.es_nif.MARKS.error;
	const title = detail ? `${text}: ${detail}` : text;
	$button.find("a").attr("title", title).css("color", color).html(frappe.utils.icon(icon, "sm"));
	$button.toggle(erpnext_spain.es_nif.is_spanish(frm.doc.tax_id));
};

erpnext_spain.es_nif.check = function (frm) {
	const name = frm.doc[erpnext_spain.es_nif.NAME_FIELDS[frm.doctype]];
	erpnext_spain.es_nif.set_mark(frm, "checking");
	frappe
		.call({
			method: "erpnext_spain.es_nif.aeat_census.check_tax_id",
			type: "POST",
			args: { doctype: frm.doctype, tax_id: frm.doc.tax_id, party_name: name },
		})
		.then((r) => {
			const result = r.message || {};
			erpnext_spain.es_nif.set_mark(frm, result.status, result.census_name || result.result);
			if (result.status === "Nombre distinto" && result.census_name) {
				erpnext_spain.es_nif.offer_census_name(frm, result.census_name);
			}
		})
		.catch(() => erpnext_spain.es_nif.set_mark(frm, "error"));
};

erpnext_spain.es_nif.offer_census_name = function (frm, census_name) {
	frappe.confirm(
		__("La AEAT tiene este NIF a nombre de «{0}». ¿Usar ese nombre?", [
			frappe.utils.escape_html(census_name),
		]),
		() =>
			frm
				.set_value(erpnext_spain.es_nif.NAME_FIELDS[frm.doctype], census_name)
				.then(() => erpnext_spain.es_nif.set_mark(frm, "Identificado"))
	);
};

erpnext_spain.es_nif.reset = function (frm) {
	erpnext_spain.es_nif.toggle_name_hint(frm);
	erpnext_spain.es_nif.set_mark(frm, "unchecked");
};

// --- datos de VIES ------------------------------------------------------------

erpnext_spain.es_nif.EU_PREFIXES = [
	"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "FI", "FR", "HR", "HU", "IE",
	"IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
]; // prettier-ignore

erpnext_spain.es_nif.is_eu_vat = function (tax_id) {
	const value = erpnext_spain.es_nif.clean_nif(tax_id);
	return value.length > 4 && erpnext_spain.es_nif.EU_PREFIXES.includes(value.slice(0, 2));
};

erpnext_spain.es_nif.vies_button = function (frm) {
	if (frm.is_new() || !erpnext_spain.es_nif.is_eu_vat(frm.doc.tax_id)) return;
	frm.add_custom_button(__("Completar con VIES"), () => {
		const run = () => erpnext_spain.es_nif.vies_dialog(frm);
		frm.is_dirty() ? frm.save().then(run) : run();
	});
};

erpnext_spain.es_nif.vies_dialog = function (frm) {
	frappe
		.call({
			method: "erpnext_spain.es_nif.vies.vies_details",
			type: "POST",
			freeze: true,
			args: { doctype: frm.doctype, name: frm.doc.name },
		})
		.then((r) => {
			const data = r.message || {};
			if (data.status !== "Válido") {
				frappe.msgprint(__("VIES: {0}", [data.status || __("sin respuesta")]));
				frm.reload_doc();
				return;
			}
			const name_field = erpnext_spain.es_nif.NAME_FIELDS[frm.doctype];
			const parsed = data.parsed_address;
			const dialog = new frappe.ui.Dialog({
				title: __("Datos registrados en VIES"),
				fields: [
					{
						fieldname: "name",
						label: __("Nombre"),
						fieldtype: "Data",
						read_only: 1,
						default: data.name,
					},
					{
						fieldname: "address",
						label: __("Dirección"),
						fieldtype: "Small Text",
						read_only: 1,
						default: data.address,
					},
					{
						fieldname: "request_identifier",
						label: __("Número de consulta"),
						fieldtype: "Data",
						read_only: 1,
						default: data.request_identifier,
					},
					{ fieldtype: "Section Break" },
					{
						fieldname: "update_name",
						label: __("Usar este nombre en el tercero"),
						fieldtype: "Check",
						default: data.name && data.name !== frm.doc[name_field] ? 1 : 0,
						hidden: data.name ? 0 : 1,
					},
					{
						fieldname: "create_address",
						label: __("Crear la dirección de facturación"),
						fieldtype: "Check",
						default: parsed ? 1 : 0,
						hidden: parsed ? 0 : 1,
					},
				],
				primary_action_label: __("Aplicar"),
				primary_action: (values) =>
					frappe
						.call({
							method: "erpnext_spain.es_nif.vies.apply_vies_details",
							type: "POST",
							freeze: true,
							args: {
								doctype: frm.doctype,
								name: frm.doc.name,
								update_name: values.update_name,
								create_address: values.create_address,
							},
						})
						.then(() => {
							dialog.hide();
							frm.reload_doc();
						}),
			});
			dialog.show();
		});
};

// El mismo fichero se carga con los dos formularios: eventos una sola vez.
if (!erpnext_spain.nif_party_events) {
	erpnext_spain.nif_party_events = true;
	["Customer", "Supplier"].forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh: (frm) => {
				erpnext_spain.es_nif.reset(frm);
				erpnext_spain.es_nif.vies_button(frm);
			},
			tax_id: (frm) => erpnext_spain.es_nif.reset(frm),
			[erpnext_spain.es_nif.NAME_FIELDS[doctype]]: (frm) =>
				erpnext_spain.es_nif.set_mark(frm, "unchecked"),
			[erpnext_spain.es_nif.TYPE_FIELDS[doctype]]: (frm) =>
				erpnext_spain.es_nif.toggle_name_hint(frm),
		});
	});
}
