"""Acceso de sólo lectura al archivo DuckDB."""

import duckdb

from config import DB_PATH


def get_conn():
    """Abre una conexión de solo lectura a DuckDB."""
    return duckdb.connect(DB_PATH, read_only=True)
