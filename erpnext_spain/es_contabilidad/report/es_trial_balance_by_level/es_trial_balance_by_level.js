// Sumas y saldos PGC por niveles (spec 04 §4).

frappe.query_reports["ES Trial Balance by Level"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Compañía"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Desde"),
			fieldtype: "Date",
			default: frappe.datetime.year_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Hasta"),
			fieldtype: "Date",
			default: frappe.datetime.year_end(),
			reqd: 1,
		},
		{
			fieldname: "level",
			label: __("Nivel"),
			fieldtype: "Select",
			options: "1\n2\n3\n4\nCuenta",
			default: "3",
		},
		{
			fieldname: "include_closing",
			label: __("Incluir asiento de cierre"),
			fieldtype: "Check",
		},
		{
			fieldname: "finance_book",
			label: __("Libro de finanzas"),
			fieldtype: "Link",
			options: "Finance Book",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${value}</b>` : value;
	},
};
