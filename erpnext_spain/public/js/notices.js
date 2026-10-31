// Avisos de ERPNext Spain en el escritorio (SII y otros): el servidor emite el
// evento realtime «erpnext_spain_notice» a cada usuario (erpnext_spain/es_sii/notices.py)
// y aquí se muestra como aviso emergente.

$(document).on("app_ready", function () {
	frappe.realtime.on("erpnext_spain_notice", function (data) {
		if (!data) return;
		const escape = frappe.utils.escape_html;
		const message = data.message
			? `<b>${escape(data.title || "")}</b><br>${escape(data.message)}`
			: escape(data.title || "");
		frappe.show_alert({ message: message, indicator: data.indicator || "blue" }, 10);
	});
});
