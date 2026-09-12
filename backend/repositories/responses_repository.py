"""Consultas sobre los respondientes: atributos demográficos y ciudades."""


def fetch_attribute_values(conn, wave: str) -> list[tuple]:
    """(attribute, value, option_label) de los atributos demográficos de una ola.

    `respondent_attributes.value` es un `option_id`, así que la etiqueta sale de
    un LEFT JOIN contra `options` por (wave_id, question_id, option_id).
    """
    return conn.execute(
        """
        SELECT ra.attribute, ra.value, o.option_label
        FROM (
            SELECT DISTINCT question_id, attribute, value
            FROM respondent_attributes WHERE wave_id = ?
        ) ra
        LEFT JOIN options o ON o.wave_id = ? AND o.question_id = ra.question_id
            AND o.option_id = ra.value
        ORDER BY ra.attribute, ra.value
        """,
        [wave, wave],
    ).fetchall()


def fetch_attribute_question_id(conn, wave: str, attribute: str) -> str | None:
    """La pregunta que respalda un atributo amigable (`sexo` → `p3`)."""
    row = conn.execute(
        "SELECT DISTINCT question_id FROM respondent_attributes "
        "WHERE wave_id = ? AND attribute = ?",
        [wave, attribute],
    ).fetchone()
    return row[0] if row else None


def fetch_city_ids(conn, wave: str) -> list[int]:
    """`city_id`s distintos con respondientes en una ola."""
    rows = conn.execute(
        """
        SELECT DISTINCT city_id FROM responses
        WHERE city_id IS NOT NULL AND wave_id = ? ORDER BY city_id
        """,
        [wave],
    ).fetchall()
    return [r[0] for r in rows]


def fetch_attribute_option_map(conn) -> list[tuple]:
    """(wave_id, attribute, option_id, concept_option_id) de TODAS las olas.

    El catálogo entero de los atributos de filtro, en una sola consulta. La
    vista Año lo necesita completo para traducir filtros entre olas: resolverlo
    con un lookup por (ola, atributo, valor) hacía cientos de consultas de una
    fila cuando el filtro traía muchos valores.
    """
    return conn.execute(
        """
        SELECT ra.wave_id, ra.attribute, o.option_id, o.concept_option_id
        FROM (
            SELECT DISTINCT wave_id, attribute, question_id
            FROM respondent_attributes
        ) ra
        JOIN options o ON o.wave_id = ra.wave_id
            AND o.question_id = ra.question_id
        ORDER BY ra.wave_id, ra.attribute, o.option_id
        """
    ).fetchall()
