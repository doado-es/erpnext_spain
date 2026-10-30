# Validación de NIF/CIF/NIE españoles (spec 14).
#
# Módulo deliberadamente puro: sin imports de frappe, importable y testeable
# sin site (doc 12 §2, §20). Toda la aritmética de control se delega en
# python-stdnum (decisión de dependencia, spec 14) — nunca algoritmo casero
# de letra/dígito de control.
#
# Tipos reconocidos:
# - DNI: 8 dígitos + letra de control (mod 23).
# - NIE: X/Y/Z + 7 dígitos + letra (X→0, Y→1, Z→2 y mod 23).
# - CIF: letra de organización + 7 dígitos + control (Luhn; si el control es
#   letra, se toma de "JABCDEFGHI" — no la tabla mod 23 del DNI).
# - NIFs personales históricos K/L/M: algoritmo del DNI sobre los 7 dígitos
#   (los acepta el dispatcher de stdnum; se clasifican como "dni").

from __future__ import annotations

import re
from dataclasses import dataclass

from stdnum.es import vat as stdnum_vat  # dispatcher ES: alias de stdnum.es.nif
from stdnum.es import cif as stdnum_cif
from stdnum.es import dni as stdnum_dni
from stdnum.es import nie as stdnum_nie
from stdnum.exceptions import InvalidChecksum, ValidationError

compact = stdnum_vat.compact


ORG_LETTERS = "ABCDEFGHJNPQRSUVW"
ORG_LETTERS_HUMAN = "A, B, C, D, E, F, G, H, J, N, P, Q, R, S, U, V y W"
CIF_LETTER_CONTROL_TABLE = "JABCDEFGHI"

FORMAT = "format"
CONTROL_LETTER = "control_letter"
CONTROL_DIGIT = "control_digit"
ORG_LETTER = "org_letter"

DNI_PATTERN = re.compile(r"^[0-9]{8}[A-Z]$")
NIE_PATTERN = re.compile(r"^[XYZ][0-9]{7}[A-Z]$")
NIF_PERSONAL_KLM_PATTERN = re.compile(r"^[KLM][0-9]{7}[A-Z]$")
CIF_PATTERN = re.compile(r"^[A-Z][0-9]{7}[A-Z0-9]$")


@dataclass(frozen=True)
class ValidatedTaxID:
	kind: str  # "dni" | "nie" | "cif"
	number: str


class InvalidTaxID(ValueError):
	def __init__(self, error_type: str, message: str, suggestion: str | None = None):
		self.error_type = error_type
		self.suggestion = suggestion
		super().__init__(message)


def validate_spanish_tax_id(tax_id: str) -> ValidatedTaxID:
	"""Valida un NIF español y devuelve el tipo detectado y el número normalizado.

	:Lanza InvalidTaxID: con mensajes en español que incluyen el remedio
	(p. ej. la letra de control correcta).
	"""
	number = compact(tax_id) if tax_id else ""
	if not number:
		raise _format_error(tax_id)

	kind = _detect_type(number)

	try:
		if kind == "dni":
			_validate_dni(number)
		elif kind == "nie":
			stdnum_nie.validate(number)
		else:
			stdnum_cif.validate(number)
	except ValidationError as exc:
		raise _error_from_stdnum(number, kind, exc) from exc

	return ValidatedTaxID(kind=kind, number=number)


def looks_spanish(tax_id: str) -> bool:
	"""Detecta por patrón si el valor parece un NIF español.

	Se usa para decidir si aplicar la validación española (spec 14 §2). La
	detección es deliberadamente amplia en la letra inicial (cualquier
	letra + 7 dígitos + control): un patrón reconocible con letra de
	organización inválida debe entrar en validación para poder reportar el
	defecto con precisión, no saltarse silenciosamente.
	"""
	if not tax_id:
		return False
	number = compact(tax_id)
	return bool(
		DNI_PATTERN.match(number)
		or NIE_PATTERN.match(number)
		or NIF_PERSONAL_KLM_PATTERN.match(number)
		or CIF_PATTERN.match(number)
	)


def _detect_type(number: str) -> str:
	if DNI_PATTERN.match(number) or NIF_PERSONAL_KLM_PATTERN.match(number):
		return "dni"
	if NIE_PATTERN.match(number):
		return "nie"
	if CIF_PATTERN.match(number):
		return "cif"
	raise _format_error(number)


def _validate_dni(number: str) -> None:
	if NIF_PERSONAL_KLM_PATTERN.match(number):
		if stdnum_dni.calc_check_digit(number[1:-1]) != number[-1]:
			raise InvalidChecksum()
	else:
		stdnum_dni.validate(number)


def _error_from_stdnum(number: str, kind: str, exc: ValidationError) -> InvalidTaxID:
	if isinstance(exc, InvalidChecksum):
		return _control_error(number, kind)
	if kind == "cif" and number[0] not in ORG_LETTERS:
		return InvalidTaxID(
			ORG_LETTER,
			f"La letra de organización «{number[0]}» no es válida en un NIF de entidad."
			f" Las letras válidas son: {ORG_LETTERS_HUMAN}."
			" Revise el primer carácter del NIF (confusiones típicas: O por A o por 0, I por 1).",
		)
	return _format_error(number)


def _control_error(number: str, kind: str) -> InvalidTaxID:
	if kind == "cif":
		digit, letter = stdnum_cif.calc_check_digits(number[:-1])
		if number[-1].isdigit():
			return InvalidTaxID(
				CONTROL_DIGIT,
				f"El dígito de control del CIF {number} no coincide:"
				f" ¿quisiste decir `{digit}`? (la letra `{letter}` también es válida como control).",
				suggestion=digit,
			)
		return InvalidTaxID(
			CONTROL_LETTER,
			f"La letra de control del CIF {number} no coincide:"
			f" ¿quisiste decir `{letter}`? (el dígito `{digit}` también es válido como control).",
			suggestion=letter,
		)

	if kind == "nie":
		correct_letter = stdnum_nie.calc_check_digit(number[:-1])
	else:
		base = number[1:-1] if NIF_PERSONAL_KLM_PATTERN.match(number) else number[:-1]
		correct_letter = stdnum_dni.calc_check_digit(base)

	name = "NIE" if kind == "nie" else "NIF"
	return InvalidTaxID(
		CONTROL_LETTER,
		f"La letra de control del {name} {number} no coincide: ¿quisiste decir `{correct_letter}`?",
		suggestion=correct_letter,
	)


def _format_error(value: str) -> InvalidTaxID:
	return InvalidTaxID(
		FORMAT,
		f"«{value or ''}» no tiene formato de NIF español. Debe ser un DNI (8 dígitos y letra),"
		" un NIE (X, Y o Z + 7 dígitos y letra) o un CIF (letra de organización + 7 dígitos"
		" y dígito o letra de control). Corrija el valor o vacíe el campo si el tercero"
		" no tiene NIF español.",
	)
