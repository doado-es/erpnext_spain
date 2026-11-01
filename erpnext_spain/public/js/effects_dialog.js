// Diálogo «Añadir efectos» de las remesas (adeudos SEPA, confirming).
//
// Filtros (tercero, condiciones de pago, vencimiento e importe), «Buscar» trae
// los efectos pendientes del servidor marcados por defecto, el total de los
// marcados se recalcula al marcar o desmarcar y «Añadir» los pasa a la tabla
// de la remesa sin repetir los que ya están.
//
// Uso (desde el formulario de la remesa, tras frappe.require de este fichero):
//   erpnext_spain.effects_dialog.open(frm, {
//     method, party: { fieldname, doctype, label }, args: (frm) => ({...}),
//     columns: [{ fieldname, label, fieldtype, options }], key: (row) => "...",
//     to_line: (row) => ({...}),   // o on_add: (rows) => promesa, para tratarlos en el servidor
//   });

frappe.provide("erpnext_spain.effects_dialog");

erpnext_spain.effects_dialog.open = function (frm, options) {
	const multiselect = (fieldname, label, doctype) => ({
		fieldname,
		label,
		fieldtype: "MultiSelectList",
		options: doctype,
		get_data: (txt) => frappe.db.get_link_options(doctype, txt),
	});
	const today = frappe.datetime.get_today();
	// Valores iniciales: la primera búsqueda sale antes de que el diálogo los aplique.
	const defaults = {
		from_due_date: frm.doc.from_due_date || "",
		to_due_date: frm.doc.to_due_date || frappe.datetime.add_months(today, 1),
	};
	const dialog = new frappe.ui.Dialog({
		title: options.title || __("Añadir efectos"),
		size: "extra-large",
		fields: [
			multiselect(options.party.fieldname, options.party.label, options.party.doctype),
			{ fieldtype: "Column Break" },
			multiselect(
				"payment_terms_templates",
				__("Condiciones de pago"),
				"Payment Terms Template"
			),
			{ fieldtype: "Section Break" },
			{
				fieldname: "from_due_date",
				label: __("Vencimiento desde"),
				fieldtype: "Date",
				default: defaults.from_due_date,
			},
			{
				fieldname: "to_due_date",
				label: __("Vencimiento hasta"),
				fieldtype: "Date",
				default: defaults.to_due_date,
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "min_amount", label: __("Importe mínimo"), fieldtype: "Currency" },
			{ fieldname: "max_amount", label: __("Importe máximo"), fieldtype: "Currency" },
			{ fieldtype: "Section Break" },
			{
				fieldname: "effects",
				label: __("Efectos pendientes"),
				fieldtype: "Table",
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: false,
				data: [],
				fields: options.columns.map((column) =>
					Object.assign({ in_list_view: 1, read_only: 1 }, column)
				),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "selected_count",
				label: __("Efectos marcados"),
				fieldtype: "Int",
				read_only: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "selected_total",
				label: __("Total marcado"),
				fieldtype: "Currency",
				read_only: 1,
			},
		],
		secondary_action_label: __("Buscar"),
		secondary_action: () => search(),
		primary_action_label: __("Añadir"),
		primary_action: () => add(),
	});

	const grid = () => dialog.fields_dict.effects.grid;
	const selected = () => grid().get_selected_children();

	const update_totals = () => {
		const rows = selected();
		dialog.set_value("selected_count", rows.length);
		dialog.set_value(
			"selected_total",
			rows.reduce((total, row) => total + flt(row.amount), 0)
		);
	};

	const search = (initial = false) => {
		const values = Object.assign({}, initial ? defaults : {}, dialog.get_values(true) || {});
		frappe
			.call({
				method: options.method,
				args: Object.assign(
					{
						[options.party.fieldname]: values[options.party.fieldname] || [],
						payment_terms_templates: values.payment_terms_templates || [],
						from_due_date: values.from_due_date || null,
						to_due_date: values.to_due_date || null,
						min_amount: values.min_amount || null,
						max_amount: values.max_amount || null,
						batch: frm.is_new() ? null : frm.doc.name,
					},
					options.args(frm)
				),
				freeze: true,
			})
			.then((r) => {
				const in_batch = new Set((frm.doc.lines || []).map(options.key));
				const rows = (r.message || []).filter((row) => !in_batch.has(options.key(row)));
				const field = dialog.fields_dict.effects;
				field.df.data = rows.map((row) => Object.assign({ __checked: 1 }, row));
				field.grid.refresh();
				update_totals();
				if (!rows.length) {
					frappe.show_alert({
						message: __("No hay efectos con esos filtros."),
						indicator: "orange",
					});
				}
			});
	};

	const add = () => {
		const rows = selected();
		if (!rows.length) {
			frappe.msgprint(__("Marque al menos un efecto."));
			return;
		}
		// La orden de pago crea sus pagos en el servidor.
		if (options.on_add) {
			Promise.resolve(options.on_add(rows)).then(() => dialog.hide());
			return;
		}
		// Fuera la fila vacía que trae la remesa nueva.
		const first_field = options.columns[0].fieldname;
		frm.doc.lines = (frm.doc.lines || []).filter((line) => line[first_field]);
		const in_batch = new Set(frm.doc.lines.map(options.key));
		let added = 0;
		for (const row of rows) {
			if (in_batch.has(options.key(row))) continue;
			frm.add_child("lines", options.to_line(row));
			in_batch.add(options.key(row));
			added += 1;
		}
		frm.refresh_field("lines");
		frm.set_value(
			"total_amount",
			(frm.doc.lines || []).reduce((sum, line) => sum + flt(line.amount), 0)
		);
		frm.dirty();
		dialog.hide();
		frappe.show_alert({ message: __("Efectos añadidos: {0}", [added]), indicator: "green" });
	};

	// Casillas de fila y la de «marcar todo»: el total cuando ya ha cambiado.
	grid().wrapper.on("change", ".grid-row-check", () => setTimeout(update_totals, 0));
	dialog.show();
	search(true);
};
