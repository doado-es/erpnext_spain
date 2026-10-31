// Retenciones practicadas (spec 08 §6).

frappe.query_reports["ES Withholdings Made"] = {
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
		},
		{
			fieldname: "to_date",
			label: __("Hasta"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "tax_model",
			label: __("Modelo"),
			fieldtype: "Select",
			options: "\n111\n115",
		},
		{
			fieldname: "category",
			label: __("Categoría"),
			fieldtype: "Link",
			options: "Tax Withholding Category",
		},
		{
			fieldname: "party",
			label: __("Proveedor"),
			fieldtype: "Link",
			options: "Supplier",
		},
	],
};
