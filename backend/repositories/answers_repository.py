"""Consultas sobre `answers` que no pasan por el motor de consultas."""


def fetch_out_of_range_sentinel_values(
    conn, suspect_codes: tuple[int, ...]
) -> list[tuple]:
    """(wave_id, question_id, value) de cada código sospechoso que EXCEDE el
    valor real máximo de su pregunta numérica ⇒ es centinela, no un dato.
    """
    codes = ", ".join(str(int(code)) for code in suspect_codes)
    return conn.execute(f"""
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
                   MAX(value) FILTER (WHERE value NOT IN ({codes})) AS hi
            FROM vals GROUP BY 1, 2
        )
        SELECT v.wave_id, v.question_id, v.value
        FROM vals v JOIN ceil c USING (wave_id, question_id)
        WHERE v.value IN ({codes}) AND v.value > COALESCE(c.hi, 0)
        """).fetchall()
