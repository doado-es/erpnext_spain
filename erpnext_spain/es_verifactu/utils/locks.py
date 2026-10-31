# Cerrojo de la cadena VeriFactu por compañía (spec 04 §12).
#
# Serializa, entre workers web y de background, la sección crítica de la
# emisión: asignación del número fiscal + renombre (lote 4b) y, desde el
# 4c, la creación del registro del libro con su encadenamiento SHA-256.
#
# Primitiva: filelock (FileLock fuerte, a nivel de SO, multi-proceso) — la
# misma librería que frappe.utils.synchronization.filelock. No se usa el
# file_lock «débil» de frappe (documentado como propenso a carreras).
#
# Se expone como context manager Y como API manual acquire/release: el lote
# 4c sostendrá el cerrojo desde before_submit hasta DESPUÉS de on_submit
# (creación del registro bajo el mismo cerrojo), y un context manager
# dentro de un solo hook no alcanza para eso.
#
# Clave lógica (spec 04 §12): verifactu:chain:{company}. El nombre de
# archivo sanitiza «:» (portabilidad del path, la clave semántica no
# cambia).

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import frappe
from filelock import FileLock, Timeout

from erpnext_spain.aeat.utils import absolute_site_path

PREFIX = "verifactu:chain:"

# Ventana de adquisición corta (spec 04 §12): la sección crítica es una
# lectura+incremento de contador y un rename — del orden de milisegundos.
DEFAULT_TIMEOUT = 15


def _lock_path(company: str) -> Path:
	"""Ruta del archivo de cerrojo DENTRO del site (locks/).

	ABSOLUTA vía absolute_site_path (ancla get_bench_path): los workers
	corren con CWDs mixtos y una ruta relativa haría que cada CWD usara un
	archivo DISTINTO — el cerrojo dejaría de excluir entre procesos."""
	file_name = f"{PREFIX}{company}".replace(":", "-").replace("/", "-")
	path = Path(absolute_site_path("locks", file_name))
	path.parent.mkdir(parents=True, exist_ok=True)
	return path


def acquire_chain_lock(company: str, timeout: float = DEFAULT_TIMEOUT) -> FileLock:
	"""Adquiere el cerrojo de cadena de la compañía (API manual: el llamador
	DEBE liberarlo con release_chain_lock; el 4c lo usa a través de
	before_submit/on_submit)."""
	lock = FileLock(str(_lock_path(company)), timeout=timeout)
	try:
		lock.acquire()
	except Timeout:
		frappe.throw(
			f"No se pudo adquirir el cerrojo de la cadena VeriFactu de"
			f" {company} en {timeout}s: hay otra emisión de la misma empresa en"
			" curso y la asignación de números fiscales debe ser estrictamente"
			" secuencial. Remedio: reintente en unos instantes; si"
			" el aviso persiste, revise jobs de emisión estancados en el"
			" monitor de background jobs.",
			frappe.ValidationError,
		)
	return lock


def release_chain_lock(lock: FileLock) -> None:
	"""Libera un cerrojo adquirido con acquire_chain_lock (idempotente)."""
	try:
		lock.release()
	except Exception:
		pass


@contextmanager
def chain_lock(company: str, timeout: float = DEFAULT_TIMEOUT):
	"""Context manager de conveniencia sobre acquire/release (before_submit
	del lote 4b)."""
	lock = acquire_chain_lock(company, timeout=timeout)
	try:
		yield lock
	finally:
		release_chain_lock(lock)
