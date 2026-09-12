"""Centinelas: códigos que significan "No sabe / No contesta / No aplica".

Se reconocen por ETIQUETA o por estar FUERA DE RANGO.
"""

import re
from functools import lru_cache

from db_runtime import get_conn
from repositories import answers_repository

# Estándar en todas las olas.
STANDARD_SENTINEL_CODES = (7777, 8888, 9999)

# La vista Año descarta además 5555.
YEAR_VIEW_SENTINEL_CODES = {7777, 8888, 9999, 5555}

# Códigos "sospechosos" que algunas olas usan para No sabe/No contesta/No aplica
# en preguntas NUMÉRICAS. No se excluyen a ciegas: sólo cuentan como centinela
# en una pregunta si SUPERAN el techo de valores reales de esa pregunta, para no
# tirar valores legítimos como una edad de 88 o un gasto de $96.
SUSPECT_SENTINEL_CODES = (
    88,
    96,
    97,
    98,
    99,
    888,
    997,
    998,
    999,
    5555,
    9995,
    9996,
    9998,
    99998,
    99999,
)

# Misma regla que `db/build_db.py::_is_sentinel`, deliberadamente reimplementada
# aquí: si una de las dos cambia, los tests de integridad lo delatan.
SENTINEL_PHRASE_RE = re.compile(r"no\s*(sabe|contest|aplica|respond)", re.I)
SENTINEL_ABBREVIATION_RE = re.compile(r"^\s*(NS\s*/\s*NC|NS|NC|NA)\s*$", re.I)


def is_sentinel_label(label) -> bool:
    """True si la ETIQUETA de la opción es un centinela (No sabe/NC/NA…).

    Hace falta porque `out_of_range_sentinels_by_question` sólo mira preguntas
    `q_type='numerica'` y no cubre las escalas que una ola guardó como
    `categorica`: ahí el código del centinela (888, 8888…) entraría al promedio
    como si fuera un valor.
    """
    text = str(label or "")
    return bool(SENTINEL_PHRASE_RE.search(text)) or bool(
        SENTINEL_ABBREVIATION_RE.match(text)
    )


@lru_cache(maxsize=1)
def out_of_range_sentinels_by_question() -> dict[tuple[str, str], set[int]]:
    """(ola, pregunta) → códigos sospechosos que exceden el valor real máximo de
    esa pregunta ⇒ son centinelas (99 "días a la semana", 999 "bicicletas") y
    deben salir del promedio. Un código sospechoso DENTRO del rango real (edad
    88, gasto 96) se conserva. Se calcula una vez por proceso.
    """
    with get_conn() as conn:
        rows = answers_repository.fetch_out_of_range_sentinel_values(
            conn, SUSPECT_SENTINEL_CODES
        )
    sentinels: dict[tuple[str, str], set[int]] = {}
    for wave, question_id, value in rows:
        sentinels.setdefault((wave, question_id), set()).add(int(value))
    return sentinels


def numeric_sentinel_codes(wave: str, question_id: str) -> list[int]:
    """Códigos a excluir del promedio de una pregunta numérica: el estándar
    7777/8888/9999 unido a los centinelas fuera de rango de esa pregunta."""
    detected = out_of_range_sentinels_by_question().get((wave, question_id), set())
    return sorted(set(STANDARD_SENTINEL_CODES) | detected)
