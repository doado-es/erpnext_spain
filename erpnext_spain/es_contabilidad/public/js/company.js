// ERPNext Spain · ES Contabilidad — acción «Aplicar plan PGC» en Company (spec 02 §2).
//
// La acción borra el plan de cuentas actual de la compañía: primero se pide el
// resumen (dry_run) y se muestra; solo con confirmación explícita se aplica.
// Las precondiciones y permisos los comprueba el servidor.

frappe.provide("erpnext_spain.es_contabilidad");

const APPLY_METHOD = "erpnext_spain.es_contabilidad.pgc.apply_pgc_chart";

erpnext_spain.es_contabilidad.summary_html = function (summary) {
	const rows = [
		[__("Plan"), summary.chart],
		[__("Cuentas actuales que se borran"), summary.accounts_to_delete],
		[__("Cuentas que se crean"), summary.accounts_to_create],
		[__("Inventario permanente"), __("Se desactiva (inventario administrativo)")],
	];
	for (const [doctype, count] of Object.entries(summary.records_to_delete || {})) {
		rows.push([__("{0} que se borran", [__(doctype)]), count]);
	}
	const table = rows
		.map(
			([label, value]) =>
				`<tr><td>${frappe.utils.escape_html(label)}</td><td><b>${frappe.utils.escape_html(
					String(value)
				)}</b></td></tr>`
		)
		.join("");
	return (
		`<table class="table table-bordered">${table}</table>` +
		`<p class="text-danger">${__(
			"Se borra el plan de cuentas actual de la compañía y sus plantillas de impuestos. Esta acción no se puede deshacer."
		)}</p>`
	);
};

erpnext_spain.es_contabilidad.apply_pgc_chart = function (frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Aplicar plan PGC"),
		fields: [
			{
				fieldname: "chart_model",
				label: __("Modelo de plan"),
				fieldtype: "Select",
				options: "PYMES\nNormal",
				default: frm.doc.es_annual_accounts_model === "Normal" ? "Normal" : "PYMES",
				reqd: 1,
			},
		],
		primary_action_label: __("Ver resumen"),
		primary_action(values) {
			frappe.call({
				method: APPLY_METHOD,
				type: "POST",
				args: { company: frm.doc.name, chart_model: values.chart_model, dry_run: 1 },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					dialog.hide();
					frappe.confirm(erpnext_spain.es_contabilidad.summary_html(r.message), () => {
						frappe.call({
							method: APPLY_METHOD,
							type: "POST",
							args: {
								company: frm.doc.name,
								chart_model: values.chart_model,
								dry_run: 0,
							},
							freeze: true,
							freeze_message: __("Creando el plan de cuentas…"),
							callback(res) {
								if (res.message && res.message.applied) {
									frappe.show_alert({
										message: __("Plan PGC aplicado"),
										indicator: "green",
									});
									frm.reload_doc();
								}
							},
						});
					});
				},
			});
		},
	});
	dialog.show();
};

erpnext_spain.es_contabilidad.create_missing_records = function (frm) {
	frappe.call({
		method: "erpnext_spain.es_impuestos.initial_data.create_missing_company_records",
		type: "POST",
		args: { company: frm.doc.name },
		freeze: true,
		callback(r) {
			if (!r.message) return;
			const total = Object.values(r.message).reduce(
				(sum, list) => sum + (list || []).length,
				0
			);
			frappe.show_alert({
				message: total
					? __("Creados {0} registros de impuestos", [total])
					: __("No faltaba ningún registro de impuestos"),
				indicator: "green",
			});
			frm.reload_doc();
		},
	});
};

erpnext_spain.es_contabilidad.closing_entry = function (frm, method, title, extra_fields) {
	const dialog = new frappe.ui.Dialog({
		title: title,
		fields: [
			{
				fieldname: "posting_date",
				label: __("Fecha de cierre"),
				fieldtype: "Date",
				default: frappe.datetime.year_end(),
				reqd: 1,
			},
			...(extra_fields || []),
		],
		primary_action_label: __("Crear asiento en borrador"),
		primary_action(values) {
			frappe.call({
				method: `erpnext_spain.es_contabilidad.closing.${method}`,
				type: "POST",
				args: { company: frm.doc.name, posting_date: values.posting_date, dry_run: 0 },
				freeze: true,
				callback(r) {
					if (!r.message || !r.message.journal_entry) return;
					dialog.hide();
					frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
				},
			});
		},
	});
	dialog.show();
};

frappe.ui.form.on("Company", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.country !== "Spain") return;
		if (!frappe.user.has_role(["Accounts Manager", "System Manager"])) return;
		if (!frm.doc.es_pgc_applied) {
			frm.add_custom_button(
				__("Aplicar plan PGC"),
				() => erpnext_spain.es_contabilidad.apply_pgc_chart(frm),
				__("Plan de cuentas")
			);
		} else {
			// Crea las plantillas, reglas y cuentas de impuestos que falten, sin
			// tocar las existentes (spec 09).
			frm.add_custom_button(
				__("Crear impuestos que faltan"),
				() => erpnext_spain.es_contabilidad.create_missing_records(frm),
				__("Plan de cuentas")
			);
			// Asientos de cierre PGC (spec 04 §6-§7): se crean en borrador para revisarlos.
			frm.add_custom_button(
				__("Regularizar existencias"),
				() =>
					erpnext_spain.es_contabilidad.closing_entry(
						frm,
						"regularise_inventory",
						__("Regularización de existencias")
					),
				__("Cierre PGC")
			);
			if (frm.doc.es_chart_model === "Normal") {
				frm.add_custom_button(
					__("Traspasar grupos 8 y 9"),
					() =>
						erpnext_spain.es_contabilidad.closing_entry(
							frm,
							"transfer_groups_8_9",
							__("Traspaso de los grupos 8 y 9")
						),
					__("Cierre PGC")
				);
			}
		}
	},
});
