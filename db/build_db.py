#!/usr/bin/env python3
"""
Construye la base de datos multi-año `data/encuesta_multianual.duckdb`.

Cada ola se carga desde su propia fuente y se inserta con su `wave_id`:

  * 2025 — desde la BD original `data/encuesta.duckdb` (una sola ola, READ_ONLY,
    queda INTACTA).
  * 2024 — desde los CSV en `db/waves/2024/`, producidos por el ETL
    `encuesta-asi-vamos-etl` (formato ancho → largo). Ver db/README.md.

`answers` se ordena FÍSICAMENTE por (question_id, option_id, respondent_id)
dentro de cada ola; como cada ola se inserta de corrido, el archivo queda
agrupado por (wave_id, question_id) → DuckDB poda por zone-maps.

Es idempotente: reconstruye la BD nueva desde cero en cada corrida (write-once).

Uso (desde la raíz del repo o desde db/):
    .venv/bin/python db/build_db.py
"""

import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC_2025 = ROOT / "data" / "encuesta.duckdb"               # original (intacta)
DST = ROOT / "data" / "encuesta_multianual.duckdb"          # nueva (multi-año)
SCHEMA = HERE / "schema.sql"
WAVES_DIR = HERE / "waves"                                  # CSVs de olas extra

DATA_TABLES = ["responses", "questions", "options", "respondent_attributes", "answers"]


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------
def _run_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Ejecuta el esquema completo (DuckDB corre múltiples sentencias)."""
    con.execute(SCHEMA.read_text())


# ---------------------------------------------------------------------------
# Ola 2025 — desde la BD original de una sola ola
# ---------------------------------------------------------------------------
def load_wave_2025(con: duckdb.DuckDBPyConnection) -> None:
    wave = "2025"
    print(f"\n▶ Cargando ola '{wave}' desde {SRC_2025.name} ...")
    con.execute(
        """
        INSERT INTO waves (wave_id, year, label, n_respondents)
        SELECT '2025', 2025, 'Encuesta 2025', (SELECT COUNT(*) FROM src.responses)
        """
    )
    con.execute(
        f"""
        INSERT INTO responses
        SELECT '{wave}', respondent_id, is_initial_respondent, nombre, factor_cvnl, city_id
        FROM src.responses ORDER BY respondent_id
        """
    )
    con.execute(
        f"""
        INSERT INTO questions
        SELECT '{wave}', q_id, q_text, q_section, q_type, q_notes, q_info, q_block, NULL
        FROM src.questions ORDER BY q_id
        """
    )
    con.execute(
        f"""
        INSERT INTO options
        SELECT '{wave}', question_id, option_id, option_label, NULL
        FROM src.options ORDER BY question_id, option_id
        """
    )
    con.execute(
        f"""
        INSERT INTO respondent_attributes
        SELECT '{wave}', respondent_id, question_id, attribute, value
        FROM src.respondent_attributes ORDER BY respondent_id, attribute
        """
    )
    con.execute(
        f"""
        INSERT INTO answers
        SELECT '{wave}', respondent_id, question_id, option_id, value
        FROM src.answers
        ORDER BY question_id, option_id NULLS LAST, respondent_id
        """
    )


# ---------------------------------------------------------------------------
# Olas en formato ancho — desde CSVs producidos por el ETL (db/waves/<año>/)
# ---------------------------------------------------------------------------
def load_wave_csv(con: duckdb.DuckDBPyConnection, wave: str, year: int, label: str) -> None:
    csv_dir = WAVES_DIR / wave
    print(f"\n▶ Cargando ola '{wave}' desde {csv_dir.relative_to(ROOT)}/ ...")

    def csv(name: str) -> str:
        p = csv_dir / f"{name}.csv"
        if not p.exists():
            sys.exit(f"ERROR: falta el CSV de la ola {wave}: {p}")
        return f"read_csv_auto('{p}', header=true)"

    con.execute(
        f"""
        INSERT INTO waves (wave_id, year, label, n_respondents)
        SELECT '{wave}', {year}, '{label}', (SELECT COUNT(*) FROM {csv('responses')})
        """
    )
    con.execute(
        f"""
        INSERT INTO responses
        SELECT '{wave}', respondent_id,
               CASE WHEN is_initial_respondent THEN 1 ELSE 0 END,
               nombre, factor_cvnl, city_id
        FROM {csv('responses')} ORDER BY respondent_id
        """
    )
    con.execute(
        f"""
        INSERT INTO questions
        SELECT '{wave}', q_id, q_text, q_section, q_type, q_notes, NULL, NULL, NULL
        FROM {csv('questions')} ORDER BY q_id
        """
    )
    con.execute(
        f"""
        INSERT INTO options
        SELECT '{wave}', question_id, option_id, option_label, NULL
        FROM {csv('options')} ORDER BY question_id, option_id
        """
    )
    con.execute(
        f"""
        INSERT INTO respondent_attributes
        SELECT '{wave}', respondent_id, question_id, attribute, value
        FROM {csv('respondent_attributes')} ORDER BY respondent_id, attribute
        """
    )
    con.execute(
        f"""
        INSERT INTO answers
        SELECT '{wave}', respondent_id, question_id, option_id, value
        FROM {csv('answers')}
        ORDER BY question_id, option_id NULLS LAST, respondent_id
        """
    )


# ---------------------------------------------------------------------------
# Conceptos (Fase 2) — armonización entre años
# ---------------------------------------------------------------------------
def load_concepts(con: duckdb.DuckDBPyConnection) -> None:
    cdir = HERE / "concepts"
    cfile, mfile = cdir / "concepts.csv", cdir / "concept_members.csv"
    if not cfile.exists() or not mfile.exists():
        print("\n(∅ sin conceptos: no existe db/concepts/*.csv — se omite Fase 2)")
        return
    print(f"\n▶ Cargando conceptos desde {cdir.relative_to(ROOT)}/ ...")

    ofile = cdir / "concept_options.csv"
    omfile = cdir / "concept_option_map.csv"

    con.execute(
        f"""
        INSERT INTO concepts (concept_id, label, q_type, comparable)
        SELECT concept_id, label, q_type, comparable
        FROM read_csv_auto('{cfile}', header=true)
        """
    )
    # Enlazar cada pregunta a su concepto vía (wave_id, q_id).
    con.execute(
        f"""
        UPDATE questions q
        SET concept_id = m.concept_id
        FROM read_csv_auto('{mfile}', header=true) m
        WHERE q.wave_id = m.wave_id AND q.q_id = m.q_id
        """
    )
    # Catálogo de opciones canónicas.
    if ofile.exists():
        con.execute(
            f"""
            INSERT INTO concept_options (concept_id, concept_option_id, label, sort_order)
            SELECT concept_id, concept_option_id, label, sort_order
            FROM read_csv_auto('{ofile}', header=true)
            """
        )
    # Mapear cada opción de cada ola a su opción canónica (identidad + recodes).
    if omfile.exists():
        con.execute(
            f"""
            UPDATE options o
            SET concept_option_id = m.concept_option_id
            FROM read_csv_auto('{omfile}', header=true) m
            WHERE o.wave_id = m.wave_id AND o.question_id = m.q_id
              AND o.option_id = m.option_id
            """
        )

    n_concepts = con.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
    n_linked = con.execute(
        "SELECT COUNT(*) FROM questions WHERE concept_id IS NOT NULL"
    ).fetchone()[0]
    n_copts = con.execute("SELECT COUNT(*) FROM concept_options").fetchone()[0]
    print(f"  conceptos={n_concepts}  preguntas enlazadas={n_linked}  opciones canónicas={n_copts}")


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def _validate(con: duckdb.DuckDBPyConnection) -> None:
    print("\nValidación:")
    ok = True

    # Conteo de olas
    waves = [r[0] for r in con.execute("SELECT wave_id FROM waves ORDER BY wave_id").fetchall()]
    print(f"  olas cargadas: {waves}")

    for w in waves:
        # Unicidad de (wave, respondent, question) en answers (no hay PK).
        dups = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT respondent_id, question_id, COUNT(*) n
                FROM answers WHERE wave_id = ? GROUP BY 1, 2 HAVING n > 1
            )
            """,
            [w],
        ).fetchone()[0]
        # Integridad EAV: exactamente uno de (option_id, value).
        bad = con.execute(
            """
            SELECT COUNT(*) FROM answers WHERE wave_id = ?
            AND ((option_id IS NULL AND value IS NULL)
                 OR (option_id IS NOT NULL AND value IS NOT NULL))
            """,
            [w],
        ).fetchone()[0]
        n_ans = con.execute("SELECT COUNT(*) FROM answers WHERE wave_id = ?", [w]).fetchone()[0]
        n_resp = con.execute("SELECT COUNT(*) FROM responses WHERE wave_id = ?", [w]).fetchone()[0]
        print(
            f"  [{w}] responses={n_resp:>6,}  answers={n_ans:>9,}  "
            f"dups={dups}  eav_malformadas={bad}  "
            f"{'OK' if dups == 0 and bad == 0 else 'FALLA'}"
        )
        ok = ok and dups == 0 and bad == 0

    if not ok:
        con.close()
        sys.exit("ERROR: la validación falló.")


# ---------------------------------------------------------------------------
def main() -> None:
    if not SRC_2025.exists():
        sys.exit(f"ERROR: no existe la BD origen 2025: {SRC_2025}")
    if not SCHEMA.exists():
        sys.exit(f"ERROR: no existe el esquema: {SCHEMA}")

    if DST.exists():
        DST.unlink()  # reconstrucción limpia

    con = duckdb.connect(str(DST))
    try:
        _run_schema(con)
        con.execute(f"ATTACH '{SRC_2025}' AS src (READ_ONLY)")
        load_wave_2025(con)
        con.execute("DETACH src")

        load_wave_csv(con, "2024", 2024, "Encuesta 2024")
        load_wave_csv(con, "2023", 2023, "Encuesta 2023")
        load_wave_csv(con, "2022", 2022, "Encuesta 2022")
        load_wave_csv(con, "2021", 2021, "Encuesta 2021")

        load_concepts(con)

        _validate(con)
    finally:
        con.close()

    size_mb = DST.stat().st_size / 1_048_576
    print(f"\n✓ BD multi-año construida: {DST}  ({size_mb:.1f} MB)")
    print(f"  Original intacta:        {SRC_2025}")


if __name__ == "__main__":
    main()
