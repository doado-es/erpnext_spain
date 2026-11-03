// Copyright (c) 2026, ct.galega and contributors
// For license information, please see license.txt

// El certificado se sube siempre como privado: sin el conmutador «público» ni
// enlaces web. El servidor lo exige igualmente (validate de la credencial y
// before_validate de File).
// En `refresh`: set_df_property trabaja sobre el docfield del documento, y el
// nombre cambia al guardar la credencial nueva.
frappe.ui.form.on("ES AEAT Credential", {
	refresh(frm) {
		frm.set_df_property("cert_file", "options", {
			make_attachments_public: 0,
			allow_toggle_private: false,
			allow_web_link: false,
		});
	},
});
