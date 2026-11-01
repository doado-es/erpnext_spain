// Pantalla «Plan General Contable» del asistente de configuración (hook
// setup_wizard_requires). El modelo elegido llega al servidor en
// args.es_chart_model y lo aplica la etapa de es_contabilidad/onboarding.py
// después de que ERPNext cree la compañía. ERPNext registra sus pantallas antes
// (orden de las apps), así que esta queda después de la de la compañía.

frappe.provide("erpnext_spain.setup");

frappe.setup.on("before_load", function () {
	if ((frappe.boot.setup_wizard_completed_apps || []).includes("erpnext_spain")) {
		return;
	}
	frappe.setup.add_slide(erpnext_spain.setup.pgc_slide);
});

erpnext_spain.setup.pgc_slide = {
	name: "es_pgc",
	title: __("Plan General Contable"),
	help: __(
		"ERPNext Spain sustituye el plan de cuentas elegido en el paso anterior por el Plan General Contable, con sus cuentas por defecto, impuestos y retenciones."
	),
	fields: [
		// País elegido en la primera pantalla; decide qué se muestra.
		{ fieldname: "es_wizard_country", fieldtype: "Data", hidden: 1 },
		{
			fieldname: "es_chart_model",
			label: __("Modelo del plan"),
			fieldtype: "Select",
			options: "PYMES\nNormal",
			default: "PYMES",
			depends_on: "eval:doc.es_wizard_country === 'Spain'",
			description: __(
				"PYMES sirve para la mayoría de las empresas. Elija Normal si la empresa supera los límites del PGC de PYMES o forma parte de un grupo que lo exige. Después no se puede cambiar."
			),
		},
		{
			fieldname: "es_not_spain",
			fieldtype: "HTML",
			depends_on: "eval:doc.es_wizard_country !== 'Spain'",
			options: `<p class="text-muted">${__(
				"El país elegido no es España: la compañía conserva el plan de cuentas de ERPNext."
			)}</p>`,
		},
	],

	before_show: function () {
		// set_value ya refresca los depends_on.
		this.form.set_value("es_wizard_country", frappe.wizard.values.country || "");
	},
};
