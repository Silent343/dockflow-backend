"""Tests del dominio y caso de uso (sin tocar Gemini).

Usa un extractor falso (fake) que devuelve dicts controlados.
Patrón AAA: Arrange, Act, Assert.
"""
from decimal import Decimal

import pytest

from app.application.extract_document import ExtractDocumentUseCase
from app.domain.exceptions import InvalidRucError
from app.domain.value_objects import DocumentType, Ruc, money


# --- Value Object: RUC ---

def test_ruc_valido_persona_juridica():
    # RUC de ejemplo con dígito verificador correcto
    ruc = Ruc("20131388552")
    assert ruc.is_company
    assert str(ruc) == "20131388552"


@pytest.mark.parametrize("bad", ["123", "abcdefghijk", "99131388552", "20131388553"])
def test_ruc_invalido_lanza(bad):
    with pytest.raises(InvalidRucError):
        Ruc(bad)


def test_lineas_con_igv_y_redondeo_no_genera_falsos_positivos():
    # Factura real de distribuidora: el importe de cada línea incluye IGV
    # (suma = total, no subtotal) y el precio unitario viene redondeado.
    res = _run({
        "document_type": "factura", "series": "FQQ2", "number": "000330",
        "issuer_ruc": "20434903891",
        "subtotal": "16,949.15", "igv": "3,050.85", "total": "20,000.00",
        "items": [
            {"description": "GLORIA EVAP", "quantity": 2400, "unit_price": 3.2, "line_total": 7680},
            {"description": "FILETE ATUN", "quantity": 480, "unit_price": 5.067, "line_total": 2432},
            {"description": "RESTO", "quantity": 1, "unit_price": 9888, "line_total": 9888},
        ],
    })
    # IGV y total cuadran; la suma de líneas coincide con el total -> sin warnings de monto
    monto_warnings = [i for i in res.issues if i.field in ("subtotal", "items[0]", "items[1]")]
    assert not monto_warnings, [str(i) for i in monto_warnings]


def test_ruc_persona_natural_dv_cero():
    # RUC real de factura SUNAT (prefijo 10, dígito verificador 0).
    # Regresión: el caso resultado==10 -> DV 0 estaba invertido.
    ruc = Ruc("10033822800")
    assert not ruc.is_company
    assert str(ruc) == "10033822800"


def test_moneda_soles_se_normaliza_a_pen():
    from app.domain.value_objects import normalize_currency
    assert normalize_currency("SOLES") == "PEN"
    assert normalize_currency("S/") == "PEN"
    assert normalize_currency("DÓLARES") == "USD"
    assert normalize_currency(None) == "PEN"


def test_document_type_desde_texto():
    assert DocumentType.from_text("FACTURA ELECTRÓNICA") == DocumentType.FACTURA
    assert DocumentType.from_text("Nota de Crédito") == DocumentType.NOTA_CREDITO
    assert DocumentType.from_text(None) == DocumentType.OTRO


def test_money_redondea():
    assert money("1234.567") == Decimal("1234.57")
    assert money(None) == Decimal("0.00")


# --- Fakes para el caso de uso ---

class FakeReader:
    def is_text_pdf(self, data, filename):
        return True

    def extract_text(self, data, filename):
        return "texto de prueba"


class FakeExtractor:
    def __init__(self, payload):
        self.payload = payload

    def extract(self, *, text, image_bytes, mime_type):
        return self.payload


def _run(payload):
    uc = ExtractDocumentUseCase(FakeReader(), FakeExtractor(payload))
    return uc.execute(data=b"x", filename="f.pdf", mime_type="application/pdf")


# --- Caso de uso: extracción + validación ---

def test_factura_coherente_sin_errores():
    res = _run({
        "document_type": "factura",
        "series": "F001", "number": "00001234",
        "issue_date": "2025-03-15",
        "issuer_name": "ACME SAC", "issuer_ruc": "20131388552",
        "subtotal": 100, "igv": 18, "total": 118,
        "items": [{"description": "Servicio", "quantity": 1, "unit_price": 100, "line_total": 100}],
    })
    assert res.invoice.full_number == "F001-00001234"
    assert not any(i.severity.value == "error" for i in res.issues)
    assert res.confidence >= 0.9


def test_total_incoherente_genera_error():
    res = _run({
        "document_type": "factura",
        "series": "F001", "number": "1",
        "issuer_ruc": "20131388552",
        "subtotal": 100, "igv": 18, "total": 999,  # no cuadra
    })
    errs = [i for i in res.issues if i.severity.value == "error"]
    assert any(i.field == "total" for i in errs)


def test_ruc_malo_no_rompe_pero_se_reporta():
    res = _run({
        "document_type": "factura",
        "number": "1",
        "issuer_ruc": "00000000000",  # inválido
        "subtotal": 0, "igv": 0, "total": 0,
    })
    # no explota; el RUC queda en None y aparece issue de emisor
    assert res.invoice.issuer_ruc is None
    assert any(i.field == "issuer_ruc" for i in res.issues)


def test_parseo_montos_con_formato_peruano():
    res = _run({
        "document_type": "boleta", "number": "B001-1",
        "subtotal": "S/ 1,234.50", "igv": "222.21", "total": "1,456.71",
    })
    assert res.invoice.subtotal == Decimal("1234.50")
    assert res.invoice.total == Decimal("1456.71")
