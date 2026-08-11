# Arquitectura

Herramienta de consultas sobre la encuesta *Así Vamos*, olas 2021–2025.

## Panorama

```
┌──────────────────────┐        /api/*         ┌───────────────────────────┐
│  SPA Vue 3 + Vite     │  ───────────────────► │  FastAPI (Python)         │
│  Tailwind · Chart.js  │  ◄─────────────────── │  • motor de consultas     │
│  modo manual + IA     │     JSON / CSV        │  • builder SQL seguro     │
└──────────────────────┘                       │  • IA por tool-use (chat) │
                                                └─────────────┬─────────────┘
                                                              │ solo lectura
                                                     ┌────────▼────────┐
                                                     │  DuckDB (EAV)    │
                                                     │  multi-año       │
                                                     └─────────────────┘
```

En producción FastAPI **también** sirve la SPA compilada como archivos 
estáticos, así que todo es un solo servicio.

| Capa           | Tecnología                                          |
|----------------|-----------------------------------------------------|
| Base de datos  | DuckDB (embebida, solo lectura)                     |
| Backend        | Python · FastAPI · Pydantic · Uvicorn               |
| IA             | Google Gemini                                       |
| Frontend       | Vue 3 · Vite · Tailwind CSS v4                      |
| Gráficas       | Chart.js                                            |
| Tests          | pytest — 138 tests                                  |
| Deploy         | Render.com (`render.yaml`)                          |

## Esquema de datos (EAV multi-año)

Cada tabla de datos lleva `wave_id` (año de la ola) como parte de la PK, así que
varias olas coexisten sin colisionar. Ver `db/schema.sql`.

```sql
waves                 (wave_id PK, year, label, n_respondents, notes)
answers               (wave_id, respondent_id, question_id, option_id, value)
options               (wave_id, question_id, option_id) PK, option_label, concept_option_id
questions             (wave_id, q_id) PK, q_text, q_section, q_type, q_notes, q_info, q_block, concept_id
respondent_attributes (wave_id, respondent_id, attribute) PK, question_id, value
responses             (wave_id, respondent_id) PK, is_initial_respondent, nombre, factor_cvnl, city_id
concepts              (concept_id PK, label, q_type)
concept_options       (concept_id, concept_option_id PK, label, sort_order)
```

Cada par `(respondiente, pregunta)` es un renglón en `answers`.
Una respuesta guarda **exactamente uno** de:
- `option_id` (código de la opción, para preguntas **categóricas**; `value` NULL), o
- `value` (número, para preguntas **numéricas**; `option_id` NULL).

La etiqueta legible de un `option_id` vive en `options`. Los filtros
demográficos viven en `respondent_attributes`, donde `attribute` es un nombre
amigable (`sexo`) keyeado a un `question_id` de la encuesta, y `value` es el
`option_id` cuya etiqueta está en `options`.

### Por qué `answers` no tiene PK ni FK

Las dos ausencias son deliberadas y parecen errores si no se documentan — no las
"arregles" sin leer esto:

- **Sin PRIMARY KEY.** `option_id` es NULL en las preguntas numéricas, así que no
  puede formar parte de una PK. Además un índice ART sobre 1.1M+ renglones no
  ayuda a los scans/agregados que hace el motor (DuckDB es columnar y poda por
  zone-maps) y engorda el archivo. La unicidad de
  `(wave_id, respondent_id, question_id)` se valida en `build_db.py`, no en el
  esquema.
- **Sin FOREIGN KEY.** Existen ~76 referencias `(question_id, option_id)` sin
  fila correspondiente en `options`; el backend ya las maneja con `LEFT JOIN`.
  Una FK las rechazaría y el build fallaría.

`answers` además se ordena **físicamente** al cargar (ver `build_db.py`) para que
DuckDB pode por zone-maps al filtrar por pregunta.


## Motor de consultas (`backend/main.py`)

Todo pasa por `run_query()` (`POST /api/query`). Según `group_by` y el tipo de
pregunta hay **cuatro formas** más la comparación entre años:

| `group_by`        | Categórica                          | Numérica                                   |
|-------------------|-------------------------------------|--------------------------------------------|
| `"answer"` (plana)| 1 renglón por opción: conteo + %    | distribución de frecuencias por valor + %  |
| ≠ `"answer"` (pivote) | 2 tablas (conteos + %) con Total | igual + fila **Promedio** (media ponderada)|
| `"year"`          | pivote entre olas, alineado por opción canónica | media ponderada por año         |

Helpers compartidos que arman el SQL y las tablas:

- **`_base_from_where(...)`** — bloque `FROM/JOIN/WHERE` común (answers ⋈
  responses de la misma ola + JOINs de filtros + WHERE de ola/pregunta/cohorte).
  Slots: `extra_where` (centinelas / no-nulos) y `with_options` (LEFT JOIN al
  catálogo de opciones).
- **`_group_expr_sql(group_by, wave)`** — expresión SQL de la etiqueta de columna
  del pivote (city_id / rangos de edad / recode / atributo).
- **`_city_buckets(city_filter)`** — buckets de columna al agrupar por ciudad.
- **`_collapse_city_cells(...)`** — colapsa city_ids crudos en los buckets de
  metadata (11 municipios AMM + 4 agregados).
- **`_pivot_count_pct_rows(...)`** — ensambla filas de conteos y porcentajes +
  fila Total (idéntico para numérica y categórica).

`_year_comparison()` maneja `group_by="year"`: resuelve el concepto de la
pregunta y reutiliza el camino plano en cada ola, alineando opciones por
`concept_option_id` (ver [conceptos.md](conceptos.md)).

## Decisiones de diseño

- **DuckDB embebida y de solo lectura.** Los datos son referencia fija, no
  transaccional. Columnar → escaneos agregados rápidos sobre 1.1M filas. Se
  versiona como **un archivo** commiteado; cada conexión abre `read_only=True`.
- **SQL generado con validación por allowlist, no ORM.** Las consultas se
  componen dinámicamente. Cada identificador del usuario (`question_id`,
  `group_by`, cada `attribute` de filtro) se valida contra una allowlist
  derivada de la BD **antes** de construir cualquier string SQL; los valores son
  enteros coaccionados por Pydantic. SQL dinámico con superficie de
  inyección **cero**, y el SQL generado se devuelve al cliente (transparencia).
- **Proyección a población (`factor_cvnl`).** Con `initial_only=true` (default)
  se restringe a respondientes iniciales y se pondera por el factor de expansión
  de cada uno → estimaciones poblacionales. Con `false` se cuentan filas crudas.
- **Centinelas.** Los códigos `7777`/`8888`/`9999` (No aplica / No sabe / No
  contesta) son respuestas reales: se conservan en conteos y porcentajes, pero se
  **excluyen** de estadísticos numéricos (promedios). Además, la "regla de techo"
  detecta centinelas no estándar por pregunta numérica (ver
  `_extra_numeric_sentinels`): un código sospechoso (p. ej. 99, 999) sólo cuenta
  como centinela si **excede** el valor real máximo de esa pregunta.
- **Modo IA por tool-use, no text-to-SQL.** El modelo no emite SQL: se le dan las
  **mismas** funciones de consulta que usa la UI y solo puede actuar
  invocándolas, así toda respuesta de IA corre por el mismo camino validado y
  ponderado. Superficie de inyección cero. Es opcional: sin `GEMINI_API_KEY` la
  app corre en modo manual.
- **Caché.** Los endpoints de metadata (`/api/questions`, `/api/attributes`,
  `/api/cities`) son inmutables durante la vida del proceso y se cachean con
  `lru_cache`.

## Endpoints

| Método | Ruta               | Descripción                             |
|--------|--------------------|-----------------------------------------|
| GET    | `/api/questions`   | Preguntas + opciones (por ola)          |
| GET    | `/api/attributes`  | Atributos de filtro + etiquetas         |
| GET    | `/api/cities`      | Municipios distintos                    |
| GET    | `/api/waves`       | Olas disponibles (marca la default)     |
| GET    | `/api/recodes`     | Definiciones de recode                  |
| GET    | `/api/presets`     | Recetas de análisis (group_by+filtros)  |
| POST   | `/api/query`       | Corre una consulta → JSON               |
| POST   | `/api/query/csv`   | Corre una consulta → descarga CSV       |
| POST   | `/api/chat`        | Consulta en lenguaje natural (modo IA)  |
| GET    | `/api/health`      | Health check                            |

Ver también: [pipeline-datos.md](pipeline-datos.md) ·
[conceptos.md](conceptos.md) · [desarrollo.md](desarrollo.md).
