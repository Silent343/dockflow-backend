"""Procesador en lote de comprobantes — CLI.

Lee una carpeta de PDFs/imágenes, los pasa por el pipeline de extracción +
validación y genera un reporte consolidado en Excel. Pensado como herramienta
de QA / regresión: ver de un vistazo qué facturas cuadran y cuáles revisar.

Uso:
    python -m app.batch ./facturas
    python -m app.batch ./facturas --out reporte.xlsx --workers 3 --dump-json ./salida_json

Cada archivo se procesa de forma aislada: un PDF corrupto o un fallo de la API
no aborta el lote, sólo marca esa fila como FALLO.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .application.extract_document import ExtractDocumentUseCase, ExtractionResult
from .domain.validation import has_blocking_errors
from .infrastructure.batch_report import build_summary_report
from .infrastructure.pdf_reader import PdfPlumberReader

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_MIME = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp",
}


@dataclass
class BatchRow:
    filename: str
    status: str                       # OK | REVISAR | ERROR | FALLO
    document_type: str = ""
    full_number: str = ""
    issuer_name: str = ""
    issuer_ruc: str = ""
    customer_doc: str = ""
    currency: str = ""
    subtotal: float = 0.0
    igv: float = 0.0
    total: float = 0.0
    confidence: float = 0.0
    n_errors: int = 0
    n_warnings: int = 0
    error_detail: str = ""
    issues: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def _status_from(result: ExtractionResult) -> str:
    if has_blocking_errors(result.issues):
        return "ERROR"
    if result.issues:
        return "REVISAR"
    return "OK"


def _row_from(filename: str, result: ExtractionResult) -> BatchRow:
    invoice = result.invoice
    issues = [
        {"field": i.field, "severity": i.severity.value, "message": i.message}
        for i in result.issues
    ]
    return BatchRow(
        filename=filename,
        status=_status_from(result),
        document_type=invoice.document_type.value,
        full_number=invoice.full_number or "",
        issuer_name=invoice.issuer_name or "",
        issuer_ruc=str(invoice.issuer_ruc) if invoice.issuer_ruc else "",
        customer_doc=invoice.customer_doc or "",
        currency=invoice.currency,
        subtotal=float(invoice.subtotal),
        igv=float(invoice.igv),
        total=float(invoice.total),
        confidence=result.confidence,
        n_errors=sum(1 for i in result.issues if i.severity.value == "error"),
        n_warnings=sum(1 for i in result.issues if i.severity.value == "warning"),
        issues=issues,
        raw=result.raw,
    )


def process_file(path: Path, use_case: ExtractDocumentUseCase, *, retries: int = 2) -> BatchRow:
    data = path.read_bytes()
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    last_err = ""
    for attempt in range(retries + 1):
        try:
            result = use_case.execute(data=data, filename=path.name, mime_type=mime)
            return _row_from(path.name, result)
        except Exception as e:  # noqa: BLE001 - un fallo no debe tumbar el lote
            last_err = f"{type(e).__name__}: {e}"
            msg = str(e).lower()
            transient = any(k in msg for k in ("429", "quota", "exhausted", "rate", "timeout", "503"))
            if attempt < retries and transient:
                time.sleep(2 ** attempt * 1.5)  # backoff: 1.5s, 3s
                continue
            break
    return BatchRow(filename=path.name, status="FALLO", error_detail=last_err)


def process_folder(folder: Path, use_case: ExtractDocumentUseCase, *, workers: int = 3) -> list[BatchRow]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED)
    if not files:
        return []
    rows: list[BatchRow] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(process_file, p, use_case): p for p in files}
        for fut in concurrent.futures.as_completed(futures):
            row = fut.result()
            rows.append(row)
            mark = {"OK": "✓", "REVISAR": "!", "ERROR": "✗", "FALLO": "✗"}.get(row.status, "?")
            print(f"  [{mark}] {row.filename:<40} {row.status:<8} conf={row.confidence}")
    # ordenar por nombre para reporte estable
    rows.sort(key=lambda r: r.filename)
    return rows


def _build_use_case() -> ExtractDocumentUseCase:
    from .infrastructure.gemini_extractor import GeminiExtractor
    return ExtractDocumentUseCase(PdfPlumberReader(), GeminiExtractor())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Procesador en lote de comprobantes (DocFlow)")
    parser.add_argument("folder", type=Path, help="Carpeta con PDFs/imágenes")
    parser.add_argument("--out", type=Path, default=Path("reporte_lote.xlsx"),
                        help="Ruta del reporte Excel de salida")
    parser.add_argument("--workers", type=int, default=3,
                        help="Hilos concurrentes (usar 1 con free tier de Gemini)")
    parser.add_argument("--dump-json", type=Path, default=None,
                        help="Carpeta donde guardar el JSON crudo de cada extracción")
    args = parser.parse_args(argv)

    if not args.folder.is_dir():
        print(f"No es una carpeta: {args.folder}", file=sys.stderr)
        return 2

    try:
        use_case = _build_use_case()
    except RuntimeError as e:
        print(f"No se pudo iniciar el extractor: {e}", file=sys.stderr)
        return 3

    print(f"Procesando {args.folder} ...")
    rows = process_folder(args.folder, use_case, workers=args.workers)
    if not rows:
        print("No se encontraron archivos soportados (.pdf .png .jpg .jpeg .webp)")
        return 1

    if args.dump_json:
        args.dump_json.mkdir(parents=True, exist_ok=True)
        for row in rows:
            (args.dump_json / f"{Path(row.filename).stem}.json").write_text(
                json.dumps(row.raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    report = build_summary_report(rows)
    args.out.write_bytes(report)

    ok = sum(1 for r in rows if r.status == "OK")
    rev = sum(1 for r in rows if r.status == "REVISAR")
    err = sum(1 for r in rows if r.status in ("ERROR", "FALLO"))
    print(f"\nResumen: {ok} OK | {rev} a revisar | {err} con problemas")
    print(f"Reporte: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
