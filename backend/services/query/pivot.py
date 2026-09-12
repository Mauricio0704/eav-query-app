"""Armado de las tablas del pivote y agrupación geográfica.

El SQL devuelve una celda por (respuesta, grupo); aquí se convierte en las dos
tablas que ve el usuario —conteos y porcentajes— y se colapsan los `city_id`
crudos en las cubetas curadas de `metadata.py`.
"""

from metadata import AMM_ID, DESIRED_ORDERS, ID_TO_CITY_NAME, PERIFERIA_ID

# Ids < 100 son municipios de Nuevo León; el resto son códigos de otra cosa.
NUEVO_LEON_CITY_IDS = {city_id for city_id in ID_TO_CITY_NAME if city_id < 100}
RESTO_NL_CITY_IDS = NUEVO_LEON_CITY_IDS - set(AMM_ID) - set(PERIFERIA_ID)

# Cubetas que CONTIENEN a otras: sumarlas en el total de un renglón contaría dos
# veces a los mismos respondientes.
OVERLAPPING_CITY_BUCKETS = ("AMM", "Nuevo León")


def format_numeric_label(value) -> str:
    """Formatea un valor numérico como id/etiqueta legible (30.0 → '30')."""
    try:
        number = float(value)
        return str(int(number)) if number == int(number) else str(number)
    except (TypeError, ValueError):
        return str(value)


def resolve_city_buckets(city_filter):
    """Decide las columnas de la vista por ciudad: (ids por cubeta, orden).

    Sin filtro de ciudad se muestran las 11 del AMM más los cuatro agregados
    (AMM, Periferia, Resto NL, Nuevo León). Con filtro se muestran sólo los
    municipios pedidos, en el orden canónico de `metadata.DESIRED_ORDERS`.
    """
    selected_city_ids = None
    if city_filter:
        raw_value = city_filter["value"]
        selected_city_ids = raw_value if isinstance(raw_value, list) else [raw_value]

    if selected_city_ids:
        city_ids_by_bucket = {}
        for city_id in selected_city_ids:
            label = ID_TO_CITY_NAME.get(int(city_id), str(city_id))
            city_ids_by_bucket.setdefault(label, set()).add(str(int(city_id)))
        municipality_rank = {
            name: i for i, name in enumerate(DESIRED_ORDERS["municipio"])
        }
        bucket_labels = sorted(
            city_ids_by_bucket,
            key=lambda label: (municipality_rank.get(label, 10_000), label.lower()),
        )
        return city_ids_by_bucket, bucket_labels

    city_ids_by_bucket = {
        ID_TO_CITY_NAME[city_id]: {str(city_id)} for city_id in AMM_ID
    }
    city_ids_by_bucket["AMM"] = {str(city_id) for city_id in AMM_ID}
    city_ids_by_bucket["Periferia"] = {str(city_id) for city_id in PERIFERIA_ID}
    city_ids_by_bucket["Resto NL"] = {str(city_id) for city_id in RESTO_NL_CITY_IDS}
    city_ids_by_bucket["Nuevo León"] = {
        str(city_id) for city_id in NUEVO_LEON_CITY_IDS
    }
    return city_ids_by_bucket, list(DESIRED_ORDERS["municipio"])


def collapse_cities_into_buckets(
    response_values, counts_by_cell, totals_by_city, bucket_labels, city_ids_by_bucket
):
    """Suma las celdas por `city_id` crudo en las cubetas geográficas.

    Devuelve `(counts_by_cell, totals_by_bucket)` ya rekeyados por etiqueta de
    cubeta en vez de por id de municipio.
    """
    collapsed_counts, totals_by_bucket = {}, {}
    for bucket in bucket_labels:
        city_ids = city_ids_by_bucket.get(bucket, set())
        totals_by_bucket[bucket] = sum(
            totals_by_city.get(city_id, 0) for city_id in city_ids
        )
        for response_value in response_values:
            total = sum(
                counts_by_cell.get((response_value, city_id), 0)
                for city_id in city_ids
            )
            if total:
                collapsed_counts[(response_value, bucket)] = total
    return collapsed_counts, totals_by_bucket


def build_counts_and_percentage_rows(
    response_values,
    label_for,
    counts_by_cell,
    group_keys,
    totals_by_group,
    grand_total,
    grouped_by_city,
):
    """Arma los renglones de ambas tablas del pivote, con su renglón Total.

    El % de cada celda se calcula sobre el total de SU COLUMNA (no del renglón),
    que es como se leen los cruces en el informe. Una celda en cero se emite
    como cadena vacía; `csv_export` la rellena con 0 al exportar.
    """
    # El total del renglón suma sólo cubetas disjuntas: con AMM y Nuevo León
    # dentro, cada respondiente del AMM se contaría tres veces.
    non_overlapping_groups = (
        [group for group in group_keys if group not in OVERLAPPING_CITY_BUCKETS]
        if grouped_by_city
        else list(group_keys)
    )

    counts_rows, percentage_rows = [], []
    for response_value in response_values:
        label = label_for(response_value)
        row_total = sum(
            counts_by_cell.get((response_value, group), 0)
            for group in non_overlapping_groups
        )
        counts_row = [response_value, label]
        percentage_row = [response_value, label]
        for group in group_keys:
            count = counts_by_cell.get((response_value, group), 0)
            group_total = totals_by_group.get(group, 0)
            counts_row.append(count if count else "")
            percentage_row.append(
                round(count * 100.0 / group_total, 1) if group_total else ""
            )
        counts_row.append(row_total if row_total else "")
        percentage_row.append(
            round(row_total * 100.0 / grand_total, 1) if grand_total else ""
        )
        counts_rows.append(counts_row)
        percentage_rows.append(percentage_row)

    counts_rows.append(
        ["Total", ""]
        + [totals_by_group.get(group, 0) for group in group_keys]
        + [grand_total]
    )
    percentage_rows.append(
        ["Total", ""]
        + [100.0 if totals_by_group.get(group, 0) else "" for group in group_keys]
        + [100.0 if grand_total else ""]
    )
    return counts_rows, percentage_rows
