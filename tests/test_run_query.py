"""Tests for the core query engine (main.run_query).

Covers the four shapes (flat/pivot × numeric/categorical) plus the behaviours
that previously broke: numeric frequency breakdown, single 'Promedio' stat row,
city-filter column narrowing, recode grouping, weighting, and sentinel handling.
"""

import pytest

import main
from main import run_query, QueryRequest

SENTINELS = {7777, 8888, 9999}


def _pct_sum(rows, col=-1):
    return sum(r[col] for r in rows if isinstance(r[col], (int, float)))


# ── flat (group_by = "answer") ──────────────────────────────────────────────
def test_flat_numeric_is_frequency_breakdown(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="answer"))
    assert r["format"] == "flat"
    assert r["column_labels"] == ["Respuesta", "Respuestas", "%"]
    assert len(r["rows"]) >= 1
    # percentages add up to ~100 (allowing per-row rounding)
    tol = max(1.0, 0.06 * len(r["rows"]))
    assert _pct_sum(r["rows"]) == pytest.approx(100, abs=tol)


def test_flat_numeric_excludes_sentinels(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="answer"))
    values = {int(row[0]) for row in r["rows"]}
    assert values.isdisjoint(SENTINELS)


def test_flat_categorical_shape(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="answer"))
    assert r["format"] == "flat"
    assert r["column_labels"] == ["id_respuesta", "Respuesta", "Total", "%"]
    assert len(r["rows"]) >= 1
    tol = max(1.0, 0.06 * len(r["rows"]))
    assert _pct_sum(r["rows"]) == pytest.approx(100, abs=tol)


# ── Capa A: catálogo incompleto NO debe tirar respuestas (base intacta) ──────
def test_flat_categorical_counts_uncatalogued_options():
    """Regresión Capa A: un option_id ausente del catálogo `options` debe
    seguir contándose (LEFT JOIN + 'Código N'), no caerse en silencio — si se
    cae, la base se encoge y todos los % se inflan (la clase de bug de p128).
    p8/2021 tenía el catálogo roto (una sola fila basura 1234567), así que
    antes del fix devolvía base 0; ahora recupera sus 7 opciones reales."""
    wave, qid = "2021", "p8"
    r = run_query(
        QueryRequest(question_id=qid, group_by="answer", wave_id=wave, initial_only=True)
    )
    base = sum(row[2] for row in r["rows"] if isinstance(row[2], (int, float)))

    expected = main.get_conn().execute(
        """
        SELECT ROUND(SUM(r.factor_cvnl))::BIGINT
        FROM answers a
        JOIN responses r
          ON r.respondent_id = a.respondent_id AND r.wave_id = a.wave_id
        WHERE a.wave_id = ? AND a.question_id = ? AND a.option_id IS NOT NULL
          AND r.is_initial_respondent = 1
        """,
        [wave, qid],
    ).fetchone()[0]

    assert base > 0
    # nada se cayó: la base del flat = total ponderado crudo de answers
    assert base == pytest.approx(expected, abs=len(r["rows"]))
    # las opciones sin etiqueta se muestran como "Código N", no desaparecen
    assert any(str(row[1]).startswith("Código ") for row in r["rows"])


# ── pivot (group_by != "answer") ────────────────────────────────────────────
def test_pivot_by_attribute(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="sexo"))
    assert r["format"] == "pivot"
    cols = r["counts"]["columns"]
    assert cols[0] == "id_respuesta" and cols[-1] == "Total"
    # counts and percentages share the same column layout
    assert r["percentages"]["columns"] == cols
    # there is a Total row in both tables
    assert any(row[0] == "Total" for row in r["counts"]["rows"])
    assert any(row[0] == "Total" for row in r["percentages"]["rows"])


def test_pivot_percentage_total_row_is_100(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="sexo"))
    total_row = next(row for row in r["percentages"]["rows"] if row[0] == "Total")
    for cell in total_row[2:]:
        if isinstance(cell, (int, float)):
            assert cell == pytest.approx(100, abs=0.5)


# ── city grouping ───────────────────────────────────────────────────────────
def test_pivot_city_without_filter_has_aggregates(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="city_id"))
    group_cols = r["counts"]["columns"][2:-1]
    for agg in ("AMM", "Periferia", "Resto NL", "Nuevo León"):
        assert agg in group_cols
    assert "Monterrey" in group_cols


def test_pivot_city_with_filter_shows_only_filtered(numeric_qid, city_ids):
    r = run_query(
        QueryRequest(
            question_id=numeric_qid,
            filters=[{"attribute": "city_id", "value": list(city_ids.values())}],
            group_by="city_id",
        )
    )
    group_cols = set(r["counts"]["columns"][2:-1])
    assert group_cols == {"Monterrey", "Apodaca"}
    # no aggregate buckets when filtering specific municipalities
    assert group_cols.isdisjoint({"AMM", "Periferia", "Resto NL", "Nuevo León"})


# ── numeric pivot stat rows ─────────────────────────────────────────────────
def test_numeric_pivot_has_only_promedio_stat(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="sexo"))
    labels = {row[0] for row in r["counts"]["rows"]}
    assert "Promedio" in labels
    assert labels.isdisjoint({"Mínimo", "Máximo", "Desv. estándar"})


# ── recode grouping ─────────────────────────────────────────────────────────
def test_recode_group_by(numeric_qid):
    r = run_query(
        QueryRequest(question_id=numeric_qid, group_by="tipo_trabajo_remunerado")
    )
    assert r["format"] == "pivot"
    group_cols = r["counts"]["columns"][2:-1]
    assert "Trabajo remunerado" in group_cols


# ── weighting & filters ─────────────────────────────────────────────────────
def test_weighting_projects_to_population(categorical_qid):
    weighted = run_query(
        QueryRequest(question_id=categorical_qid, initial_only=True)
    )["total_respondents"]
    raw = run_query(
        QueryRequest(question_id=categorical_qid, initial_only=False)
    )["total_respondents"]
    # population projection (factor_cvnl) is far larger than the raw sample
    assert weighted > raw > 0


def test_filter_reduces_total(categorical_qid):
    full = run_query(QueryRequest(question_id=categorical_qid))["total_respondents"]
    filtered = run_query(
        QueryRequest(
            question_id=categorical_qid,
            filters=[{"attribute": "sexo", "value": [1]}],
        )
    )["total_respondents"]
    assert 0 < filtered <= full


# ── error handling ──────────────────────────────────────────────────────────
def test_unknown_question_raises_404():
    with pytest.raises(main.HTTPException) as exc:
        run_query(QueryRequest(question_id="__does_not_exist__"))
    assert exc.value.status_code == 404


# ── SQL-injection guard (allow-list validation) ─────────────────────────────
def test_unknown_group_by_raises_400(categorical_qid):
    with pytest.raises(main.HTTPException) as exc:
        run_query(QueryRequest(question_id=categorical_qid, group_by="sexo'; DROP--"))
    assert exc.value.status_code == 400


def test_unknown_filter_attribute_raises_400(categorical_qid):
    with pytest.raises(main.HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id=categorical_qid,
                filters=[{"attribute": "sexo' OR '1'='1", "value": [1]}],
            )
        )
    assert exc.value.status_code == 400
