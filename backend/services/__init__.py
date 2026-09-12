"""Lógica de negocio: orquesta repositorios, aplica reglas y cachea.

Los servicios abren la conexión (`with get_conn() as conn`), llaman a uno o más
repositorios y arman la estructura que la capa HTTP devuelve. No contienen SQL.
"""
