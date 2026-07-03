"""Entidades del dominio.

Invoice es el aggregate root. Contiene la lógica de coherencia
del comprobante (totales, IGV) independiente de cómo se extrajo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .value_objects import DocumentType, Ruc, money


# IGV vigente en Perú. Configurable a futuro por si cambia la tasa.
IGV_RATE = Decimal("0.18")


@dataclass
class InvoiceItem:
    """Línea de detalle del comprobante."""

    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal

    @property
    def computed_total(self) -> Decimal:
        return money(self.quantity * self.unit_price)

    def total_matches(self, tolerance: Decimal = Decimal("0.05")) -> bool:
        """El total de línea cuadra con cantidad x precio (con tolerancia por redondeo)."""
        return abs(self.line_total - self.computed_total) <= tolerance


@dataclass
class Invoice:
    """Comprobante de pago (aggregate root)."""

    document_type: DocumentType
    series: Optional[str]
    number: Optional[str]
    issue_date: Optional[date]

    issuer_name: Optional[str]
    issuer_ruc: Optional[Ruc]
    customer_name: Optional[str]
    customer_doc: Optional[str]  # RUC o DNI del cliente (boletas usan DNI)

    items: list[InvoiceItem] = field(default_factory=list)

    subtotal: Decimal = Decimal("0.00")
    igv: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    currency: str = "PEN"

    # --- reglas de negocio / coherencia ---

    @property
    def full_number(self) -> Optional[str]:
        if self.series and self.number:
            return f"{self.series}-{self.number}"
        return self.number

    def expected_igv(self) -> Decimal:
        return money(self.subtotal * IGV_RATE)

    def expected_total(self) -> Decimal:
        return money(self.subtotal + self.igv)

    def items_sum(self) -> Decimal:
        return money(sum((it.line_total for it in self.items), Decimal("0")))
