# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A query tool over the *Así Vamos* / Consejo Nuevo León multi-year survey (waves
2021–2025, ~15,400 respondents, 1.1M answers, 309 questions). DuckDB (embedded,
read-only) + FastAPI backend + Vue 3 SPA. Lets non-technical users build
cross-tabs, weight to the population, and export CSV without writing SQL; an
optional Gemini-backed chat mode answers in natural language via the same
validated query path (tool use, not text-to-SQL).

**`docs/` has the deep technical documentation (Spanish), and is the
authoritative source — don't duplicate it here, read it when touching that
area:**
- [`docs/arquitectura.md`](docs/arquitectura.md) — query engine internals, the four query shapes, design decisions.
- [`docs/pipeline-datos.md`](docs/pipeline-datos.md) — how `build_db.py` assembles the DB, overlay files.
- [`docs/conceptos.md`](docs/conceptos.md) — cross-year question/option matching algorithm.
- [`docs/desarrollo.md`](docs/desarrollo.md) — env vars, deploy flow.

## Commands

```bash
# Setup (first time)
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install

# Run backend — API on :8000, docs at /docs
cd backend && ../.venv/bin/uvicorn main:app --port 8000 --reload

# Run frontend — :3000, proxies /api → :8000
cd frontend && npm run dev

# AI chat mode is opt-in (omit to run manual-only)
export GEMINI_API_KEY=your_key_here

# Tests (repo root; conftest.py adds backend/ to sys.path)
.venv/bin/pytest                                   # full suite
.venv/bin/pytest tests/test_run_query.py::test_pivot_by_attribute   # single test
.venv/bin/pytest -k sentinel                        # by keyword
.venv/bin/pytest -m published                       # published-figures acceptance tests only

# Frontend format (no separate lint script; Prettier is the only formatter)
cd frontend && npm run format          # write
cd frontend && npm run format:check    # CI-style check
cd frontend && npm run build           # → frontend/dist, served by FastAPI in prod

# Rebuild the DuckDB file — one command, does everything: loads all waves,
# applies the overlays, and builds the concepts layer in memory (no generated CSVs).
# Required after changing schema.sql, build_db.py, wave CSVs, an overlay, or
# concept_equivalences.csv.
.venv/bin/python db/build_db.py

# Draft cross-year question pairings when adding a new wave (manual tool, NOT
# part of the build — writes a draft for review, nothing is loaded until you
# move the rows into concept_equivalences.csv by hand)
.venv/bin/python db/concepts/bootstrap_pairs.py --new 2026
```

`data/encuesta_multianual.duckdb` is a **committed binary** that the app reads
directly — there is no live migration path. Any change to `db/schema.sql`,
`db/build_db.py`, wave CSVs, or the concepts CSVs requires rebuilding it and
committing the result; Render deploys straight from that file.

## Architecture

```
Vue 3 SPA (Vite, Tailwind v4, Chart.js)  ──/api/*──►  FastAPI (main.py)
  manual mode + chat mode                 ◄─JSON/CSV─  query engine, safe SQL builder
                                                        Gemini tool-use (chat.py)
                                                              │ read-only
                                                        DuckDB file (EAV, multi-year)
```

In production FastAPI also serves the built SPA (`STATIC_DIR`), so it's one
deployable service (`render.yaml`, Render.com, auto-deploy on push to `main`).

### Data model (EAV, multi-year)

Every data table carries `wave_id` as part of its PK so waves coexist without
colliding; question numbering is **not** stable across years (a question's
`q_id` can change between waves — that's what the concepts layer solves).

```sql
answers               (wave_id, respondent_id, question_id, option_id, value)  -- no PK, ordered physically
options               (wave_id, question_id, option_id) PK, option_label, concept_option_id
questions             (wave_id, q_id) PK, q_text, q_section, q_type, concept_id
respondent_attributes (wave_id, respondent_id, attribute) PK, question_id, value
responses             (wave_id, respondent_id) PK, is_initial_respondent, factor_cvnl, city_id
concepts / concept_options   -- cross-year harmonization catalog, see docs/conceptos.md
```

A row in `answers` holds *either* `option_id` (categorical) *or* `value`
(numeric), never both. `respondent_attributes` is the demographic-filter side
table: `attribute` is a friendly name (`sexo`) keyed to a `question_id`,
`value` is an `option_id` resolved through `options`. Wave 2025 loads from
`data/waves/2025/encuesta.duckdb` (the original single-year DB, kept read-only and never
mutated); waves 2021–2024 load from `data/waves/<year>/*.csv` produced by a
sibling ETL repo (`encuesta-asi-vamos-etl`).

`data/` is organized by pipeline stage, both levels keyed by year:
`source/<year>/` holds the raw material the **external ETL** consumes
(`Cuestionario <year>.xlsx` = the instrument, `EAV <year>.xlsx` = the raw export);
`waves/<year>/` holds what **`build_db.py`** consumes; `encuesta_multianual.duckdb`
is the output. This repo never runs that ETL — the one exception is
`db/overlays/build_option_fixes.py`, which reads the questionnaire to recover
missing option labels. `source/2019/` exists with no matching wave (raw material
kept, wave not loaded); `source/2025/` doesn't exist (that wave came from the
original DB, not the ETL).

### Query engine (`backend/main.py`)

Everything routes through `run_query()`. `group_by` selects one of four output
shapes (flat / pivot × categorical / numeric) plus a fifth, `group_by="year"`,
which only works for questions with a populated `concept_id` and is handled
separately by `_year_comparison()`. Shared helpers worth knowing before
touching this file: `_base_from_where` (common FROM/JOIN/WHERE), `_group_expr_sql`
(pivot column expression), `_collapse_city_cells` (raw `city_id` → AMM
municipality buckets from `metadata.py`), `_pivot_count_pct_rows` (assembles
counts + percentages + Total, shared by numeric and categorical paths).

Every user-supplied identifier (`question_id`, `group_by`, filter
`attribute`s) is validated against an allowlist derived from the DB itself
before any SQL string is built — this is a hand-rolled safe-SQL-builder
pattern, not an ORM, and it's why there's no parametrization gap to watch for
when extending query params. `initial_only` (default true) restricts to
initial respondents and weights by `factor_cvnl` for population estimates.
Sentinels `7777`/`8888`/`9999` (N/A · Don't know · No answer) stay in
counts/percentages but are excluded from numeric aggregates. Metadata
endpoints (`list_questions`, `list_attributes`, `list_cities`, etc.) are
`lru_cache`d per-wave — they're safe to cache because the DB file never
mutates at runtime.

### Cross-year concepts (`db/concepts/`)

**Everything is hand-declared in two versioned CSVs; there is no matcher and no
generated intermediate files.** `build_db.py::load_concepts` builds the whole
layer in memory at build time.

- `concept_equivalences.csv` — one row per **pair** of equivalent questions in two
  waves (`wave_a,q_a,wave_b,q_b,ctype,decision,concept_id,source,note`). Pairs
  chain transitively, so a multi-wave concept is built from pairwise rows and
  adding a wave is **adding rows, never touching code**. `decision=exclude`
  documents pairs that must *not* be compared. `concept_id` optionally pins the
  id (used for `attr_*`, which the recodes file references by name); otherwise
  the id derives from the newest member (`c2025_p9_1`) and is stable across
  rebuilds. `source` marks `manual` (team-verified) vs `frozen-auto` (frozen from
  the old fuzzy matcher, not individually verified — audit these first).
- `concept_recodes_approved.csv` — only for options whose **codes changed** across
  waves (sexo 1/2 → 0/1), which pairs can't express. A wave covered by a recode
  contributes exactly the declared mappings and nothing else.

The canonical option catalog is the **union** of member waves' options (newest
wave's label wins, sentinels normalized to 7777/8888/9999), built only for
**categorical** concepts — numeric ones align by value in the year view, so a
catalog would be meaningless. The build warns (never fails) on declared-comparable
pairs whose option codes diverge, on `exclude` pairs pulled together by
transitivity, and on recodes pointing at nonexistent concepts/options.

`bootstrap_pairs.py` is a **manual tool, not part of the build**: it drafts
candidate pairs by text similarity when a new wave lands, writing a separate
draft file that nothing loads until rows are moved over by hand. See
[docs/conceptos.md](docs/conceptos.md).

### AI chat mode (`backend/chat.py`, `backend/ratelimit.py`)

The model is given the *same* query functions the manual UI calls (Gemini tool
use) and can only act by invoking them — it never emits raw SQL, so chat
answers run through the identical validated/weighted path as the manual UI.
Fully optional: without `GEMINI_API_KEY` the app just runs in manual mode.
`ratelimit.py` enforces per-IP and global daily caps (`CHAT_RATE_PER_MIN`,
`CHAT_DAILY_GLOBAL`, etc. — free-tier defaults live in `render.yaml`).

### Frontend (`frontend/src/`)

Single reactive store (`store.js`, Vue `reactive` + `computed`) holds all
query/UI/chat state; `api.js` is a thin fetch wrapper with one function per
endpoint and no logic. Components read/write the shared store directly rather
than passing props down a tree — check `store.js` first when tracing how a UI
action turns into a query. Larger components: `Sidebar.vue` (question/filter
picker), `QuestionPicker.vue`, `ResultsPanel.vue` / `PivotTables.vue` /
`ChartView.vue` (result rendering), `ChatPanel.vue` (AI mode, renders Markdown
via `marked` + `dompurify`).

## Tests (`tests/`)

`conftest.py` pins `DB_PATH` to the committed DB with an absolute path and adds
`backend/` to `sys.path` *before* importing `main` — tests always run against
real data, not fixtures/mocks. Suites: `test_run_query.py` (query engine
shapes + invariants — base-count regressions, sentinel handling, weighting,
city collapsing, injection guards, year comparison), `test_endpoints.py`,
`test_chat_helpers.py`, `test_ratelimit.py`, and `test_published_figures.py`
(cross-checks live query results against figures published in the annual
report, cited in `tests/published_figures.csv`; run standalone with
`-m published`).
