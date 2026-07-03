"""Value Objects del dominio.

Inmutables, sin identidad propia, validados en construcción.
Encapsulan reglas tributarias peruanas (SUNAT).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from .exceptions import InvalidRucError


@dataclass(frozen=True)
class Ruc:
    """RUC peruano: 11 dígitos con dígito verificador (módulo 11).

    Reglas:
      - 11 dígitos numéricos.
      - Los dos primeros identifican el tipo de contribuyente
        (10 = persona natural con negocio, 20 = persona jurídica,
        15/17 = otros). Validamos prefijos conocidos.
      - El último dígito es verificador y se calcula con pesos fijos.
    """

    value: str

    _WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    _VALID_PREFIXES = ("10", "15", "16", "17", "20")

    def __post_init__(self) -> None:
        v = self.value.strip()
        if not v.isdigit() or len(v) != 11:
            raise InvalidRucError(f"RUC debe tener 11 dígitos numéricos: {self.value!r}")
        if v[:2] not in self._VALID_PREFIXES:
            raise InvalidRucError(f"Prefijo de RUC no válido: {v[:2]}")
        if not self._check_digit_ok(v):
            raise InvalidRucError(f"Dígito verificador de RUC inválido: {v}")
        object.__setattr__(self, "value", v)

    @classmethod
    def _check_digit_ok(cls, v: str) -> bool:
        total = sum(int(d) * w for d, w in zip(v[:10], cls._WEIGHTS))
        residuo = total % 11
        resultado = 11 - residuo
        # Regla SUNAT: resultado 10 -> DV 0 ; resultado 11 -> DV 1
        check = 0 if resultado == 10 else (1 if resultado == 11 else resultado)
        return check == int(v[10])

    @property
    def is_company(self) -> bool:
        return self.value.startswith("20")

    def __str__(self) -> str:
        return self.value


class DocumentType(str, Enum):
    """Tipos de comprobante según catálogo SUNAT (catálogo 01)."""

    FACTURA = "factura"
    BOLETA = "boleta"
    NOTA_CREDITO = "nota_credito"
    NOTA_DEBITO = "nota_debito"
    RECIBO = "recibo"
    ORDEN_COMPRA = "orden_compra"
    OTRO = "otro"

    @classmethod
    def from_text(cls, text: str | None) -> "DocumentType":
        if not text:
            return cls.OTRO
        t = text.lower()
        if "crédito" in t or "credito" in t:
            return cls.NOTA_CREDITO
        if "débito" in t or "debito" in t:
            return cls.NOTA_DEBITO
        if "factura" in t:
            return cls.FACTURA
        if "boleta" in t:
            return cls.BOLETA
        if "recibo" in t:
            return cls.RECIBO
        if "orden" in t:
            return cls.ORDEN_COMPRA
        return cls.OTRO


def money(value) -> Decimal:
    """Normaliza un monto a Decimal con 2 decimales (redondeo bancario peruano)."""
    if value is None:
        return Decimal("0.00")
    d = Decimal(str(value))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_currency(raw: str | None) -> str:
    """Mapea las muchas formas de escribir la moneda a código ISO.

    Las facturas peruanas suelen poner 'SOLES' / 'S/' en vez de 'PEN'.
    """
    if not raw:
        return "PEN"
    t = raw.strip().upper().replace(".", "")
    if t in ("PEN", "SOL", "SOLES", "S/", "NUEVOS SOLES", "SOLES PERUANOS"):
        return "PEN"
    if t in ("USD", "US$", "$", "DOLARES", "DÓLARES", "DOLLARS", "US DOLLAR"):
        return "USD"
    return t[:3]
