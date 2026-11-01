// Mapa de cuentas de impuestos: cuenta, nombre oficial del impuesto y plantillas que la usan.

frappe.query_reports["ES Tax Accounts"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Compañía"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "issue" && data && data.issue) {
			return `<span class="text-danger">${value}</span>`;
		}
		return value;
	},
};
