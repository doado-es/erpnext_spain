// Libro diario PGC (spec 04 §5).

frappe.query_reports["ES Journal Book"] = {
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
			fieldname: "fiscal_year",
			label: __("Ejercicio"),
			fieldtype: "Link",
			options: "Fiscal Year",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today()),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Desde"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Hasta"),
			fieldtype: "Date",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${value}</b>` : value;
	},
};
