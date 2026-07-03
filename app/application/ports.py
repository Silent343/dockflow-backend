"""Puertos (interfaces) de la capa de aplicación.

El dominio y los casos de uso dependen de estas abstracciones,
no de implementaciones concretas (Gemini, pdfplumber, openpyxl).
Esto es la inversión de dependencias de Clean Architecture.
"""
from __future__ import annotations

from typing import Protocol


class FileReader(Protocol):
    """Convierte un archivo crudo (PDF/imagen) en algo procesable por el extractor."""

    def is_text_pdf(self, data: bytes, filename: str) -> bool:
        """True si el PDF tiene texto nativo seleccionable (no escaneado)."""
        ...

    def extract_text(self, data: bytes, filename: str) -> str:
        """Texto plano del documento (si tiene capa de texto)."""
        ...


class DocumentExtractor(Protocol):
    """Extrae datos estructurados de un documento usando un modelo de IA."""

    def extract(self, *, text: str | None, image_bytes: bytes | None,
                mime_type: str | None) -> dict:
        """Devuelve un dict crudo con los campos del comprobante.

        Recibe texto (PDF nativo) o bytes de imagen (escaneado/foto).
        El mapeo a entidades del dominio ocurre en el use case.
        """
        ...
