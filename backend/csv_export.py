"""Serialización a CSV de los resultados del motor de consultas."""

import csv
import io

_CSV_STAT_ROWS = {"Promedio", "Promedio (media)"}


def _csv_fill_empty(rows, label_cols):
    """Fill empty data cells with zero, preserving empty statistic cells."""
    out = []
    for row in rows:
        if row and row[0] in _CSV_STAT_ROWS:
            out.append(row)
            continue
        out.append(
            [0 if (i >= label_cols and cell == "") else cell for i, cell in enumerate(row)]
        )
    return out


def query_result_to_csv(data) -> str:
    """Serializa el resultado de `run_query` a un CSV.

    En modo pivote emite dos tablas en un solo CSV —un bloque Conteos y uno
    Porcentajes, separados por un renglón en blanco—; las celdas de grupos sin
    respondientes se exportan como 0 (ver `_csv_fill_empty`).
    """
    output = io.StringIO()
    writer = csv.writer(output)

    if data.get("format") == "pivot":
        # 1 columna de etiqueta en la vista Año (Respuesta); 2 en los demás
        # pivotes (id_respuesta + Respuesta).
        label_cols = 1 if data.get("group_by") == "year" else 2
        writer.writerow(["Conteos"])
        writer.writerow(data["counts"]["columns"])
        for row in _csv_fill_empty(data["counts"]["rows"], label_cols):
            writer.writerow(row)
        writer.writerow([])
        writer.writerow(["Porcentajes"])
        writer.writerow(data["percentages"]["columns"])
        for row in _csv_fill_empty(data["percentages"]["rows"], label_cols):
            writer.writerow(row)
    else:
        writer.writerow(data["column_labels"])
        for row in data["rows"]:
            writer.writerow(row)

    return output.getvalue()
