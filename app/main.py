"""DocFlow API — extractor inteligente de comprobantes.

Endpoints:
  GET  /health          -> estado del servicio
  POST /extract         -> sube PDF/imagen, devuelve JSON estructurado + validación
  POST /export/excel    -> sube PDF/imagen, devuelve .xlsx listo para contabilidad

Composición de dependencias (manual, sin contenedor IoC) en get_use_case().
"""
from __future__ import annotations

import io
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .interfaces.schemas import ExtractionResponse, InvoiceInput
from .application.extract_document import ExtractDocumentUseCase, build_extraction_result
from .infrastructure.excel_exporter import export_to_excel
from .infrastructure.pdf_reader import PdfPlumberReader

load_dotenv()

my_secret_key = os.getenv("AQ.Ab8RN6JLaBQuuUwKXNQ6w47gaA-pt64lfzIzLugCCpNXpd0-lw")

app = FastAPI(title="DocFlow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # en prod restringir al dominio del frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

_ALLOWED = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def get_use_case() -> ExtractDocumentUseCase:
    # Import perezoso: Gemini sólo se inicializa si hay API key configurada.
    from .infrastructure.gemini_extractor import GeminiExtractor
    return ExtractDocumentUseCase(PdfPlumberReader(), GeminiExtractor())


async def _read_upload(file: UploadFile) -> bytes:
    if file.content_type not in _ALLOWED:
        raise HTTPException(415, f"Tipo no soportado: {file.content_type}")
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "Archivo demasiado grande (máx 10 MB)")
    if not data:
        raise HTTPException(400, "Archivo vacío")
    return data


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "docflow"}


@app.post("/extract", response_model=ExtractionResponse)
async def extract(file: UploadFile = File(...)) -> ExtractionResponse:
    data = await _read_upload(file)
    try:
        result = get_use_case().execute(
            data=data, filename=file.filename or "doc", mime_type=file.content_type
        )
    except (RuntimeError, ImportError) as e:   # falta API key o dependencia
        raise HTTPException(503, str(e))
    return ExtractionResponse.from_result(result)


@app.post("/export/excel")
async def export_excel(file: UploadFile = File(...)) -> StreamingResponse:
    data = await _read_upload(file)
    try:
        result = get_use_case().execute(
            data=data, filename=file.filename or "doc", mime_type=file.content_type
        )
    except (RuntimeError, ImportError) as e:
        raise HTTPException(503, str(e))

    xlsx = export_to_excel(result)
    name = (result.invoice.full_number or "comprobante").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


@app.post("/export/excel-from-data")
def export_excel_from_data(payload: InvoiceInput) -> StreamingResponse:
    """Exporta a Excel datos ya revisados/corregidos en el dashboard.

    El backend re-valida (autoridad final) antes de generar el archivo, así la
    hoja de validación refleja las correcciones del usuario.
    """
    result = build_extraction_result(payload.model_dump())
    xlsx = export_to_excel(result)
    name = (result.invoice.full_number or "comprobante").replace("/", "-")
    return StreamingResponse(
        io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )
