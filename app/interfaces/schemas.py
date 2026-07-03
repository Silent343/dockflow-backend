"""DTOs de la API (Pydantic v2).

Convierten las entidades del dominio en JSON serializable para el frontend.
Separados del dominio para no acoplar la API a la estructura interna.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from ..application.extract_document import ExtractionResult


class ItemInput(BaseModel):
    description: str = ""
    quantity: float = 1
    unit_price: float = 0
    line_total: float = 0


class InvoiceInput(BaseModel):
    """Datos del comprobante enviados desde el dashboard (posiblemente editados)."""
    document_type: Optional[str] = None
    series: Optional[str] = None
    number: Optional[str] = None
    issue_date: Optional[str] = None
    issuer_name: Optional[str] = None
    issuer_ruc: Optional[str] = None
    customer_name: Optional[str] = None
    customer_doc: Optional[str] = None
    currency: Optional[str] = "PEN"
    subtotal: float = 0
    igv: float = 0
    total: float = 0
    items: list[ItemInput] = []


class ItemDTO(BaseModel):
    description: str
    quantity: float
    unit_price: float
    line_total: float


class IssueDTO(BaseModel):
    field: str
    severity: str
    message: str


class InvoiceDTO(BaseModel):
    document_type: str
    series: Optional[str] = None
    number: Optional[str] = None
    full_number: Optional[str] = None
    issue_date: Optional[str] = None
    issuer_name: Optional[str] = None
    issuer_ruc: Optional[str] = None
    customer_name: Optional[str] = None
    customer_doc: Optional[str] = None
    currency: str
    subtotal: float
    igv: float
    total: float
    items: list[ItemDTO]


class ExtractionResponse(BaseModel):
    invoice: InvoiceDTO
    issues: list[IssueDTO]
    confidence: float
    has_errors: bool

    @classmethod
    def from_result(cls, result: ExtractionResult) -> "ExtractionResponse":
        inv = result.invoice
        return cls(
            invoice=InvoiceDTO(
                document_type=inv.document_type.value,
                series=inv.series,
                number=inv.number,
                full_number=inv.full_number,
                issue_date=inv.issue_date.isoformat() if inv.issue_date else None,
                issuer_name=inv.issuer_name,
                issuer_ruc=str(inv.issuer_ruc) if inv.issuer_ruc else None,
                customer_name=inv.customer_name,
                customer_doc=inv.customer_doc,
                currency=inv.currency,
                subtotal=_f(inv.subtotal),
                igv=_f(inv.igv),
                total=_f(inv.total),
                items=[
                    ItemDTO(
                        description=it.description,
                        quantity=_f(it.quantity),
                        unit_price=_f(it.unit_price),
                        line_total=_f(it.line_total),
                    )
                    for it in inv.items
                ],
            ),
            issues=[
                IssueDTO(field=i.field, severity=i.severity.value, message=i.message)
                for i in result.issues
            ],
            confidence=result.confidence,
            has_errors=any(i.severity.value == "error" for i in result.issues),
        )


def _f(d: Decimal) -> float:
    return float(d)
