# DocFlow — Extractor inteligente de comprobantes (backend)

Sube un PDF/imagen de **factura, boleta, recibo u orden de compra** y obtené
datos estructurados (JSON) validados según reglas SUNAT, con export directo a Excel.

MVP enfocado en LATAM/Perú: RUC con dígito verificador, IGV 18%, cuadre de
totales, y **revisión humana** antes de exportar (nunca automatización a ciegas).

## Stack

- **FastAPI** + Pydantic v2 — API
- **Google Gemini** (SDK `google-genai`) — comprensión del documento
- **pdfplumber** — texto nativo de PDFs (los escaneados/fotos van al modelo como imagen)
- **openpyxl** — export a Excel
- Arquitectura limpia (DDD): `domain` → `application` → `infrastructure` / `interfaces`

## Arranque

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # y poné tu GEMINI_API_KEY (https://aistudio.google.com/apikey)
export $(cat .env | xargs)  # o usá python-dotenv

uvicorn app.main:app --reload
```

Docs interactivas en `http://localhost:8000/docs`.

## Endpoints

| Método | Ruta             | Qué hace                                            |
|--------|------------------|-----------------------------------------------------|
| GET    | `/health`        | Estado del servicio                                 |
| POST   | `/extract`       | Sube archivo → JSON estructurado + hallazgos        |
| POST   | `/export/excel`  | Sube archivo → `.xlsx` (cabecera + items + validación) |

Ejemplo:

```bash
curl -F "file=@factura.pdf" http://localhost:8000/extract
curl -F "file=@factura.pdf" http://localhost:8000/export/excel -o salida.xlsx
```

## Estructura

```
app/
├── domain/            # núcleo: entidades, value objects (RUC), reglas (IGV, cuadre)
│   ├── entities.py
│   ├── value_objects.py
│   ├── validation.py  # motor de detección de errores (humano en el loop)
│   └── exceptions.py
├── application/       # casos de uso + puertos (interfaces)
│   ├── ports.py
│   └── extract_document.py
├── infrastructure/    # implementaciones: Gemini, pdfplumber, openpyxl
│   ├── gemini_extractor.py
│   ├── pdf_reader.py
│   └── excel_exporter.py
├── interfaces/        # DTOs de la API
│   └── schemas.py
└── main.py            # FastAPI + composición de dependencias
```

El dominio no conoce FastAPI ni Gemini: la inversión de dependencias va por
los `Protocol` de `application/ports.py`. Cambiar Gemini por otro modelo, o
Excel por Notion/Airtable, sólo toca `infrastructure/`.

## Procesamiento en lote (QA / regresión)

Para validar muchos comprobantes de una vez y detectar cuáles revisar:

```bash
python -m app.batch ./facturas                      # genera reporte_lote.xlsx
python -m app.batch ./facturas --out qa.xlsx --workers 3 --dump-json ./json
```

Procesa todos los `.pdf .png .jpg .jpeg .webp` de la carpeta y produce un Excel
con tres hojas:

- **Resumen**: una fila por archivo, coloreada por estado
  (`OK` verde · `REVISAR` amarillo · `ERROR` rojo · `FALLO` gris).
- **Validación**: todos los hallazgos del lote (archivo, campo, severidad, mensaje).
- **Totales**: conteos por estado y por tipo de documento.

Cada archivo se procesa aislado: un PDF corrupto o un error de la API marca esa
fila como `FALLO` sin abortar el resto. Hay reintentos con backoff ante límites
de tasa. Con el *free tier* de Gemini usá `--workers 1`. `--dump-json` guarda la
extracción cruda de cada archivo, útil para armar un set de regresión "golden".

## Tests

```bash
pytest -q
```

Cubren RUC (módulo 11), parseo de montos peruanos (`S/ 1,234.50`),
cuadre de totales e IGV, y tolerancia a campos faltantes.

## Siguiente iteración

- Frontend Angular 21: dashboard de revisión (editar campos marcados antes de exportar)
- Conectores: Notion, Airtable, Google Sheets, ERP
- Soporte XML de factura electrónica SUNAT (cruzar XML + PDF)
- Persistencia + multi-tenant para versión SaaS
