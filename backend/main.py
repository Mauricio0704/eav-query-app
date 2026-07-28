"""
Encuesta NL — Backend sobre DuckDB.

Motor de consultas de la encuesta CVNL (FastAPI + DuckDB de solo lectura).
Arranque:  uvicorn main:app --reload --port 8000
Docs de arquitectura: ver docs/ en la raíz del repo.
"""

import os
import re
import logging
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

log = logging.getLogger("encuesta")

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


def _attr_question_id(conn, wave: str, attribute: str) -> str | None:
    """The survey question_id that backs a friendly attribute in a given wave
    (e.g. sexo → cp2 en 2025, cp2_1 en 2022)."""
    row = conn.execute(
        "SELECT DISTINCT question_id FROM respondent_attributes "
        "WHERE wave_id = ? AND attribute = ?",
        [wave, attribute],
    ).fetchone()
    return row[0] if row else None


def _translate_attr_value(conn, attribute: str, value, from_wave: str, to_wave: str):
    """Traduce el `option_id` de un atributo entre olas vía la opción canónica.
    La codificación cambia entre años (p. ej. sexo 0=Hombre en 2025 pero 1 en
    2022), así que un id fijo daría 0 filas o la categoría equivocada en otra ola.
    Devuelve el valor original si no hay mapeo canónico (nada que traducir)."""
    if from_wave == to_wave:
        return value
    q_from = _attr_question_id(conn, from_wave, attribute)
    q_to = _attr_question_id(conn, to_wave, attribute)
    if not q_from or not q_to:
        return value
    coid_row = conn.execute(
        "SELECT concept_option_id FROM options "
        "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
        [from_wave, q_from, value],
    ).fetchone()
    if not coid_row or not coid_row[0]:
        return value
    raw_row = conn.execute(
        "SELECT option_id FROM options "
        "WHERE wave_id = ? AND question_id = ? AND concept_option_id = ?",
        [to_wave, q_to, coid_row[0]],
    ).fetchone()
    return raw_row[0] if raw_row else value


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
def list_presets(wave: str | None = None):
    """
    Returns named preset configurations (group_by + filters combinations) that
    the UI can apply as one-click "analysis recipes". Each preset returns a
    payload directly compatible with the /api/query body (minus question_id).

    Los presets están escritos en la codificación de la ola default (p. ej.
    sexo 0=Hombre, 1=Mujer). Como esa codificación cambia entre años, aquí se
    traducen los valores de filtro a la ola pedida (`wave`) vía la opción
    canónica, para que "MUJERES por unidad geográfica" filtre a mujeres en
    CUALQUIER ola y no caiga en la categoría equivocada o en cero filas.
    """
    target = _resolve_wave(wave)
    default = _default_wave()
    if target == default:
        return PRESETS

    conn = get_conn()
    try:
        out = []
        for p in PRESETS:
            new_filters = []
            for f in p.get("filters") or []:
                attr = f["attribute"]
                val = f["value"]
                if attr == "city_id":
                    new_filters.append(f)
                    continue
                is_list = isinstance(val, list)
                vals = val if is_list else [val]
                nv = [
                    _translate_attr_value(conn, attr, v, default, target) for v in vals
                ]
                new_filters.append({"attribute": attr, "value": nv if is_list else nv[0]})
            out.append({**p, "filters": new_filters})
        return out
    finally:
        conn.close()


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
    # Cada filtro: {"attribute": "sexo", "value": 1} o {"attribute": "tipo_trabajo", "value": [1, 4, 6]}
    # Para filtrar por ciudad usar attribute="city_id".
    filters: list[dict] = []
    group_by: str = "answer"
    # True  → restringe a is_initial_respondent=1 y pondera por factor_cvnl
    #         (proyección a población). False → cuenta cada fila sin ponderar.
    initial_only: bool = True
    # Ola (año) de la encuesta. None → ola más reciente. Todas las tablas están
    # particionadas por ola.
    wave_id: str | None = None


_YEAR_SENTINELS = {7777, 8888, 9999, 5555}

# Códigos-centinela "sospechosos" que algunas olas usan para No sabe/No contesta/
# No aplica en preguntas NUMÉRICAS, además del estándar 7777/8888/9999. No se
# excluyen a ciegas: sólo cuentan como centinela en una pregunta si SUPERAN el
# techo de valores reales de esa pregunta (ver _extra_numeric_sentinels), para
# no tirar valores legítimos como una edad de 88 o un gasto de $96.
_NUM_SENT_SUSPECT = (88, 96, 97, 98, 99, 888, 997, 998, 999, 5555, 9995, 9996, 9998)
_NUM_SENT_CACHE = None


def _extra_numeric_sentinels():
    """(wave, question) → set de códigos sospechosos que exceden el máximo valor
    real de esa pregunta ⇒ son centinelas (ej. 99 "días a la semana", 999
    "bicicletas") y deben salir del promedio. Un código sospechoso DENTRO del
    rango real (edad 88, gasto 96) se conserva. Se calcula una vez y se cachea."""
    global _NUM_SENT_CACHE
    if _NUM_SENT_CACHE is None:
        s = ", ".join(str(x) for x in _NUM_SENT_SUSPECT)
        rows = get_conn().execute(
            f"""
            WITH nq AS (SELECT wave_id, q_id FROM questions WHERE q_type='numerica'),
            vals AS (
                SELECT a.wave_id, a.question_id, a.value
                FROM answers a
                JOIN nq ON nq.wave_id = a.wave_id AND nq.q_id = a.question_id
                WHERE a.value IS NOT NULL AND a.value NOT IN (7777, 8888, 9999)
                GROUP BY 1, 2, 3
            ),
            ceil AS (
                SELECT wave_id, question_id,
                       MAX(value) FILTER (WHERE value NOT IN ({s})) AS hi
                FROM vals GROUP BY 1, 2
            )
            SELECT v.wave_id, v.question_id, v.value
            FROM vals v JOIN ceil c USING (wave_id, question_id)
            WHERE v.value IN ({s}) AND v.value > COALESCE(c.hi, 0)
            """
        ).fetchall()
        cache = {}
        for w, q, val in rows:
            cache.setdefault((w, q), set()).add(int(val))
        _NUM_SENT_CACHE = cache
    return _NUM_SENT_CACHE


def _numeric_sentinel_sql(wave, qid):
    """Lista para `a.value NOT IN (...)`: el estándar 7777/8888/9999 unido a los
    centinelas no estándar detectados para esta pregunta."""
    vals = sorted({7777, 8888, 9999} | _extra_numeric_sentinels().get((wave, qid), set()))
    return ", ".join(str(v) for v in vals)


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
        # Base (universo) por año: cada ola es su propia población, así que se
        # muestran por separado en vez de sumarlas (la suma no tiene sentido).
        "year_bases": [
            {"year": w, "base": per_year[w]["total_respondents"]} for w in years
        ],
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
            prom.append(round(num / den, 2) if den else "") # type: ignore
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


# ---------------------------------------------------------------------------
# Helpers del motor de query (compartidos por los cuatro caminos de run_query)
# ---------------------------------------------------------------------------


def _base_from_where(
    wave: str,
    qid: str,
    join_clauses: str,
    initial_filter: str,
    city_where: str,
    extra_where: str = "",
    with_options: bool = False,
) -> str:
    """Bloque FROM/JOIN/WHERE común a todas las consultas del motor.

    Slots variables:
      - `extra_where`   inyecta el filtro de centinelas o de no-nulos según el caso.
      - `with_options`  agrega el LEFT JOIN al catálogo de opciones (trae etiquetas
                        sin tirar códigos sin catálogo; ver Capa A).
    `wave` y `qid` vienen de un conjunto validado.
    El SELECT y el GROUP BY los pone cada llamador porque difieren por caso."""
    opt_join = (
        f"""
        LEFT JOIN options o
            ON o.wave_id = '{wave}'
            AND o.question_id = a.question_id
            AND o.option_id = a.option_id"""
        if with_options
        else ""
    )
    return f"""
        FROM answers a
        INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'{opt_join}
        {join_clauses}
        WHERE a.wave_id = '{wave}' AND a.question_id = '{qid}'
          {extra_where}
          {initial_filter}
          {city_where}"""


def _collapse_city_cells(items, cell_map, group_totals_raw, city_bucket_labels,
                         label_to_city_ids):
    """Colapsa los `city_id` crudos en los buckets curados de metadata (las 11
    ciudades del AMM + agregados AMM/Periferia/Resto NL/Nuevo León).

    Suma, por cada bucket, los conteos de sus ciudades. Idéntico para numérica y
    categórica (sólo cambia qué son los `items`: valores numéricos u option_ids).
    Devuelve `(cell_map_colapsado, totales_por_bucket)`. Los stats de las
    numéricas se recalculan aparte (no componen desde los stats por ciudad)."""
    new_cell_map, new_totals = {}, {}
    for label in city_bucket_labels:
        ids = label_to_city_ids.get(label, set())
        new_totals[label] = sum(group_totals_raw.get(c, 0) for c in ids)
        for it in items:
            s = sum(cell_map.get((it, c), 0) for c in ids)
            if s:
                new_cell_map[(it, label)] = s
    return new_cell_map, new_totals


def _pivot_count_pct_rows(items, label_of, cell_map, group_keys, group_totals,
                          grand_total, is_city):
    """Ensambla las filas de conteos y porcentajes de una tabla pivote.

    Un renglón por `item` (option_id o valor numérico) con una celda por grupo,
    más la columna Total y la fila Total. La lógica es idéntica para numérica y
    categórica; sólo cambia `label_of(item)` → etiqueta a mostrar.

    Con `is_city=True` la fila Total se suma sólo sobre buckets mutuamente
    excluyentes (excluye AMM y Nuevo León, que son superconjuntos y duplicarían)."""
    atomic_keys = (
        [g for g in group_keys if g not in ("AMM", "Nuevo León")]
        if is_city
        else list(group_keys)
    )
    counts_rows, pct_rows = [], []
    for it in items:
        label = label_of(it)
        row_total = sum(cell_map.get((it, g), 0) for g in atomic_keys)
        count_row = [it, label]
        pct_row = [it, label]
        for g in group_keys:
            cnt = cell_map.get((it, g), 0)
            grp_t = group_totals.get(g, 0)
            count_row.append(cnt if cnt else "")
            pct_row.append(round(cnt * 100.0 / grp_t, 1) if grp_t else "")
        count_row.append(row_total if row_total else "")
        pct_row.append(
            round(row_total * 100.0 / grand_total, 1) if grand_total else ""
        )
        counts_rows.append(count_row)
        pct_rows.append(pct_row)

    counts_rows.append(
        ["Total", ""] + [group_totals.get(g, 0) for g in group_keys] + [grand_total]
    )
    pct_rows.append(
        ["Total", ""]
        + [100.0 if group_totals.get(g, 0) else "" for g in group_keys]
        + [100.0 if grand_total else ""]
    )
    return counts_rows, pct_rows


def _group_expr_sql(group_by: str, wave: str) -> str:
    """Expresión SQL que produce la etiqueta de columna del pivote para cada
    respondiente, según `group_by`. Se embebe en consultas donde `r` (responses)
    está en scope:
      - city_id   → el city_id crudo (se colapsa a buckets después, en Python).
      - edad_anos → subconsulta que bucketiza la edad en rangos en vez de una
                    columna por año (serían ~80 columnas).
      - recode    → subconsulta con el CASE del recode (agrupa opciones).
      - atributo  → subconsulta que resuelve la etiqueta desde `options` por el
                    question_id que respalda al atributo; cae al valor crudo si no
                    hay etiqueta (p. ej. edad_anos)."""
    if group_by == "city_id":
        return "r.city_id::TEXT"
    if group_by == "edad_anos":
        return f"""(
                SELECT {_edad_bin_sql('rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = 'edad_anos'
                LIMIT 1
            )"""
    if group_by in RECODES:
        recode_src = RECODES[group_by]["source_attribute"]
        return f"""(
                SELECT {_recode_case_sql(group_by, 'rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{recode_src}'
                LIMIT 1
            )"""
    # `respondent_attributes` guarda el question_id de la encuesta (p. ej. 'cp2')
    # junto al nombre amigable del atributo ('sexo'). La etiqueta vive en `options`
    # keyeada por ese question_id + valor, NO por el nombre del atributo.
    return f"""(
                SELECT COALESCE(o2.option_label, rg.value::TEXT)
                FROM respondent_attributes rg
                LEFT JOIN options o2
                  ON o2.wave_id     = '{wave}'
                 AND o2.question_id = rg.question_id
                 AND o2.option_id   = rg.value
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{group_by}'
                LIMIT 1
            )"""


def _city_buckets(city_filter):
    """Define los buckets de columna al agrupar por ciudad.

    Sin filtro de ciudad: el set curado completo (las 11 ciudades del AMM + los 4
    agregados AMM/Periferia/Resto NL/Nuevo León). Con filtro: una columna por
    municipio filtrado (sin agregados), en el orden canónico de metadata.
    Devuelve `(label_to_city_ids, city_bucket_labels)`."""
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
    return label_to_city_ids, city_bucket_labels


@app.post("/api/query")
def run_query(req: QueryRequest):
    """
    Endpoint central del motor. Arma y ejecuta el SQL contra DuckDB.

    group_by="answer" (forma plana):
      - Preguntas categóricas: un renglón por opción con conteo + porcentaje.
      - Preguntas numéricas: un renglón por valor distinto con conteo + %
        (distribución de frecuencias; centinelas 7777/8888/9999 excluidos).

    group_by != "answer" (forma pivote): dos tablas — conteos y porcentajes —
    cada una con fila/columna Total. Las numéricas agregan una fila "Promedio"
    (media ponderada) a la tabla de conteos.

    group_by="year" (pivote entre años): compara el concepto de la pregunta
    seleccionada a través de las olas donde existe (ver `_year_comparison`).
    """
    if req.group_by in ("year", "año", "anio"):
        return _year_comparison(req)

    conn = get_conn()
    try:
        # Resolver + validar la ola. `wave` viene de un conjunto conocido, así que
        # es seguro interpolarla en los strings SQL junto con question_id.
        wave = req.wave_id or _default_wave()
        if wave not in _wave_ids():
            raise HTTPException(status_code=400, detail=f"Unknown wave_id: {wave}")

        # Tipo de pregunta (dentro de esta ola)
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

        # Base (universo) de la consulta. Centinelas filtrados sólo en numéricas:
        # las categóricas guardan la respuesta en `option_id` y dejan `a.value`
        # NULL, así que aplicar el filtro de centinelas ahí tiraría todas las filas
        # (NULL NOT IN (...) es NULL/falsy).
        num_sentinels = (
            _numeric_sentinel_sql(wave, req.question_id) if q_type == "numerica" else ""
        )
        sentinel_filter = (
            f"AND a.value NOT IN ({num_sentinels})" if q_type == "numerica" else ""
        )
        base_fw = _base_from_where(
            wave, req.question_id, join_clauses, initial_filter, city_where,
            extra_where=sentinel_filter,
        )
        if weighted:
            # Suma factor_cvnl sobre (respondiente, factor) distintos.
            total_sql = f"""
                SELECT ROUND(SUM(factor_cvnl))::BIGINT FROM (
                    SELECT DISTINCT a.respondent_id, r.factor_cvnl
                    {base_fw}
                )
            """
        else:
            total_sql = f"SELECT COUNT(DISTINCT a.respondent_id) {base_fw}"
        total_respondents = (conn.execute(total_sql).fetchone() or (0,))[0]

        # ── group_by="answer" → flat shape (no pivot) ─────────────────────
        if req.group_by == "answer":
            if q_type == "numerica":
                # Distribución de frecuencias: un renglón por valor numérico
                # distinto (el valor ES la respuesta, sin id/etiqueta aparte) con
                # conteo ponderado + %. Centinelas excluidos (ya en `base_fw`).
                sql = f"""
                    WITH base AS (
                        SELECT a.value AS valor, {count_expr} AS cnt
                        {base_fw}
                        GROUP BY a.value
                    ),
                    totals AS (SELECT SUM(cnt) AS total FROM base)
                    SELECT b.valor,
                           ROUND(b.cnt)::BIGINT              AS total,
                           ROUND(b.cnt * 100.0 / t.total, 1) AS pct
                    FROM base b CROSS JOIN totals t
                    ORDER BY b.valor ASC
                """
                rows = conn.execute(sql).fetchall()
                col_labels = ["Respuesta", "Respuestas", "%"]
            else:
                # LEFT JOIN (no INNER) al catálogo: las respuestas cuyo option_id
                # falta en `options` igual deben CONTARSE — tirarlas encoge la base
                # e infla todos los porcentajes (Capa A). Los códigos sin catálogo
                # afloran como "Código N" hasta reparar el catálogo (Capa B).
                cat_fw = _base_from_where(
                    wave, req.question_id, join_clauses, initial_filter,
                    city_where, with_options=True,
                )
                sql = f"""
                    WITH base AS (
                        SELECT a.option_id AS id_respuesta,
                               COALESCE(o.option_label, 'Código ' || a.option_id::TEXT) AS respuesta,
                               {count_expr} AS cnt
                        {cat_fw}
                        GROUP BY id_respuesta, respuesta
                    ),
                    totals AS (SELECT SUM(cnt) AS total FROM base)
                    SELECT b.id_respuesta,
                           b.respuesta,
                           ROUND(b.cnt)::BIGINT              AS total,
                           ROUND(b.cnt * 100.0 / t.total, 1) AS pct
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
                "wave_id": wave,
                "filters_applied": req.filters,
                "group_by": req.group_by,
                "total_respondents": total_respondents,
                "column_labels": col_labels,
                "rows": [list(r) for r in rows],
                "sql": sql.strip(),
            }

        # ── pivot mode (group_by != "answer") ─────────────────────────────
        group_expr = _group_expr_sql(req.group_by, wave)

        # Totales por grupo INCLUYENDO centinelas — son los denominadores de
        # columna del % y la fila "Total" de la tabla de conteos.
        per_group_total_sql = f"""
            SELECT {group_expr} AS grupo, {count_int} AS total
            {_base_from_where(wave, req.question_id, join_clauses, initial_filter, city_where)}
            GROUP BY grupo
            HAVING grupo IS NOT NULL
        """
        group_totals_raw = {
            row[0]: row[1] for row in conn.execute(per_group_total_sql).fetchall()
        }
        grand_total_incl = sum(group_totals_raw.values())

        # Para agrupaciones no-ciudad ya aplicamos aquí el orden canónico de
        # metadata. Para `city_id` conservamos los ids crudos por ahora; el
        # cell_map / stats se remapean a los buckets de metadata (11 ciudades AMM
        # + 4 agregados) más abajo.
        if req.group_by == "city_id":
            label_to_city_ids, city_bucket_labels = _city_buckets(city_filter)
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
            # Distribución de frecuencias por grupo (todos los valores no nulos;
            # los centinelas se excluyen sólo del promedio, no de la distribución).
            freq_sql = f"""
                SELECT a.value AS id_respuesta, {group_expr} AS grupo, {count_int} AS cnt
                {_base_from_where(wave, req.question_id, join_clauses, initial_filter, city_where, extra_where="AND a.value IS NOT NULL")}
                GROUP BY id_respuesta, grupo
                ORDER BY id_respuesta
            """
            freq_rows = conn.execute(freq_sql).fetchall()

            # Promedio ponderado por grupo (centinelas excluidos). El mismo
            # FROM/WHERE sirve para el promedio global.
            stats_fw = _base_from_where(
                wave, req.question_id, join_clauses, initial_filter, city_where,
                extra_where=sentinel_filter,
            )
            stats_sql = f"""
                SELECT {group_expr} AS grupo, {avg_expr} AS promedio
                {stats_fw}
                GROUP BY grupo
                HAVING grupo IS NOT NULL
            """
            stats_per_group = {
                row[0]: list(row[1:]) for row in conn.execute(stats_sql).fetchall()
            }

            overall_stats = list(
                conn.execute(f"SELECT {avg_expr} {stats_fw}").fetchone() or [None]
            )

            distinct_values = sorted(
                {r[0] for r in freq_rows}, key=lambda v: (v is None, v)
            )
            cell_map = {(r[0], r[1]): r[2] for r in freq_rows}

            # Collapse raw city_ids into the curated metadata buckets (11 AMM
            # cities + AMM/Periferia/Resto NL/Nuevo León aggregates). Stats
            # for the four aggregates are recomputed via SQL because they
            # don't compose from per-city pre-aggregated stats.
            if req.group_by == "city_id":
                cell_map, group_totals_raw = _collapse_city_cells(
                    distinct_values, cell_map, group_totals_raw,
                    city_bucket_labels, label_to_city_ids,
                )
                grand_total_incl = group_totals_raw.get("Nuevo León", grand_total_incl)
                group_keys = list(city_bucket_labels)
                group_labels = list(group_keys)

                # Stats por bucket: un bucket de una sola ciudad reutiliza el stat
                # ya calculado; un agregado (>1 ciudad) se recalcula por SQL porque
                # los promedios no se componen desde los stats por ciudad.
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
                    agg_fw = _base_from_where(
                        wave, req.question_id, join_clauses, initial_filter,
                        city_where,
                        extra_where=f"{sentinel_filter} AND r.city_id IN ({in_clause})",
                    )
                    agg_row = conn.execute(f"SELECT {avg_expr} {agg_fw}").fetchone()
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
                return lbl if lbl is not None else (str(value) if value is not None else "")

            counts_columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
            pct_columns = list(counts_columns)

            counts_rows, pct_rows = _pivot_count_pct_rows(
                distinct_values, label_for, cell_map, group_keys,
                group_totals_raw, grand_total_incl,
                is_city=req.group_by == "city_id",
            )

            # Fila de promedio (sólo en la tabla de conteos — no es un porcentaje).
            promedio_row = ["Promedio", ""]
            for g in group_keys:
                v = stats_per_group.get(g, [None])[0]
                promedio_row.append(v if v is not None else "")
            ov = overall_stats[0]
            promedio_row.append(ov if ov is not None else "")
            counts_rows.append(promedio_row)

            return {
                "format": "pivot",
                "question": {
                    "q_id": req.question_id,
                    "q_text": q_text,
                    "q_type": q_type,
                },
                "wave_id": wave,
                "filters_applied": req.filters,
                "group_by": req.group_by,
                "total_respondents": total_respondents,
                "counts": {"columns": counts_columns, "rows": counts_rows},
                "percentages": {"columns": pct_columns, "rows": pct_rows},
                "sql": freq_sql.strip(),
            }

        # categórica + pivot (group_by != "answer"). LEFT JOIN al catálogo (Capa A).
        freq_sql = f"""
            SELECT a.option_id AS id_respuesta,
                   o.option_label AS respuesta,
                   {group_expr} AS grupo,
                   {count_int} AS cnt
            {_base_from_where(wave, req.question_id, join_clauses, initial_filter, city_where, with_options=True)}
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
            cell_map, group_totals_raw = _collapse_city_cells(
                option_keys, cell_map, group_totals_raw,
                city_bucket_labels, label_to_city_ids,
            )
            grand_total_incl = group_totals_raw.get("Nuevo León", grand_total_incl)
            group_keys = list(city_bucket_labels)
            group_labels = list(group_keys)

        counts_columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
        pct_columns = list(counts_columns)

        def label_for_opt(opt_id):
            lbl = opt_lookup.get(opt_id)
            if lbl is not None:
                return lbl
            return f"Código {opt_id}" if opt_id is not None else ""

        counts_rows, pct_rows = _pivot_count_pct_rows(
            option_keys, label_for_opt, cell_map, group_keys,
            group_totals_raw, grand_total_incl,
            is_city=req.group_by == "city_id",
        )

        return {
            "format": "pivot",
            "question": {"q_id": req.question_id, "q_text": q_text, "q_type": q_type},
            "wave_id": wave,
            "filters_applied": req.filters,
            "group_by": req.group_by,
            "total_respondents": total_respondents,
            "counts": {"columns": counts_columns, "rows": counts_rows},
            "percentages": {"columns": pct_columns, "rows": pct_rows},
            "sql": freq_sql.strip(),
        }

    except HTTPException:
        raise
    except Exception:
        # No filtrar detalles internos al cliente, pero dejar rastro en el log
        # (Render captura stdout/stderr). Incluye la pregunta y el group_by para
        # poder reproducir la consulta que falló.
        log.exception(
            "run_query falló: q=%s group_by=%s wave=%s",
            req.question_id, req.group_by, req.wave_id,
        )
        raise HTTPException(status_code=500, detail="Error interno.")
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


# Serve the built Vite frontend (frontend/dist) at the root path.
# Must run AFTER all /api/* routes are registered
STATIC_DIR = os.getenv("STATIC_DIR", "../frontend/dist")
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
