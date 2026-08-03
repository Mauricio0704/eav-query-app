# Desarrollo

## Requisitos

- Python 3.12+ (el repo usa un venv en `.venv/`)
- Node 18+ (para el frontend)

## Setup

```bash
# Backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

## Correr localmente

```bash
# Backend (FastAPI) — API en :8000
cd backend
../.venv/bin/uvicorn main:app --port 8000 --reload

# Frontend (Vite dev server, proxea /api → :8000)
cd frontend
npm run dev        # http://localhost:3000
```

El modo IA es opcional:

```bash
export GEMINI_API_KEY=key   # sin esto, la app corre en modo manual
```

## Variables de entorno

| Variable         | Default                                | Uso                                        |
|------------------|----------------------------------------|--------------------------------------------|
| `DB_PATH`        | `../data/encuesta_multianual.duckdb`   | Ruta a la BD DuckDB                        |
| `STATIC_DIR`     | `../frontend/dist`                     | SPA compilada                              |
| `GEMINI_API_KEY` | — (sin default)                        | Habilita el modo IA                        |

> `DB_PATH` es relativo a `backend/`.

## Tests

```bash
.venv/bin/pytest          # 138 tests: motor de query + endpoints + chat + ratelimit
```

Suites en `tests/`:
- `test_run_query.py` — las 4 formas del motor + invariantes (base Capa A,
  centinelas, ponderación, colapso de ciudades, guard de inyección).
- `test_endpoints.py` — endpoints de la API.
- `test_chat_helpers.py` — helpers del modo IA.
- `test_ratelimit.py` — rate limiting.
- `test_published_figures.py` — cifras publicadas vs. la BD.

## Reconstruir la BD

Ver [pipeline-datos.md](pipeline-datos.md). Un solo comando: construye las olas,
aplica los overlays y arma la capa de conceptos en memoria (no genera CSVs).

```bash
.venv/bin/python db/build_db.py          # reconstruye data/encuesta_multianual.duckdb
```

Los conceptos (comparación entre años) se declaran a mano en
`db/concepts/concept_equivalences.csv` — editarlo y volver a correr `build_db.py`.
Ver [conceptos.md](conceptos.md).

## Deploy (Render.com)

`render.yaml` es un Blueprint: Render hace **auto-deploy** al hacer push a la
rama `main`. El servicio compila el frontend, instala deps de Python y arranca
uvicorn, sirviendo la BD DuckDB **commiteada** en `data/`.

Flujo típico:
1. Hacer cambios y correr tests localmente.
2. Si cambió la BD, reconstruirla y commitear el `.duckdb`.
3. `git push` a `main` → Render redeploya solo (o hacer redeploy manual al último commit).
4. `GEMINI_API_KEY` se configura en el dashboard de Render.

## Estructura del repo

```
eav-queries/
├── backend/
│   ├── main.py          # FastAPI, motor de consultas, builder SQL seguro
│   ├── chat.py          # Integración Gemini
│   ├── metadata.py      # Rollups geográficos, recodes, presets, órdenes
│   └── ratelimit.py     # Rate limiting del modo IA
├── frontend/
│   ├── src/             # SPA Vue 3 + Vite
│   └── dist/            # Build
├── db/
│   ├── schema.sql       # DDL multi-año
│   ├── build_db.py      # Construye la BD (olas + overlays + conceptos, sin CSVs intermedios)
│   ├── waves/{2021..2024}/  # CSVs por ola (del ETL)
│   ├── concepts/        # equivalencias entre olas (a mano) + bootstrap_pairs.py
│   └── overlays/        # correcciones al catálogo crudo (a mano)
├── data/
│   ├── source/<año>/                # materia prima del ETL (Cuestionario + EAV .xlsx)
│   ├── waves/<año>/                 # insumos por ola (CSV del ETL; 2025 = BD original intacta)
│   └── encuesta_multianual.duckdb   # BD multi-año que lee la app (build_db.py)
├── docs/                # Documentación
├── tests/               # Suite pytest
└── render.yaml          # Blueprint de deploy
```

Ver también: [arquitectura.md](arquitectura.md) ·
[pipeline-datos.md](pipeline-datos.md) · [conceptos.md](conceptos.md).
