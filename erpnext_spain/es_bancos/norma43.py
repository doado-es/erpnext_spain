# Lector de ficheros Norma 43 (cuaderno 43 de AEB/CECA/UNACC, junio de 2012)
# (spec 13 §2). Registros de 80 posiciones: 11 cabecera de cuenta, 22
# movimiento, 23 conceptos complementarios, 24 equivalencia de divisa, 33 final
# de cuenta y 88 fin de fichero.

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

END_TO_END = re.compile(r"\b([A-Z0-9][A-Z0-9\-]{5,34})\b")


class Norma43Error(ValueError):
	pass


@dataclass
class Movement:
	office: str
	operation_date: date
	value_date: date
	common_concept: str
	own_concept: str
	amount: Decimal  # con signo: positivo = abono (haber), negativo = cargo (debe)
	document: str
	reference_1: str
	reference_2: str
	concepts: list[str] = field(default_factory=list)
	position: int = 0

	@property
	def description(self) -> str:
		parts = [self.own_concept.strip(), *[c.strip() for c in self.concepts]]
		return " ".join(part for part in parts if part)

	@property
	def reference(self) -> str:
		"""Referencias 1 y 2 seguidas: una referencia larga (p. ej. un EndToEndId)
		ocupa las dos sin separación."""
		return " ".join((self.reference_1 + self.reference_2).split())


@dataclass
class AccountBlock:
	bank: str
	office: str
	account: str
	start: date
	end: date
	opening: Decimal
	currency: str
	name: str
	movements: list[Movement] = field(default_factory=list)
	closing: Decimal | None = None
	errors: list[str] = field(default_factory=list)

	@property
	def key(self) -> str:
		return f"{self.bank}{self.office}{self.account}"


def parse_date(value: str) -> date:
	return date(2000 + int(value[0:2]), int(value[2:4]), int(value[4:6]))


def parse_amount(value: str) -> Decimal:
	return Decimal(int(value)) / 100


def signed(key: str, value: str, debit_key: str = "1") -> Decimal:
	amount = parse_amount(value)
	return -amount if key == debit_key else amount


def parse(content: bytes | str) -> list[AccountBlock]:
	text = content.decode("latin-1") if isinstance(content, bytes) else content
	lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]
	blocks: list[AccountBlock] = []
	current: AccountBlock | None = None
	positions: dict[date, int] = {}
	records = 0
	for number, line in enumerate(lines, 1):
		line = line.ljust(80)
		code = line[0:2]
		if code == "88":
			if int(line[20:26] or 0) not in (records, records + 1):
				raise Norma43Error(
					f"El registro 88 indica {int(line[20:26])} registros y el fichero tiene {records}."
				)
			break
		records += 1
		if code == "11":
			current = AccountBlock(
				bank=line[2:6],
				office=line[6:10],
				account=line[10:20],
				start=parse_date(line[20:26]),
				end=parse_date(line[26:32]),
				opening=signed(line[32], line[33:47]),
				currency=line[47:50],
				name=line[51:77].strip(),
			)
			blocks.append(current)
			positions = {}
		elif code == "22":
			if current is None:
				raise Norma43Error(f"Línea {number}: movimiento sin cabecera de cuenta (registro 11).")
			operation = parse_date(line[10:16])
			positions[operation] = positions.get(operation, 0) + 1
			current.movements.append(
				Movement(
					office=line[6:10],
					operation_date=operation,
					value_date=parse_date(line[16:22]),
					common_concept=line[22:24],
					own_concept=line[24:27],
					amount=signed(line[27], line[28:42]),
					document=line[42:52].strip(),
					reference_1=line[52:64],
					reference_2=line[64:80],
					position=positions[operation],
				)
			)
		elif code == "23":
			if current and current.movements:
				current.movements[-1].concepts += [line[4:42], line[42:80]]
		elif code == "33":
			if current is None:
				raise Norma43Error(f"Línea {number}: final de cuenta sin cabecera.")
			check_totals(current, line)
			current = None
		elif code != "24":
			raise Norma43Error(f"Línea {number}: tipo de registro desconocido «{code}».")
	return blocks


def check_totals(block: AccountBlock, line: str) -> None:
	debit_count, debit_total = int(line[20:25]), parse_amount(line[25:39])
	credit_count, credit_total = int(line[39:44]), parse_amount(line[44:58])
	block.closing = signed(line[58], line[59:73])
	debits = [m.amount for m in block.movements if m.amount < 0]
	credits = [m.amount for m in block.movements if m.amount > 0]
	if len(debits) != debit_count or -sum(debits) != debit_total:
		block.errors.append(
			f"cargos: {len(debits)} por {-sum(debits)} y el registro 33 indica {debit_count} por {debit_total}"
		)
	if len(credits) != credit_count or sum(credits) != credit_total:
		block.errors.append(
			f"abonos: {len(credits)} por {sum(credits)} y el registro 33 indica {credit_count} por {credit_total}"
		)
	if block.opening + sum(m.amount for m in block.movements) != block.closing:
		block.errors.append(
			f"saldo inicial {block.opening} + movimientos {sum(m.amount for m in block.movements)} ≠ saldo final {block.closing}"
		)


def transaction_id(block: AccountBlock, movement: Movement) -> str:
	"""Identificador estable para no duplicar movimientos al reimportar."""
	key = "|".join(
		str(part)
		for part in (
			block.key,
			movement.operation_date,
			movement.value_date,
			movement.amount,
			movement.document,
			movement.reference_1.strip(),
			movement.reference_2.strip(),
			movement.position,
		)
	)
	return "N43-" + hashlib.sha1(key.encode()).hexdigest()[:24]
