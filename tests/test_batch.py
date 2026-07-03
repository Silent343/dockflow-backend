"""Tests del procesador en lote: clasificación de estados y aislamiento de fallos."""
import tempfile
from pathlib import Path

from app.application.extract_document import ExtractDocumentUseCase
from app.batch import process_file, process_folder


class _Reader:
    def is_text_pdf(self, d, f): return False
    def extract_text(self, d, f): return ""


_PAYLOADS = {
    b"ok": {"document_type": "factura", "number": "1", "issue_date": "01/01/2024",
            "issuer_ruc": "20131388552", "currency": "SOLES",
            "subtotal": 100, "igv": 18, "total": 118,
            "items": [{"description": "x", "quantity": 1, "unit_price": 100, "line_total": 100}]},
    b"revisar": {"document_type": "boleta", "number": "2",  # sin fecha -> warning
                 "issuer_ruc": "20131388552", "currency": "SOLES",
                 "subtotal": 100, "igv": 18, "total": 118},
    b"error": {"document_type": "factura", "number": "3", "issuer_ruc": "20131388552",
               "currency": "SOLES", "subtotal": 100, "igv": 18, "total": 999},  # no cuadra
}


class _Fake:
    def extract(self, *, text, image_bytes, mime_type):
        if image_bytes == b"fail":
            raise ValueError("boom")
        return _PAYLOADS[image_bytes]


def _uc():
    return ExtractDocumentUseCase(_Reader(), _Fake())


def _file(content: bytes) -> Path:
    d = Path(tempfile.mkdtemp())
    p = d / "doc.png"
    p.write_bytes(content)
    return p


def test_status_ok():
    assert process_file(_file(b"ok"), _uc()).status == "OK"


def test_status_revisar():
    row = process_file(_file(b"revisar"), _uc())
    assert row.status == "REVISAR" and row.n_warnings >= 1 and row.n_errors == 0


def test_status_error():
    row = process_file(_file(b"error"), _uc())
    assert row.status == "ERROR" and row.n_errors >= 1


def test_fallo_no_tumba_y_reporta_detalle():
    row = process_file(_file(b"fail"), _uc(), retries=0)
    assert row.status == "FALLO" and "boom" in row.error_detail


def test_process_folder_ordena_y_procesa_todo():
    d = Path(tempfile.mkdtemp())
    (d / "a.png").write_bytes(b"ok")
    (d / "b.png").write_bytes(b"error")
    (d / "ignorar.txt").write_bytes(b"no soportado")
    rows = process_folder(d, _uc(), workers=2)
    assert [r.filename for r in rows] == ["a.png", "b.png"]  # ordenado, sin el .txt
