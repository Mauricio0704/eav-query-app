"""Acceso a datos: el único lugar donde vive texto SQL fijo.

Cada función recibe una conexión abierta (`conn`) y devuelve filas crudas o
valores planos. No cachea, no valida y no conoce HTTP — de eso se encargan los
servicios, que son los dueños del ciclo de vida de la conexión.

El SQL que se COMPONE en tiempo de ejecución no vive aquí sino en
`services/query/sql_builder.py`: aquí sólo hay consultas fijas y parametrizadas.
"""
