# Child table «ES Verifactu Notification Role» (spec 04 §2.1): roles con
# notificación in-app de incidencias. La consume la capa AEAT
# (aeat/utils.notify_roles → _notification_roles): cuando la empresa tiene
# filas aquí, las incidencias van a esos roles; sin configuración, el fallback
# documentado es System Managers.

from __future__ import annotations

from frappe.model.document import Document


class ESVerifactuNotificationRole(Document):
	pass
