"""Extractor de documentos basado en Google Gemini (SDK unificado google-genai).

Usa salida JSON forzada (response_mime_type) y un prompt afinado para
comprobantes peruanos. Soporta texto (PDF nativo) e imagen (escaneado/foto).
"""
from __future__ import annotations

import json
import os

from google import genai
from google.genai import types


_SCHEMA_HINT = """
Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma (sin texto adicional,
sin markdown). Usa null cuando un dato no aparezca. No inventes valores.

{
  "document_type": "factura | boleta | nota_credito | nota_debito | recibo | orden_compra | otro",
  "series": "string o null",          // ej. F001
  "number": "string o null",          // ej. 00001234
  "issue_date": "YYYY-MM-DD o null",
  "issuer_name": "razon social del emisor o null",
  "issuer_ruc": "11 digitos o null",
  "customer_name": "nombre del cliente o null",
  "customer_doc": "RUC(11) o DNI(8) del cliente o null",
  "currency": "PEN | USD",
  "subtotal": numero (sin simbolo de moneda),
  "igv": numero,
  "total": numero,
  "items": [
    {
      "description": "string",
      "quantity": numero,
      "unit_price": numero,
      "line_total": numero
    }
  ]
}
""".strip()

_INSTRUCTIONS = (
    "Eres un extractor de comprobantes de pago peruanos (SUNAT). "
    "Extrae los datos del documento con precision. El IGV en Peru es 18%. "
    "Los montos van como numeros sin el simbolo 'S/' ni separadores de miles. "
    "Si el documento es una boleta, el cliente suele identificarse con DNI (8 digitos). "
    "Si es factura, con RUC (11 digitos). "
    "Para cada linea, 'line_total' es la columna de IMPORTE/TOTAL de esa fila. "
    "Si hay varias columnas de precio unitario (por ejemplo 'V/U' valor sin IGV y "
    "'P/U' precio con IGV), usa como 'unit_price' la que multiplicada por la cantidad "
    "reproduce el IMPORTE de la linea."
)


class GeminiExtractor:
    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Falta GEMINI_API_KEY en el entorno")
        self._client = genai.Client(api_key=key)
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def extract(self, *, text: str | None, image_bytes: bytes | None,
                mime_type: str | None) -> dict:
        contents: list = [_SCHEMA_HINT]

        if text:
            contents.append("TEXTO DEL DOCUMENTO:\n" + text[:30000])
        elif image_bytes:
            contents.append("Analiza la siguiente imagen del comprobante:")
            contents.append(
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/jpeg")
            )
        else:
            raise ValueError("Se requiere texto o imagen para extraer")

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_INSTRUCTIONS,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        return self._parse(response.text)

    @staticmethod
    def _parse(raw_text: str) -> dict:
        s = (raw_text or "").strip()
        if s.startswith("```"):                       # defensa por si envuelve en fences
            s = s.strip("`")
            s = s[4:] if s.lower().startswith("json") else s
        try:
            data = json.loads(s)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
