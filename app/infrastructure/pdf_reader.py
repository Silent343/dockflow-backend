"""Lector de PDF basado en pdfplumber.

Decide si el PDF tiene texto nativo (se procesa como texto, más barato y
exacto) o si es escaneado/imagen (va al modelo como imagen para OCR).
"""
from __future__ import annotations

import io

import pdfplumber


class PdfPlumberReader:
    # Umbral mínimo de caracteres para considerar que el PDF tiene texto real.
    _MIN_CHARS = 40

    def is_text_pdf(self, data: bytes, filename: str) -> bool:
        if not filename.lower().endswith(".pdf"):
            return False
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                chars = 0
                for page in pdf.pages[:2]:  # basta mirar las primeras páginas
                    chars += len((page.extract_text() or ""))
                    if chars >= self._MIN_CHARS:
                        return True
            return False
        except Exception:
            return False

    def extract_text(self, data: bytes, filename: str) -> str:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
                # las tablas suelen tener los items; las añadimos como texto plano
                for table in page.extract_tables():
                    for row in table:
                        cells = [c or "" for c in row]
                        parts.append(" | ".join(cells))
        return "\n".join(p for p in parts if p.strip())
