"""Caso de uso: extraer un documento y validarlo.

Orquesta: leer archivo -> extraer con IA -> mapear a dominio -> validar.
No conoce FastAPI ni Gemini; sólo habla con puertos y entidades.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..domain.entities import Invoice, InvoiceItem
from ..domain.exceptions import InvalidRucError
from ..domain.validation import Issue, validate_invoice
from ..domain.value_objects import DocumentType, Ruc, money, normalize_currency
from .ports import DocumentExtractor, FileReader


@dataclass
class ExtractionResult:
    invoice: Invoice
    issues: list[Issue]
    raw: dict          # lo que devolvió el modelo, para auditoría
    confidence: float  # heurística simple basada en issues


class ExtractDocumentUseCase:
    def __init__(self, file_reader: FileReader, extractor: DocumentExtractor) -> None:
        self._reader = file_reader
        self._extractor = extractor

    def execute(self, *, data: bytes, filename: str, mime_type: str) -> ExtractionResult:
        is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"

        text: str | None = None
        image_bytes: bytes | None = None

        if is_pdf and self._reader.is_text_pdf(data, filename):
            text = self._reader.extract_text(data, filename)
        else:
            # PDF escaneado o imagen -> al extractor como imagen/documento
            image_bytes = data

        raw = self._extractor.extract(text=text, image_bytes=image_bytes, mime_type=mime_type)
        return build_extraction_result(raw)


def build_extraction_result(raw: dict) -> ExtractionResult:
    """Mapea datos crudos (de Gemini o editados por el usuario) a dominio y valida.

    Reutilizable tanto por el pipeline de extracción como por el export de datos
    ya corregidos: el backend siempre re-valida y es la autoridad final.
    """
    invoice = map_raw_to_invoice(raw)
    issues = validate_invoice(invoice)
    return ExtractionResult(invoice=invoice, issues=issues, raw=raw,
                            confidence=estimate_confidence(issues))


def map_raw_to_invoice(raw: dict) -> Invoice:
    items = [
        InvoiceItem(
            description=str(it.get("description", "")).strip(),
            quantity=_dec(it.get("quantity"), default="1"),
            unit_price=_dec(it.get("unit_price")),
            line_total=_dec(it.get("line_total")),
        )
        for it in (raw.get("items") or [])
        if isinstance(it, dict)
    ]
    return Invoice(
        document_type=DocumentType.from_text(raw.get("document_type")),
        series=_clean(raw.get("series")),
        number=_clean(raw.get("number")),
        issue_date=_parse_date(raw.get("issue_date")),
        issuer_name=_clean(raw.get("issuer_name")),
        issuer_ruc=_safe_ruc(raw.get("issuer_ruc")),
        customer_name=_clean(raw.get("customer_name")),
        customer_doc=_clean(raw.get("customer_doc")),
        items=items,
        subtotal=money(_dec(raw.get("subtotal"))),
        igv=money(_dec(raw.get("igv"))),
        total=money(_dec(raw.get("total"))),
        currency=normalize_currency(_clean(raw.get("currency"))),
    )


def estimate_confidence(issues: list[Issue]) -> float:
    # Heurística simple: cada error -0.25, cada warning -0.08, piso 0.
    score = 1.0
    for i in issues:
        score -= 0.25 if i.severity.value == "error" else 0.08
    return round(max(score, 0.0), 2)


# --- helpers de parseo defensivo ---

def _clean(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _dec(v, default: str = "0") -> Decimal:
    if v is None or v == "":
        return Decimal(default)
    try:
        # tolera "1,234.56", "S/ 1234.56", "1234,56"
        s = str(v).replace("S/", "").replace("$", "").strip()
        if "," in s and "." in s:
            s = s.replace(",", "")          # 1,234.56 -> 1234.56
        elif "," in s:
            s = s.replace(",", ".")          # 1234,56 -> 1234.56
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _safe_ruc(v) -> Ruc | None:
    s = _clean(v)
    if not s:
        return None
    try:
        return Ruc(s)
    except InvalidRucError:
        return None  # se reporta como issue en validación, no rompe la extracción


def _parse_date(v) -> date | None:
    s = _clean(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
