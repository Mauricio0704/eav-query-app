# Encuesta NL — Query Builder

A deterministic survey data query tool for non-technical users.
Built with DuckDB (Python/FastAPI backend) + plain HTML/JS frontend.

## Stack

| Layer    | Technology        |
|----------|-------------------|
| Database | DuckDB            |
| Backend  | Python + FastAPI  |
| Frontend | HTML + JS (no framework) |

---

## Setup

### 1. Install Python dependencies

```bash
pip install fastapi uvicorn duckdb python-multipart
```

### 2. Point to your database

Set the `DB_PATH` environment variable to your `.duckdb` file:

```bash
export DB_PATH=/path/to/your/encuesta.duckdb
```

Or if you're loading from Excel/CSV, DuckDB can query those directly.
See the note at the bottom of this file.

### 3. Start the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive docs at `http://localhost:8000/docs`.

### 4. Open the frontend

Open `frontend/index.html` in your browser.
(Or serve it with any static server, e.g. `python3 -m http.server 3000` from the frontend folder.)

---

## API Endpoints

| Method | Path               | Description                          |
|--------|--------------------|--------------------------------------|
| GET    | /api/questions     | All questions + their answer options |
| GET    | /api/attributes    | All respondent filter attributes + labels |
| GET    | /api/cities        | All city IDs                         |
| POST   | /api/query         | Run a query, returns JSON            |
| POST   | /api/query/csv     | Same but returns CSV download        |
| GET    | /api/health        | Health check                         |

### POST /api/query — Request body

```json
{
  "question_id": "49",
  "filters": [
    { "attribute": "sexo", "value": 2 },
    { "attribute": "rango_ingreso", "value": 1 }
  ],
  "group_by": "answer"
}
```

- `group_by` can be `"answer"`, `"city_id"`, or any attribute name (e.g. `"sexo"`)
- `filters` is a list of `{attribute, value}` pairs where `value` is the integer from `respondent_attributes`

---

## Schema reference

```sql
answers              (respondent_id, question_id, option_id, value REAL)
options              (question_id, option_id, option_label)
questions            (q_id, q_text, q_section, q_type, q_notes)
respondent_attributes(respondent_id, question_id [=attribute], value [=option_id])
responses            (respondent_id, is_initial_respondent, nombre, factor_cvnl, city_id)
```

**How attribute labels resolve:**
`respondent_attributes.attribute` → `options.question_id`
`respondent_attributes.value`     → `options.option_id`
So the human-readable label for a filter value is fetched from the `options` table.

---

## Using Excel / CSV files instead of a .duckdb file

DuckDB can query Excel and CSV files directly. To use this, replace
the table references in `main.py` with file paths:

```python
# In get_conn(), after connecting:
conn.execute("CREATE VIEW IF NOT EXISTS answers AS SELECT * FROM read_csv_auto('/path/to/answers.csv')")
conn.execute("CREATE VIEW IF NOT EXISTS options AS SELECT * FROM read_csv_auto('/path/to/options.csv')")
# etc.
```

Or for Excel:
```python
conn.execute("INSTALL spatial; LOAD spatial;")
conn.execute("CREATE VIEW IF NOT EXISTS answers AS SELECT * FROM st_read('/path/to/data.xlsx')")
```

---

## Production deployment

1. Set `CORS` in `main.py` to your frontend's domain (not `"*"`)
2. Run uvicorn behind nginx or use `gunicorn -k uvicorn.workers.UvicornWorker`
3. Serve `frontend/` as static files from the same nginx config
4. Keep `DB_PATH` as an env var — never hardcode paths

---

## Extending the query builder

- **New filter types** (date range, multi-select): add them to `frontend/index.html`'s `addFilter()` function and update the `QueryRequest` model in `main.py`
- **New chart types**: extend `drawChart()` in the frontend
- **Authentication**: add FastAPI middleware or use a reverse proxy with basic auth for internal access