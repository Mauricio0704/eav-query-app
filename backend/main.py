"""
Encuesta NL — DuckDB Backend
Usage:  uvicorn main:app --reload --port 8000
"""

import os
import re
from functools import lru_cache

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import io
import csv

from metadata import (
    AMM_ID,
    PERIFERIA_ID,
    ID_TO_CITY_NAME,
    DESIRED_ORDERS,
    ATTRIBUTE_LABELS,
    RECODES,
    PRESETS,
    DERIVED_NEXT,
)

DB_PATH = os.getenv("DB_PATH", "../data/encuesta_multianual.duckdb")

# ── Metadata-driven ordering helpers ──────────────────────────────────────────
# City buckets used when grouping by city_id (mirrors DESIRED_ORDERS["municipio"]).
_NL_CITY_IDS = {cid for cid in ID_TO_CITY_NAME if cid < 100}
_AMM_SET = set(AMM_ID)
_PERIFERIA = set(PERIFERIA_ID)
_RESTO_NL = _NL_CITY_IDS - _AMM_SET - _PERIFERIA

# Per-attribute mapping to DESIRED_ORDERS keys (used to order pivot columns).
_ATTRIBUTE_ORDER_KEY = {
    "sexo": "sexo",
    "ingreso": "ingreso",
    "edad_anos": "edad",
    "tipo_escuela": "tipo_escuela",
    "tipo_trabajo": "tipo_trabajo",
    "nivel_max_estudios": "estudios",
    "nivel_actual_estudios": "estudios",
}


def _order_by_desired(items, get_label, desired):
    """Sort `items` so any item whose label appears in `desired` is placed in
    that exact order; everything else is appended alphabetically."""
    if not desired:
        return sorted(items, key=lambda it: get_label(it).lower())
    rank = {label: i for i, label in enumerate(desired)}
    return sorted(
        items,
        key=lambda it: (
            rank.get(get_label(it), 10_000),
            get_label(it).lower(),
        ),
    )


def _recode_case_sql(recode_key: str, value_col: str) -> str:
    """Build a SQL CASE expression that maps `value_col` into the bucket labels
    of a recode definition. The catch-all bucket (values=None) absorbs anything
    not in the explicit lists."""
    recode = RECODES[recode_key]
    cases = []
    catch_all = None
    for label, values in recode["buckets"]:
        safe_label = label.replace("'", "''")
        if values is None:
            catch_all = safe_label
            continue
        vals = ",".join(str(int(v)) for v in values)
        cases.append(f"WHEN {value_col} IN ({vals}) THEN '{safe_label}'")
    if catch_all is not None:
        cases.append(f"WHEN {value_col} IS NOT NULL THEN '{catch_all}'")
    return "CASE\n        " + "\n        ".join(cases) + "\n    END"


def _value_clause(col: str, value) -> str:
    """SQL clause matching `col` against either a single int or a list of ints."""
    if isinstance(value, list):
        if not value:
            return "FALSE"
        return f"{col} IN ({','.join(str(int(v)) for v in value)})"
    return f"{col} = {int(value)}"


def _edad_bin_sql(col):
    """SQL CASE expression that buckets an integer age into the AGE_LABELS
    bins, preserving sentinel codes as their own labels."""
    return f"""CASE
        WHEN {col} = 9999 THEN 'No contesta'
        WHEN {col} = 8888 THEN 'No sabe'
        WHEN {col} = 7777 THEN 'No aplica'
        WHEN {col} <=  5 THEN '0-5'
        WHEN {col} <= 12 THEN '6-12'
        WHEN {col} <= 17 THEN '13-17'
        WHEN {col} <= 24 THEN '18-24'
        WHEN {col} <= 34 THEN '25-34'
        WHEN {col} <= 44 THEN '35-44'
        WHEN {col} <= 54 THEN '45-54'
        WHEN {col} <= 64 THEN '55-64'
        WHEN {col} <= 74 THEN '65-74'
        ELSE '75 o más'
    END"""


app = FastAPI(title="Encuesta NL API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your frontend domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    """Open a read-only connection to the DuckDB database."""
    return duckdb.connect(DB_PATH, read_only=True)


@lru_cache(maxsize=1)
def _wave_ids() -> frozenset[str]:
    """All wave_ids present in the database (for validation)."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT wave_id FROM waves").fetchall()
        return frozenset(r[0] for r in rows)
    finally:
        conn.close()


@lru_cache(maxsize=1)
def _default_wave() -> str:
    """Most recent wave — used whenever a request omits `wave_id`."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT wave_id FROM waves ORDER BY year DESC, wave_id DESC LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("No waves defined in the database")
        return row[0]
    finally:
        conn.close()


def _resolve_wave(wave: str | None) -> str:
    """Validate an incoming wave_id (or fall back to the most recent wave)."""
    w = wave or _default_wave()
    if w not in _wave_ids():
        raise HTTPException(status_code=400, detail=f"Unknown wave_id: {w}")
    return w


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


# ── Question display ordering ─────────────────────────────────────────────────
_NUM_RE = re.compile(r"\d+")


def _question_sort_key(q_id: str):
    if q_id.startswith("cp"):
        rank = 0
    elif q_id.startswith("p"):
        rank = 1
    else:
        rank = 2
    nums = tuple(int(n) for n in _NUM_RE.findall(q_id))
    return (rank, nums, q_id)


def _ordered_question_ids(all_ids: list[str]) -> list[str]:
    """Order question ids per the display rules. Derived questions listed in
    DERIVED_NEXT are placed immediately before their target id (chains and
    several-before-one-target preserve DERIVED_NEXT order); everything else
    sorts by `_question_sort_key`."""
    id_set = set(all_ids)
    derived = {d for d, _ in DERIVED_NEXT if d in id_set}

    # target id -> derived ids to emit just before it, in DERIVED_NEXT order
    before: dict[str, list[str]] = {}
    for d, target in DERIVED_NEXT:
        if d in id_set:
            before.setdefault(target, []).append(d)

    base_ids = sorted((q for q in all_ids if q not in derived), key=_question_sort_key)

    emitted: set[str] = set()
    order: list[str] = []

    def emit(q_id: str) -> None:
        if q_id in emitted or q_id not in id_set:
            return
        for d in before.get(q_id, []):
            emit(d)
        emitted.add(q_id)
        order.append(q_id)

    for q_id in base_ids:
        emit(q_id)
    # Derived whose target is missing/unreachable: append by canonical key.
    for q_id in sorted((q for q in all_ids if q not in emitted), key=_question_sort_key):
        emit(q_id)
    return order


@app.get("/api/questions")
@lru_cache(maxsize=16)
def list_questions(wave: str | None = None):
    """
    Returns all questions with their type, section, and answer options for a
    given wave. Used to populate the question selector in the UI.

    Cached per wave: each wave's schema is immutable for the life of the process.
    """
    conn = get_conn()
    wave = _resolve_wave(wave)
    try:
        questions = conn.execute(
            """
            SELECT
                q.q_id,
                q.q_text,
                q.q_section,
                q.q_type,
                q.q_info,
                q.q_block,
                q.concept_id
            FROM questions q
            WHERE q.wave_id = ?
            ORDER BY q.q_id
        """,
            [wave],
        ).fetchall()

        result = []
        for q_id, q_text, q_section, q_type, q_info, q_block, concept_id in questions:
            # For multiple-choice questions, fetch their options
            options = []
            if q_type != "numerica":
                opts = conn.execute(
                    """
                    SELECT option_id, option_label
                    FROM options
                    WHERE wave_id = ? AND question_id = ?
                    ORDER BY option_id
                """,
                    [wave, q_id],
                ).fetchall()
                options = [{"option_id": oid, "label": lbl} for oid, lbl in opts]

            result.append(
                {
                    "q_id": q_id,
                    "q_text": q_text,
                    "q_section": q_section,
                    "q_type": q_type,
                    "q_info": q_info,
                    "q_block": q_block,
                    "concept_id": concept_id,
                    "options": options,
                }
            )

        order = _ordered_question_ids([r["q_id"] for r in result])
        pos = {q_id: i for i, q_id in enumerate(order)}
        result.sort(key=lambda r: pos[r["q_id"]])
        return result
    finally:
        conn.close()


@app.get("/api/attributes")
@lru_cache(maxsize=16)
def list_attributes(wave: str | None = None):
    """
    Returns all distinct attribute names from respondent_attributes,
    along with their possible values (joined through options table).

    respondent_attributes.attribute  → question_id in options table
    respondent_attributes.value      → option_id in options table

    Cached per wave: attribute definitions are immutable for the life of the process.
    """
    conn = get_conn()
    wave = _resolve_wave(wave)
    try:
        rows = conn.execute(
            """
            SELECT
                ra.attribute,
                ra.value,
                o.option_label
            FROM (
                SELECT DISTINCT question_id, attribute, value
                FROM respondent_attributes
                WHERE wave_id = ?
            ) ra
            LEFT JOIN options o
                ON o.wave_id     = ?
                AND o.question_id = ra.question_id
                AND o.option_id   = ra.value
            ORDER BY ra.attribute, ra.value
        """,
            [wave, wave],
        ).fetchall()

        # Group by attribute
        attrs: dict = {}
        for attr, val, label in rows:
            if attr not in attrs:
                attrs[attr] = []
            attrs[attr].append(
                {
                    "value": val,
                    "label": label or str(val),
                }
            )

        return [
            {"attribute": k, "label": ATTRIBUTE_LABELS.get(k, k), "values": v}
            for k, v in attrs.items()
        ]
    finally:
        conn.close()


@app.get("/api/recodes")
def list_recodes():
    """
    Returns recode definitions: ways of collapsing the values of an attribute
    into named buckets (e.g., tipo_trabajo → Remunerado / No remunerado / Otro).
    Recodes can be used as `group_by` values in /api/query.
    """
    return [
        {
            "key": k,
            "label": v["label"],
            "source_attribute": v["source_attribute"],
            "buckets": [{"label": lbl, "values": vals} for lbl, vals in v["buckets"]],
            "order": v.get("order"),
        }
        for k, v in RECODES.items()
    ]


@app.get("/api/presets")
def list_presets():
    """
    Returns named preset configurations (group_by + filters combinations) that
    the UI can apply as one-click "analysis recipes". Each preset returns a
    payload directly compatible with the /api/query body (minus question_id).
    """
    return PRESETS


@app.get("/api/cities")
@lru_cache(maxsize=16)
def list_cities(wave: str | None = None):
    """Returns distinct city_id values (with municipality names) for use as a
    filter. Unknown ids fall back to showing the raw id.

    Cached per wave: the set of cities is immutable for the life of the process."""
    conn = get_conn()
    wave = _resolve_wave(wave)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT city_id
            FROM responses
            WHERE city_id IS NOT NULL
              AND wave_id = ?
            ORDER BY city_id
        """,
            [wave],
        ).fetchall()
        return [
            {"city_id": r[0], "name": ID_TO_CITY_NAME.get(r[0], str(r[0]))}
            for r in rows
        ]
    finally:
        conn.close()


@app.get("/api/waves")
def list_waves():
    """Returns the survey waves available in the database, most-recent first.
    `is_default` marks the wave used when a request omits `wave_id`."""
    conn = get_conn()
    default = _default_wave()
    try:
        rows = conn.execute(
            "SELECT wave_id, year, label, n_respondents "
            "FROM waves ORDER BY year DESC, wave_id DESC"
        ).fetchall()
        return [
            {
                "wave_id": w,
                "year": year,
                "label": label,
                "n_respondents": n,
                "is_default": w == default,
            }
            for w, year, label, n in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query endpoint
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    question_id: str
    # Each filter: {"attribute": "sexo", "value": 1} or {"attribute": "tipo_trabajo", "value": [1, 4, 6]}
    # For city filter use attribute="city_id"
    filters: list[dict] = []
    group_by: str = "answer"
    # When True, restrict to is_initial_respondent=1 and weight by factor_cvnl
    # (population projection). When False, count every row unweighted.
    initial_only: bool = True
    # Survey wave (year). None → most recent wave. All tables are wave-scoped.
    wave_id: str | None = None


_YEAR_SENTINELS = {7777, 8888, 9999, 5555}


def _fmt_num(v):
    """Formatea un valor numérico como id/etiqueta legible (30.0 → '30')."""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(v)


def _year_comparison(req: QueryRequest):
    """Cross-year comparison ("group_by=year").

    Resolves the concept of the selected question, then runs the flat
    distribution for that concept's question in EACH wave (each weighted by its
    own factor_cvnl) and assembles a pivot with one column per year.

    Categorical → % distribution within each year (options aligned by code).
    Numérica    → weighted mean per year (a single "Promedio" row).
    """
    conn = get_conn()
    try:
        wave = req.wave_id or _default_wave()
        if wave not in _wave_ids():
            raise HTTPException(status_code=400, detail=f"Unknown wave_id: {wave}")
        row = conn.execute(
            "SELECT concept_id, q_text FROM questions WHERE wave_id = ? AND q_id = ?",
            [wave, req.question_id],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Question not found")
        concept_id, q_text = row
        if not concept_id:
            raise HTTPException(
                status_code=400,
                detail="Esta pregunta no tiene equivalencia entre años.",
            )
        crow = conn.execute(
            "SELECT label, q_type, comparable FROM concepts WHERE concept_id = ?",
            [concept_id],
        ).fetchone()
        if not crow or not crow[2]:
            raise HTTPException(
                status_code=400, detail="Concepto no comparable entre años."
            )
        concept_label, concept_type = crow[0], crow[1]
        members = conn.execute(
            "SELECT wave_id, q_id FROM questions WHERE concept_id = ? ORDER BY wave_id",
            [concept_id],
        ).fetchall()
        # Redactado exacto de la pregunta en cada ola (solo para la vista "Año";
        # NO se incluye en el CSV). Siempre los N años, aunque el texto coincida.
        year_texts = []
        for w, q in members:
            tr = conn.execute(
                "SELECT q_text FROM questions WHERE wave_id = ? AND q_id = ?",
                [w, q],
            ).fetchone()
            year_texts.append({"year": w, "q_id": q, "q_text": tr[0] if tr else ""})
        # Catálogo canónico de opciones + mapa (ola, option_id) → opción canónica.
        canon = conn.execute(
            "SELECT concept_option_id, label, sort_order FROM concept_options "
            "WHERE concept_id = ? ORDER BY sort_order",
            [concept_id],
        ).fetchall()
        opt_to_canon = {}
        for w, q in members:
            for oid, coid in conn.execute(
                "SELECT option_id, concept_option_id FROM options "
                "WHERE wave_id = ? AND question_id = ?",
                [w, q],
            ).fetchall():
                opt_to_canon[(w, oid)] = coid

        # Traducción de filtros entre olas: el valor viene en la codificación de
        # la ola base (`wave`); si un atributo se recodificó (p. ej. sexo 1/2 en
        # 2022 vs 0/1), hay que traducir el valor a la codificación de cada ola
        # vía la opción canónica, o el filtro daría 0 en esa ola.
        years = [w for w, _ in members]
        attr_qid = {}
        for w2, a2, q2 in conn.execute(
            "SELECT DISTINCT wave_id, attribute, question_id FROM respondent_attributes"
        ).fetchall():
            attr_qid[(w2, a2)] = q2

        def _canon_of(w2, attr, v):
            q2 = attr_qid.get((w2, attr))
            if not q2:
                return None
            row = conn.execute(
                "SELECT concept_option_id FROM options "
                "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
                [w2, q2, v],
            ).fetchone()
            return row[0] if row and row[0] else None

        def _raw_of(w2, attr, coid):
            q2 = attr_qid.get((w2, attr))
            if not q2:
                return None
            row = conn.execute(
                "SELECT option_id FROM options "
                "WHERE wave_id = ? AND question_id = ? AND concept_option_id = ?",
                [w2, q2, coid],
            ).fetchone()
            return row[0] if row else None

        translated = {}
        for w2 in years:
            tf = []
            for f in req.filters:
                attr = f["attribute"]
                if attr == "city_id" or w2 == wave:
                    tf.append(f)
                    continue
                vals = f["value"] if isinstance(f["value"], list) else [f["value"]]
                nv = []
                for v in vals:
                    coid = _canon_of(wave, attr, v)
                    tv = _raw_of(w2, attr, coid) if coid is not None else None
                    nv.append(tv if tv is not None else v)
                tf.append({"attribute": attr, "value": nv})
            translated[w2] = tf
    finally:
        conn.close()

    qid_by_year = {w: q for w, q in members}

    # Distribución por año (reutiliza el path flat con el peso de cada ola).
    per_year = {}
    for w in years:
        per_year[w] = run_query(
            QueryRequest(
                question_id=qid_by_year[w],
                filters=translated[w],
                group_by="answer",
                initial_only=req.initial_only,
                wave_id=w,
            )
        )

    base = {
        "format": "pivot",
        "question": {"q_id": req.question_id, "q_text": q_text, "q_type": concept_type},
        "filters_applied": req.filters,
        "group_by": "year",
        "concept": {"concept_id": concept_id, "label": concept_label},
        "year_texts": year_texts,
    }
    # Sin columna "Total": sumar respondientes de olas distintas no tiene
    # sentido (cada año es su propia población / su propio 100%).
    columns = ["id_respuesta", "Respuesta", *years]

    if concept_type == "numerica":
        # Distribución de respuestas por año + Promedio + Base. Se alinea por
        # VALOR numérico (si una ola guardó la escala como categórica, el
        # option_id es el valor). Centinelas excluidos.
        dist = {}                       # (valor, w) -> conteo ponderado
        vlabel = {}                     # valor -> etiqueta a mostrar
        denom = {w: 0.0 for w in years}
        for w in years:
            sub = per_year[w]
            numeric_sub = sub["question"]["q_type"] == "numerica"
            for r in sub["rows"]:
                valor = r[0]
                cnt = r[1] if numeric_sub else r[2]
                if valor is None or valor in _YEAR_SENTINELS or not cnt:
                    continue
                dist[(valor, w)] = dist.get((valor, w), 0) + cnt
                denom[w] += cnt
                if numeric_sub:
                    vlabel.setdefault(valor, _fmt_num(valor))
                else:
                    vlabel[valor] = r[1]  # etiqueta categórica gana
        valores = sorted({v for v, _ in dist}, key=lambda x: float(x))

        counts_rows, pct_rows = [], []
        for v in valores:
            disp = _fmt_num(v)
            crow, prow = [disp, vlabel.get(v, disp)], [disp, vlabel.get(v, disp)]
            for w in years:
                c = dist.get((v, w), 0)
                crow.append(round(c) if c else "")
                prow.append(round(c * 100.0 / denom[w], 1) if denom[w] else "")
            counts_rows.append(crow)
            pct_rows.append(prow)
        counts_rows.append(
            ["Total", ""] + [round(denom[w]) if denom[w] else "" for w in years]
        )
        pct_rows.append(
            ["Total", ""] + [100.0 if denom[w] else "" for w in years]
        )

        # Promedio ponderado por año + base (ponderada, sin centinelas).
        prom = ["", "Promedio (media)"]
        grand_n = 0
        for w in years:
            num = den = 0.0
            for v in valores:
                c = dist.get((v, w), 0)
                if c:
                    num += float(v) * c
                    den += c
            prom.append(round(num / den, 2) if den else "")
            grand_n += per_year[w]["total_respondents"]
        n_row = ["", "Base (ponderada)"] + [
            per_year[w]["total_respondents"] for w in years
        ]
        counts_rows.extend([prom, n_row])

        base.update(
            {
                "total_respondents": grand_n,
                "counts": {"columns": columns, "rows": counts_rows},
                "percentages": {"columns": columns, "rows": pct_rows},
            }
        )
        return base

    # Categórica: alinear opciones por opción CANÓNICA (concept_option_id), de
    # modo que códigos distintos entre años (recodes) se comparen como la misma
    # opción. Cae al código crudo si una opción no tiene mapeo canónico.
    canon_label = {coid: lbl for coid, lbl, _ in canon}
    canon_order = {coid: so for coid, lbl, so in canon}
    cnt = {}
    denom = {w: 0 for w in years}
    for w in years:
        for r in per_year[w]["rows"]:
            oid, label, c = r[0], r[1], r[2]
            coid = opt_to_canon.get((w, oid)) or f"{concept_id}:{oid}"
            cnt[(coid, w)] = cnt.get((coid, w), 0) + (c or 0)
            denom[w] += c or 0
            canon_label.setdefault(coid, label)
    coids = sorted({k[0] for k in cnt}, key=lambda k: (canon_order.get(k, 9999), k))

    counts_rows, pct_rows = [], []
    for coid in coids:
        disp_id = coid.split(":")[-1]
        label = canon_label.get(coid, disp_id)
        crow, prow = [disp_id, label], [disp_id, label]
        for w in years:
            c = cnt.get((coid, w), 0)
            crow.append(c if c else "")
            prow.append(round(c * 100.0 / denom[w], 1) if denom[w] else "")
        counts_rows.append(crow)
        pct_rows.append(prow)

    counts_rows.append(["Total", ""] + [denom[w] for w in years])
    pct_rows.append(["Total", ""] + [100.0 if denom[w] else "" for w in years])

    base.update(
        {
            "total_respondents": sum(denom.values()),
            "counts": {"columns": columns, "rows": counts_rows},
            "percentages": {"columns": columns, "rows": pct_rows},
        }
    )
    return base


@app.post("/api/query")
def run_query(req: QueryRequest):
    """
    Core query endpoint. Builds and executes a SQL query against DuckDB.

    group_by="answer" (flat shape):
      - Multiple-choice questions: one row per option with count + percentage.
      - Numeric questions: one row per distinct value with count + percentage
        (a frequency breakdown; sentinels 7777/8888/9999 excluded).

    group_by != "answer" (pivot shape): two tables — counts and percentages —
    each with a Total row/column. Numeric questions add a single "Promedio"
    (weighted mean) row to the counts table.

    group_by="year" (cross-year pivot): compares the selected question's concept
    across the waves where it exists (see `_year_comparison`).
    """
    if req.group_by in ("year", "año", "anio"):
        return _year_comparison(req)

    conn = get_conn()
    try:
        # Resolve + validate the wave. `wave` comes from a known set, so it is
        # safe to inline into the SQL strings below alongside question_id.
        wave = req.wave_id or _default_wave()
        if wave not in _wave_ids():
            raise HTTPException(status_code=400, detail=f"Unknown wave_id: {wave}")

        # Determine question type (within this wave)
        q_info = conn.execute(
            "SELECT q_type, q_text FROM questions WHERE wave_id = ? AND q_id = ?",
            [wave, req.question_id],
        ).fetchone()

        if not q_info:
            raise HTTPException(status_code=404, detail="Question not found")

        q_type, q_text = q_info

        # SQL-injection guard
        valid_attrs = {a["attribute"] for a in list_attributes()}
        for f in req.filters:
            attr = f.get("attribute")
            if attr != "city_id" and attr not in valid_attrs:
                raise HTTPException(
                    status_code=400, detail=f"Unknown filter attribute: {attr}"
                )

        valid_group_by = {"answer", "city_id", "edad_anos"} | set(RECODES) | valid_attrs
        if req.group_by not in valid_group_by:
            raise HTTPException(
                status_code=400, detail=f"Unknown group_by: {req.group_by}"
            )

        # `initial_only` controls both the cohort and the weighting:
        #  - True  → restrict to is_initial_respondent=1, project to population
        #            via factor_cvnl (this is the canonical CVNL methodology)
        #  - False → count every respondent row unweighted (raw sample counts)
        weighted = req.initial_only
        initial_filter = "AND r.is_initial_respondent = 1" if req.initial_only else ""
        count_expr = "SUM(r.factor_cvnl)" if weighted else "COUNT(*)"
        count_int = f"ROUND({count_expr})::BIGINT" if weighted else "COUNT(*)"
        avg_expr = (
            "ROUND((SUM(a.value * r.factor_cvnl) / NULLIF(SUM(r.factor_cvnl), 0))::NUMERIC, 2)"
            if weighted
            else "ROUND(AVG(a.value)::NUMERIC, 2)"
        )

        # Build the respondent filter subquery using respondent_attributes
        # Each attribute filter becomes an INNER JOIN
        attr_filters = [f for f in req.filters if f["attribute"] != "city_id"]
        city_filter = next(
            (f for f in req.filters if f["attribute"] == "city_id"), None
        )

        join_clauses = ""
        for i, f in enumerate(attr_filters):
            alias = f"ra{i}"
            value_clause = _value_clause(f"{alias}.value", f["value"])
            join_clauses += f"""
            INNER JOIN respondent_attributes {alias}
                ON {alias}.respondent_id = r.respondent_id
                AND {alias}.wave_id = '{wave}'
                AND {alias}.attribute = '{f["attribute"]}'
                AND {value_clause}"""

        city_where = ""
        if city_filter:
            city_where = "AND " + _value_clause("r.city_id", city_filter["value"])

        # Total respondents for this query (sentinel-filtered for numerica).
        # Weighted form sums factor_cvnl over distinct (respondent, factor) rows.
        # Categorical answers store the response in `option_id` and leave
        # `a.value` NULL, so applying the sentinel filter there would drop
        # every row (NULL NOT IN (...) is NULL/falsy).
        sentinel_filter = (
            "AND a.value NOT IN (7777, 8888, 9999)" if q_type == "numerica" else ""
        )
        if weighted:
            total_sql = f"""
                SELECT ROUND(SUM(factor_cvnl))::BIGINT FROM (
                    SELECT DISTINCT a.respondent_id, r.factor_cvnl
                    FROM answers a
                    INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                    {join_clauses}
                    WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                      {sentinel_filter}
                      {initial_filter}
                      {city_where}
                )
            """
        else:
            total_sql = f"""
                SELECT COUNT(DISTINCT a.respondent_id)
                FROM answers a
                INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                {join_clauses}
                WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                  {sentinel_filter}
                  {initial_filter}
                  {city_where}
            """
        total_respondents = (conn.execute(total_sql).fetchone() or (0,))[0]

        # ── group_by="answer" → flat shape (no pivot) ─────────────────────
        if req.group_by == "answer":
            if q_type == "numerica":
                # Frequency breakdown: one row per distinct numeric value (the
                # value IS the answer, so no separate option label/id), with
                # weighted count + percentage. Sentinels excluded.
                sql = f"""
                    WITH base AS (
                        SELECT a.value      AS valor,
                               {count_expr} AS cnt
                        FROM answers a
                        INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                        {join_clauses}
                        WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                          AND a.value NOT IN (7777, 8888, 9999)
                          {initial_filter}
                          {city_where}
                        GROUP BY a.value
                    ),
                    totals AS (SELECT SUM(cnt) AS total FROM base)
                    SELECT b.valor,
                           ROUND(b.cnt)::BIGINT                 AS total,
                           ROUND(b.cnt * 100.0 / t.total, 1)    AS pct
                    FROM base b CROSS JOIN totals t
                    ORDER BY b.valor ASC
                """
                rows = conn.execute(sql).fetchall()
                col_labels = ["Respuesta", "Respuestas", "%"]
            else:
                sql = f"""
                    WITH base AS (
                        SELECT a.option_id     AS id_respuesta,
                               o.option_label  AS respuesta,
                               {count_expr}    AS cnt
                        FROM answers a
                        INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                        INNER JOIN options o
                            ON o.wave_id = '{wave}'
                            AND o.question_id = a.question_id
                            AND o.option_id = a.option_id
                        {join_clauses}
                        WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                          {initial_filter}
                          {city_where}
                        GROUP BY id_respuesta, respuesta
                    ),
                    totals AS (SELECT SUM(cnt) AS total FROM base)
                    SELECT b.id_respuesta,
                           b.respuesta,
                           ROUND(b.cnt)::BIGINT                 AS total,
                           ROUND(b.cnt * 100.0 / t.total, 1)    AS pct
                    FROM base b CROSS JOIN totals t
                    ORDER BY b.id_respuesta ASC
                """
                rows = conn.execute(sql).fetchall()
                col_labels = ["id_respuesta", "Respuesta", "Total", "%"]

            return {
                "format": "flat",
                "question": {
                    "q_id": req.question_id,
                    "q_text": q_text,
                    "q_type": q_type,
                },
                "filters_applied": req.filters,
                "group_by": req.group_by,
                "total_respondents": total_respondents,
                "column_labels": col_labels,
                "rows": [list(r) for r in rows],
                "sql": sql.strip(),
            }

        # ── pivot mode (group_by != "answer") ─────────────────────────────
        if req.group_by == "city_id":
            group_expr = "r.city_id::TEXT"
        elif req.group_by == "edad_anos":
            # Bucket integer ages into AGE_LABELS instead of producing one
            # column per integer year (would yield ~80 cols).
            group_expr = f"""(
                SELECT {_edad_bin_sql('rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = 'edad_anos'
                LIMIT 1
            )"""
        elif req.group_by in RECODES:
            recode_src = RECODES[req.group_by]["source_attribute"]
            group_expr = f"""(
                SELECT {_recode_case_sql(req.group_by, 'rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{recode_src}'
                LIMIT 1
            )"""
        else:
            # `respondent_attributes` stores the survey question_id (e.g. 'cp2')
            # alongside the friendly attribute name (e.g. 'sexo'). The option
            # label lives in `options` keyed by that question_id + value, NOT
            # by the attribute name. Fall back to the raw value when the
            # attribute has no entries in `options` (e.g. edad_anos).
            group_expr = f"""(
                SELECT COALESCE(o2.option_label, rg.value::TEXT)
                FROM respondent_attributes rg
                LEFT JOIN options o2
                  ON o2.wave_id     = '{wave}'
                 AND o2.question_id = rg.question_id
                 AND o2.option_id   = rg.value
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{req.group_by}'
                LIMIT 1
            )"""

        # Per-group totals INCLUDING sentinels — these are the column denominators
        # for the percentage table and the "Total" row in the count table.
        per_group_total_sql = f"""
            SELECT {group_expr} AS grupo, {count_int} AS total
            FROM answers a
            INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
            {join_clauses}
            WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
              {initial_filter}
              {city_where}
            GROUP BY grupo
            HAVING grupo IS NOT NULL
        """
        group_totals_raw = {
            row[0]: row[1] for row in conn.execute(per_group_total_sql).fetchall()
        }
        grand_total_incl = sum(group_totals_raw.values())

        # Initial group_keys keep the raw shape returned by the SQL (city_ids
        # for city_id grouping, attribute labels otherwise). For non-city
        # groupings we already apply the metadata-driven order here. For
        # `city_id` we keep raw ids for now; cell_map / stats are remapped
        # to metadata labels (11 AMM cities + 4 aggregates) further down.
        if req.group_by == "city_id":
            # When the user ALSO filters by city, show one column per filtered
            # municipality (no AMM/Periferia/Resto NL/Nuevo León aggregates) so
            # only the requested cities appear. Otherwise show the full curated
            # set: the 11 AMM cities + the 4 aggregates.
            city_filter_ids = None
            if city_filter:
                raw_vals = city_filter["value"]
                city_filter_ids = raw_vals if isinstance(raw_vals, list) else [raw_vals]
            if city_filter_ids:
                label_to_city_ids = {}
                for cid in city_filter_ids:
                    lbl = ID_TO_CITY_NAME.get(int(cid), str(cid))
                    label_to_city_ids.setdefault(lbl, set()).add(str(int(cid)))
                muni_rank = {m: i for i, m in enumerate(DESIRED_ORDERS["municipio"])}
                city_bucket_labels = sorted(
                    label_to_city_ids.keys(),
                    key=lambda l: (muni_rank.get(l, 10_000), l.lower()),
                )
            else:
                label_to_city_ids = {ID_TO_CITY_NAME[cid]: {str(cid)} for cid in AMM_ID}
                label_to_city_ids["AMM"] = {str(c) for c in AMM_ID}
                label_to_city_ids["Periferia"] = {str(c) for c in PERIFERIA_ID}
                label_to_city_ids["Resto NL"] = {str(c) for c in _RESTO_NL}
                label_to_city_ids["Nuevo León"] = {str(c) for c in _NL_CITY_IDS}
                city_bucket_labels = list(DESIRED_ORDERS["municipio"])
            group_keys = list(group_totals_raw.keys())
            group_labels = group_keys  # placeholder, replaced below
        else:

            def display(g):
                return str(g)

            if req.group_by in RECODES:
                desired = RECODES[req.group_by].get("order")
            else:
                order_key = _ATTRIBUTE_ORDER_KEY.get(req.group_by)
                desired = DESIRED_ORDERS.get(order_key) if order_key else None
            group_keys = _order_by_desired(
                list(group_totals_raw.keys()), display, desired
            )
            group_labels = [display(g) for g in group_keys]
            label_to_city_ids = {}
            city_bucket_labels = []  # only used in the city_id branch below

        # Option-id → option-label lookup for the "Respuesta" column.
        opt_lookup = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT option_id, option_label FROM options WHERE wave_id = ? AND question_id = ?",
                [wave, req.question_id],
            ).fetchall()
        }

        if q_type == "numerica":
            freq_sql = f"""
                SELECT a.value AS id_respuesta,
                       {group_expr} AS grupo,
                       {count_int} AS cnt
                FROM answers a
                INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                {join_clauses}
                WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                  AND a.value IS NOT NULL
                  {initial_filter}
                  {city_where}
                GROUP BY id_respuesta, grupo
                ORDER BY id_respuesta
            """
            freq_rows = conn.execute(freq_sql).fetchall()

            stats_sql = f"""
                SELECT {group_expr} AS grupo,
                       {avg_expr} AS promedio
                FROM answers a
                INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                {join_clauses}
                WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                  AND a.value NOT IN (7777, 8888, 9999)
                  {initial_filter}
                  {city_where}
                GROUP BY grupo
                HAVING grupo IS NOT NULL
            """
            stats_per_group = {
                row[0]: list(row[1:]) for row in conn.execute(stats_sql).fetchall()
            }

            overall_stats_sql = f"""
                SELECT {avg_expr}
                FROM answers a
                INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                {join_clauses}
                WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                  AND a.value NOT IN (7777, 8888, 9999)
                  {initial_filter}
                  {city_where}
            """
            overall_stats = list(conn.execute(overall_stats_sql).fetchone() or [None])

            distinct_values = sorted(
                {r[0] for r in freq_rows}, key=lambda v: (v is None, v)
            )
            cell_map = {(r[0], r[1]): r[2] for r in freq_rows}

            # Collapse raw city_ids into the curated metadata buckets (11 AMM
            # cities + AMM/Periferia/Resto NL/Nuevo León aggregates). Stats
            # for the four aggregates are recomputed via SQL because they
            # don't compose from per-city pre-aggregated stats.
            if req.group_by == "city_id":
                new_cell_map = {}
                new_totals = {}
                for label in city_bucket_labels:
                    ids = label_to_city_ids.get(label, set())
                    new_totals[label] = sum(group_totals_raw.get(c, 0) for c in ids)
                    for v in distinct_values:
                        s = sum(cell_map.get((v, c), 0) for c in ids)
                        if s:
                            new_cell_map[(v, label)] = s
                cell_map = new_cell_map
                group_totals_raw = new_totals
                grand_total_incl = new_totals.get("Nuevo León", grand_total_incl)
                group_keys = list(city_bucket_labels)
                group_labels = list(group_keys)

                # Per-bucket stats: a single-city bucket reuses the precomputed
                # per-city stats; an aggregate bucket (>1 city) is recomputed via
                # SQL because stats don't compose from per-city aggregates.
                new_stats = {}
                for label in city_bucket_labels:
                    ids = sorted(int(c) for c in label_to_city_ids.get(label, set()))
                    if not ids:
                        continue
                    if len(ids) == 1:
                        raw = stats_per_group.get(str(ids[0]))
                        if raw:
                            new_stats[label] = raw
                        continue
                    in_clause = ",".join(str(i) for i in ids)
                    agg_row = conn.execute(f"""
                        SELECT {avg_expr}
                        FROM answers a
                        INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
                        {join_clauses}
                        WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
                          AND a.value NOT IN (7777, 8888, 9999)
                          AND r.city_id IN ({in_clause})
                          {initial_filter}
                          {city_where}
                    """).fetchone()
                    if agg_row and agg_row[0] is not None:
                        new_stats[label] = list(agg_row)
                stats_per_group = new_stats

            def label_for(value):
                key = (
                    int(value)
                    if value is not None and float(value).is_integer()
                    else value
                )
                lbl = opt_lookup.get(key)
                return (
                    lbl
                    if lbl is not None
                    else (str(value) if value is not None else "")
                )

            counts_columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
            pct_columns = list(counts_columns)

            # When grouping by city_id, the column list includes overlapping
            # aggregate buckets (AMM ⊃ the 11 cities, Nuevo León ⊃ everything).
            # Sum only over the mutually-exclusive subset for the row total.
            atomic_keys = (
                [g for g in group_keys if g not in ("AMM", "Nuevo León")]
                if req.group_by == "city_id"
                else list(group_keys)
            )

            counts_rows = []
            pct_rows = []
            for v in distinct_values:
                row_total = sum(cell_map.get((v, g), 0) for g in atomic_keys)
                count_row = [v, label_for(v)]
                pct_row = [v, label_for(v)]
                for g in group_keys:
                    cnt = cell_map.get((v, g), 0)
                    grp_t = group_totals_raw.get(g, 0)
                    count_row.append(cnt if cnt else "")
                    pct_row.append(round(cnt * 100.0 / grp_t, 1) if grp_t else "")
                count_row.append(row_total if row_total else "")
                pct_row.append(
                    round(row_total * 100.0 / grand_total_incl, 1)
                    if grand_total_incl
                    else ""
                )
                counts_rows.append(count_row)
                pct_rows.append(pct_row)

            # Total row
            counts_rows.append(
                ["Total", ""]
                + [group_totals_raw.get(g, 0) for g in group_keys]
                + [grand_total_incl]
            )
            pct_rows.append(
                ["Total", ""]
                + [100.0 if group_totals_raw.get(g, 0) else "" for g in group_keys]
                + [100.0 if grand_total_incl else ""]
            )

            # Stat rows (counts table only — they aren't percentages)
            stat_names = ["Promedio"]
            for i, name in enumerate(stat_names):
                row = [name, ""]
                for g in group_keys:
                    v = stats_per_group.get(g, [None])[i]
                    row.append(v if v is not None else "")
                stat_val = overall_stats[i]
                row.append(stat_val if stat_val is not None else "")
                counts_rows.append(row)

            return {
                "format": "pivot",
                "question": {
                    "q_id": req.question_id,
                    "q_text": q_text,
                    "q_type": q_type,
                },
                "filters_applied": req.filters,
                "group_by": req.group_by,
                "total_respondents": total_respondents,
                "counts": {"columns": counts_columns, "rows": counts_rows},
                "percentages": {"columns": pct_columns, "rows": pct_rows},
                "sql": freq_sql.strip(),
            }

        # categórica + non-answer pivot
        freq_sql = f"""
            SELECT a.option_id AS id_respuesta,
                   o.option_label AS respuesta,
                   {group_expr} AS grupo,
                   {count_int} AS cnt
            FROM answers a
            INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'
            LEFT JOIN options o
                ON o.wave_id = '{wave}'
                AND o.question_id = a.question_id
                AND o.option_id = a.option_id
            {join_clauses}
            WHERE a.wave_id = '{wave}' AND a.question_id = '{req.question_id}'
              {initial_filter}
              {city_where}
            GROUP BY id_respuesta, respuesta, grupo
            ORDER BY id_respuesta
        """
        freq_rows = conn.execute(freq_sql).fetchall()

        # Distinct (option_id, label) ordered by id
        seen = {}
        for r in freq_rows:
            key = r[0]
            if key not in seen:
                seen[key] = r[1]
        option_keys = sorted(seen.keys(), key=lambda k: (k is None, k))
        cell_map = {(r[0], r[2]): r[3] for r in freq_rows}

        # Same metadata-driven collapse for city groupings as in the numérica
        # branch — sum per-city counts into the AMM/Periferia/RestoNL/NL buckets.
        if req.group_by == "city_id":
            new_cell_map = {}
            new_totals = {}
            for label in city_bucket_labels:
                ids = label_to_city_ids.get(label, set())
                new_totals[label] = sum(group_totals_raw.get(c, 0) for c in ids)
                for opt_id in option_keys:
                    s = sum(cell_map.get((opt_id, c), 0) for c in ids)
                    if s:
                        new_cell_map[(opt_id, label)] = s
            cell_map = new_cell_map
            group_totals_raw = new_totals
            grand_total_incl = new_totals.get("Nuevo León", grand_total_incl)
            group_keys = list(city_bucket_labels)
            group_labels = list(group_keys)

        counts_columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
        pct_columns = list(counts_columns)

        atomic_keys = (
            [g for g in group_keys if g not in ("AMM", "Nuevo León")]
            if req.group_by == "city_id"
            else list(group_keys)
        )

        counts_rows = []
        pct_rows = []
        for opt_id in option_keys:
            label_in_opts = opt_lookup.get(opt_id)
            label = (
                label_in_opts
                if label_in_opts is not None
                else (str(opt_id) if opt_id is not None else "")
            )
            row_total = sum(cell_map.get((opt_id, g), 0) for g in atomic_keys)
            count_row = [opt_id, label]
            pct_row = [opt_id, label]
            for g in group_keys:
                cnt = cell_map.get((opt_id, g), 0)
                grp_t = group_totals_raw.get(g, 0)
                count_row.append(cnt if cnt else "")
                pct_row.append(round(cnt * 100.0 / grp_t, 1) if grp_t else "")
            count_row.append(row_total if row_total else "")
            pct_row.append(
                round(row_total * 100.0 / grand_total_incl, 1)
                if grand_total_incl
                else ""
            )
            counts_rows.append(count_row)
            pct_rows.append(pct_row)

        # Total row
        counts_rows.append(
            ["Total", ""]
            + [group_totals_raw.get(g, 0) for g in group_keys]
            + [grand_total_incl]
        )
        pct_rows.append(
            ["Total", ""]
            + [100.0 if group_totals_raw.get(g, 0) else "" for g in group_keys]
            + [100.0 if grand_total_incl else ""]
        )

        return {
            "format": "pivot",
            "question": {"q_id": req.question_id, "q_text": q_text, "q_type": q_type},
            "filters_applied": req.filters,
            "group_by": req.group_by,
            "total_respondents": total_respondents,
            "counts": {"columns": counts_columns, "rows": counts_rows},
            "percentages": {"columns": pct_columns, "rows": pct_rows},
            "sql": freq_sql.strip(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/query/csv")
def export_csv(req: QueryRequest):
    """Same as /api/query but returns a CSV file download.

    Pivot mode emits two tables in a single CSV: a Conteos block and a
    Porcentajes block, separated by a blank line.
    """
    data = run_query(req)

    output = io.StringIO()
    writer = csv.writer(output)

    if data.get("format") == "pivot":
        writer.writerow(["Conteos"])
        writer.writerow(data["counts"]["columns"])
        for row in data["counts"]["rows"]:
            writer.writerow(row)
        writer.writerow([])
        writer.writerow(["Porcentajes"])
        writer.writerow(data["percentages"]["columns"])
        for row in data["percentages"]["rows"]:
            writer.writerow(row)
    else:
        writer.writerow(data["column_labels"])
        for row in data["rows"]:
            writer.writerow(row)

    output.seek(0)
    filename = f"encuesta_p{req.question_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "db": DB_PATH}


# ---------------------------------------------------------------------------
# AI chat (text-to-query via Gemini function-calling)
# ---------------------------------------------------------------------------
# Imported last so the lazy `from main import ...` calls inside chat.py resolve
# against a fully-loaded module (no circular import at load time).
from chat import router as chat_router  # noqa: E402

app.include_router(chat_router)


# ---------------------------------------------------------------------------
# Static frontend (production)
# ---------------------------------------------------------------------------
# When STATIC_DIR is set and points to a built Vite output (frontend/dist),
# serve it at the root path. Must run AFTER all /api/* routes are registered
# so they take precedence over the catch-all static mount.
STATIC_DIR = os.getenv("STATIC_DIR", "../frontend/dist")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
