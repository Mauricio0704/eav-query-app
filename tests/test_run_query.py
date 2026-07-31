"""Tests for the core query engine (main.run_query).

Covers the four shapes (flat/pivot × numeric/categorical) plus the behaviours
that previously broke: numeric frequency breakdown, single 'Promedio' stat row,
city-filter column narrowing, recode grouping, weighting, and sentinel handling.
"""

import pytest

import main
from main import run_query, QueryRequest, _csv_fill_empty

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
def _flat_base(r):
    return sum(row[2] for row in r["rows"] if isinstance(row[2], (int, float)))


def _raw_weighted_total(wave, qid):
    return main.get_conn().execute(
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


def test_flat_categorical_base_equals_raw_total(categorical_qid):
    """Regresión Capa A (invariante que sobrevive a Capa B): la base del flat
    categórico = total ponderado crudo de `answers`. El LEFT JOIN no tira nada;
    si volviera a INNER JOIN, las respuestas sin catálogo se caerían, la base se
    encogería y TODOS los % se inflarían (la clase de bug de p128/2021)."""
    r = run_query(QueryRequest(question_id=categorical_qid, initial_only=True))
    base = _flat_base(r)
    assert base > 0
    assert base == pytest.approx(_raw_weighted_total("2025", categorical_qid),
                                 abs=len(r["rows"]))


def test_flat_categorical_uncatalogued_surfaces_as_codigo():
    """Capa A: donde el catálogo aún tiene huecos (olas sin Capa B), el código
    sin etiqueta aflora como 'Código N' y se cuenta — no desaparece. Busca una
    pregunta con hueco dinámicamente; si ya no queda ninguna (Capa B completa en
    todas las olas), se omite."""
    hit = main.get_conn().execute(
        """
        SELECT a.wave_id, a.question_id
        FROM answers a
        JOIN responses r ON r.wave_id=a.wave_id AND r.respondent_id=a.respondent_id
                        AND r.is_initial_respondent=1
        JOIN questions q ON q.wave_id=a.wave_id AND q.q_id=a.question_id AND q.q_type='categorica'
        LEFT JOIN options o
          ON o.wave_id=a.wave_id AND o.question_id=a.question_id AND o.option_id=a.option_id
        WHERE a.option_id IS NOT NULL AND o.option_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if not hit:
        pytest.skip("no quedan huecos de catálogo en ninguna ola (Capa B completa)")
    wave, qid = hit
    r = run_query(
        QueryRequest(question_id=qid, group_by="answer", wave_id=wave, initial_only=True)
    )
    assert _flat_base(r) == pytest.approx(_raw_weighted_total(wave, qid), abs=len(r["rows"]))
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


# ── cross-tab: group_by = another survey question ───────────────────────────
def _cross_qids():
    """(A, B): a small categorical question A and a categorical breakdown B,
    both in the default wave, A != B. Prefers a binary Sí/No B for a clean table."""
    qs = main.list_questions()
    cats = [q for q in qs if q["q_type"] != "numerica" and q["options"]]
    binary = next(
        (q for q in cats if 2 <= len(q["options"]) <= 4 and len(q["options"]) <= 4),
        cats[0],
    )
    a = next(q for q in cats if q["q_id"] != binary["q_id"])
    return a["q_id"], binary["q_id"]


def test_cross_tab_columns_are_breakdown_options():
    """group_by=<q_id> pivots the main question by another question's options:
    columns come from B's catalog (in option_id order), rows from A."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    assert r["format"] == "pivot"
    b_labels = {o["label"] for o in next(
        q for q in main.list_questions() if q["q_id"] == b)["options"]}
    group_cols = set(r["counts"]["columns"][2:-1])
    # every column label is one of B's option labels (Código N fallbacks aside)
    assert group_cols <= b_labels | {c for c in group_cols if c.startswith("Código ")}
    assert group_cols & b_labels  # at least some real B options present


def test_cross_tab_n_matches_table_base():
    """The reported n for a cross-tab is the A∩B base (respondents who answered
    BOTH questions), so the header equals the table's Total row — not the larger
    A-only base, which would overstate n when the breakdown has item non-response."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    table_total = next(row for row in r["counts"]["rows"] if row[0] == "Total")[-1]
    assert r["total_respondents"] == table_total


def test_cross_tab_each_column_sums_to_100():
    """Percentages are column-normalised: within each B category the distribution
    of A adds to ~100 (the crosstab reads 'within this B group, how A splits')."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    cols = r["percentages"]["columns"]
    data = [row for row in r["percentages"]["rows"] if row[0] != "Total"]
    for ci in range(2, len(cols) - 1):  # skip id/label cols and the Total col
        s = sum(row[ci] for row in data if isinstance(row[ci], (int, float)))
        if s:  # non-empty column
            assert s == pytest.approx(100, abs=max(1.0, 0.06 * len(data)))


def test_cross_tab_numeric_main_has_promedio_row():
    """A numeric main question crossed by a categorical B still gets its weighted
    Promedio row (the group expression is independent of the main q_type)."""
    numeric = next(
        q["q_id"] for q in main.list_questions() if q["q_type"] == "numerica")
    _, b = _cross_qids()
    r = run_query(QueryRequest(question_id=numeric, group_by=b))
    assert r["format"] == "pivot"
    assert "Promedio" in {row[0] for row in r["counts"]["rows"]}


def test_cross_tab_self_raises_400():
    _, b = _cross_qids()
    with pytest.raises(main.HTTPException) as exc:
        run_query(QueryRequest(question_id=b, group_by=b))
    assert exc.value.status_code == 400


def test_cross_tab_numeric_breakdown_raises_400():
    """Numeric questions are not allowed as the breakdown variable (v1): they'd
    explode into dozens of columns. Rejected with a clear message, not 'Unknown'."""
    numeric = next(
        q["q_id"] for q in main.list_questions() if q["q_type"] == "numerica")
    a, _ = _cross_qids()
    with pytest.raises(main.HTTPException) as exc:
        run_query(QueryRequest(question_id=a, group_by=numeric))
    assert exc.value.status_code == 400
    assert "numérica" in exc.value.detail


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


# ── year comparison: transparencia del crudo por año ────────────────────────
def test_year_option_map_exposes_raw_per_year():
    """La comparación por año alinea por opción canónica, pero `year_option_map`
    conserva el código y etiqueta CRUDOS de cada ola (transparencia). sexo se
    recodifica entre olas (2022 1/2 vs 2025 0/1) y se relabela
    (Masculino/Hombre), así que debe haber al menos una opción con differs=True
    y con option_id crudo no estable entre años."""
    r = run_query(QueryRequest(question_id="cp2", group_by="year"))
    # La vista Año ya no incluye id_respuesta: columnas = [Respuesta, ...años].
    assert r["counts"]["columns"][0] == "Respuesta"
    years = r["counts"]["columns"][1:]
    yom = r.get("year_option_map")
    assert yom, "comparación categórica por año debe incluir year_option_map"
    # alineado 1:1 y en orden con los renglones de datos; la etiqueta es col 0
    data_rows = [row for row in r["counts"]["rows"] if row[0] != "Total"]
    assert len(yom) == len(data_rows)
    for entry, row in zip(yom, data_rows):
        assert entry["label"] == row[0]
        assert set(entry["years"]) == set(years)
    # sexo cambia código Y etiqueta entre años → la transparencia lo refleja
    assert any(e["differs"] for e in yom)
    hombre = next(e for e in yom if e["label"] == "Hombre")
    raw_ids = {v["option_id"] for v in hombre["years"].values() if v}
    assert len(raw_ids) > 1  # el código crudo NO es estable entre años


def test_year_sql_lists_one_query_per_wave():
    """La vista Año no es un solo statement: expone el SQL de cada ola con un
    encabezado que lo aclara, en vez de dejar el visor sin SQL. Debe incluir un
    bloque por año miembro del concepto."""
    r = run_query(QueryRequest(question_id="cp2", group_by="year"))
    sql = r.get("sql")
    assert sql and "NO es una sola consulta" in sql
    years = r["counts"]["columns"][1:]
    for w in years:
        assert f"══ {w} ·" in sql  # un bloque rotulado por ola


def test_year_numeric_empty_base_does_not_crash():
    """Una pregunta-matriz (encabezado de batería) tiene concept_id pero 0 answers
    en sus olas, así que `total_respondents` es None por año. La comparación
    numérica por año no debe reventar sumando None; devuelve una tabla vacía
    coherente con base 0. (Regresión: TypeError int += None en _year_comparison.)"""
    r = run_query(QueryRequest(question_id="p95", group_by="year", wave_id="2021"))
    assert r["format"] == "pivot"
    assert r["total_respondents"] == 0
    assert all(b["base"] == 0 for b in r["year_bases"])
    base_row = next(row for row in r["counts"]["rows"] if row[0] == "Base (ponderada)")
    assert all(cell == 0 for cell in base_row[1:])


# ── CSV: rellenar celdas sin respondientes con 0 ────────────────────────────
def test_csv_fill_empty_zeroes_data_but_keeps_labels_and_stats():
    """En el CSV, un grupo sin respondientes exporta 0 (no celda vacía). Pero
    las columnas de etiqueta iniciales y la fila de estadístico (Promedio) NO se
    tocan: un 0 ahí sería una etiqueta rota o un promedio inventado."""
    rows = [
        [11.0, "11.0", "", 146, ""],          # data: vacíos → 0
        ["Total", "", 200, 146, ""],           # total: vacíos → 0
        ["Promedio", "", "", 98.85, ""],       # estadístico: vacíos INTACTOS
    ]
    out = _csv_fill_empty(rows, label_cols=2)
    assert out[0] == [11.0, "11.0", 0, 146, 0]
    assert out[1] == ["Total", "", 200, 146, 0]
    assert out[2] == ["Promedio", "", "", 98.85, ""]  # sin cambios


def test_csv_fill_empty_year_view_uses_one_label_col():
    """La vista Año tiene 1 sola columna de etiqueta (Respuesta)."""
    rows = [["Hombre", "", 51.3], ["Promedio (media)", "", ""]]
    out = _csv_fill_empty(rows, label_cols=1)
    assert out[0] == ["Hombre", 0, 51.3]
    assert out[1] == ["Promedio (media)", "", ""]  # estadístico intacto


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
