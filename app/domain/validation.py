"""Servicio de validación del dominio.

Recorre un Invoice y produce una lista de hallazgos (issues).
Cada issue tiene severidad: ERROR (bloquea export automático) o
WARNING (se exporta pero se marca para revisión humana).

Este es el núcleo del 'humano en el loop': nunca exportamos a ciegas.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .entities import Invoice
from .value_objects import DocumentType


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    field: str
    severity: Severity
    message: str


# Tolerancia por redondeo en céntimos.
_TOL = Decimal("0.10")


def validate_invoice(inv: Invoice) -> list[Issue]:
    issues: list[Issue] = []

    # 1. Identificación mínima
    if not inv.full_number:
        issues.append(Issue("number", Severity.ERROR, "Falta número de comprobante"))
    if inv.issue_date is None:
        issues.append(Issue("issue_date", Severity.WARNING, "No se detectó fecha de emisión"))

    # 2. Emisor: para factura el RUC del emisor es obligatorio
    if inv.document_type == DocumentType.FACTURA and inv.issuer_ruc is None:
        issues.append(Issue("issuer_ruc", Severity.ERROR, "Factura sin RUC de emisor válido"))

    # 3. Coherencia de items vs subtotal / total
    #    Las líneas pueden venir SIN IGV (suman al subtotal) o CON IGV
    #    (suman al total, típico en facturas de distribuidoras/retail).
    if inv.items:
        items_sum = inv.items_sum()
        sum_tol = max(_TOL, len(inv.items) * Decimal("0.02"))
        matches_subtotal = abs(items_sum - inv.subtotal) <= sum_tol
        matches_total = abs(items_sum - inv.total) <= sum_tol
        if not (matches_subtotal or matches_total):
            issues.append(Issue(
                "subtotal", Severity.WARNING,
                f"Suma de items ({items_sum}) no coincide con subtotal "
                f"({inv.subtotal}) ni con total ({inv.total})",
            ))
        for i, it in enumerate(inv.items):
            # Tolerancia proporcional: el precio unitario suele venir redondeado,
            # y ese redondeo se amplifica con la cantidad (1 céntimo por unidad).
            line_tol = max(Decimal("0.10"), it.quantity * Decimal("0.01"))
            if not it.total_matches(line_tol):
                issues.append(Issue(
                    f"items[{i}]", Severity.WARNING,
                    f"Línea '{it.description[:30]}': {it.quantity}x{it.unit_price} "
                    f"≠ {it.line_total}",
                ))

    # 4. Coherencia de IGV (18%)
    if inv.subtotal > 0:
        expected = inv.expected_igv()
        if abs(expected - inv.igv) > _TOL:
            issues.append(Issue(
                "igv", Severity.WARNING,
                f"IGV declarado ({inv.igv}) ≠ 18% del subtotal ({expected})",
            ))

    # 5. Coherencia del total
    expected_total = inv.expected_total()
    if abs(expected_total - inv.total) > _TOL:
        issues.append(Issue(
            "total", Severity.ERROR,
            f"Subtotal + IGV ({expected_total}) ≠ total declarado ({inv.total})",
        ))

    # 6. Moneda razonable
    if inv.currency not in ("PEN", "USD"):
        issues.append(Issue("currency", Severity.WARNING, f"Moneda inusual: {inv.currency}"))

    return issues


def has_blocking_errors(issues: list[Issue]) -> bool:
    return any(i.severity == Severity.ERROR for i in issues)
