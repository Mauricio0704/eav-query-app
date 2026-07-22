# Base de datos — esquema multi-año

Esta carpeta contiene el esquema y el constructor de la base de datos DuckDB.

## Archivos

| Archivo | Qué es |
|---|---|
| `schema.sql` | DDL del esquema multi-año (tablas, PKs, columnas reservadas). |
| `build_db.py` | Construye `data/encuesta_multianual.duckdb` cargando todas las olas. |
| `waves/<año>/*.csv` | Insumos por ola (5 CSV: questions, options, responses, answers, respondent_attributes) para olas que NO vienen de la BD original 2025. |

## Modelo

Cada tabla de datos lleva `wave_id` (id de la ola/año) y forma parte de su clave
primaria. Esto permite tener varios levantamientos en el mismo archivo sin que se
mezclen: un mismo `respondent_id` o `q_id` puede existir en varias olas.

- **Optimizado para lectura / write-once**: no hay escrituras en vivo. El archivo
  se reconstruye entero con `build_db.py` y se recarga al servidor. `answers` se
  ordena físicamente por `(question_id, option_id)` para que DuckDB pode por
  zone-maps al filtrar por pregunta.
- **Columnas reservadas (Fase 2 — armonización entre años)**:
  `questions.concept_id` y `options.concept_option_id`. Hoy van en `NULL`. Cuando
  se armonicen preguntas/opciones equivalentes entre años, se llenan con un
  `UPDATE` y se crean las tablas `concepts` / `concept_options`. Reservarlas ahora
  evita re-migrar después.

## Reconstruir la BD

```bash
.venv/bin/python3 db/build_db.py
```

Escribe `data/encuesta_multianual.duckdb` cargando cada ola desde su fuente:

- **2025** — desde `data/encuesta.duckdb` (la BD original de una sola ola,
  **queda intacta**, READ_ONLY).
- **2024** y **2023** — desde `db/waves/<año>/*.csv`.

Valida unicidad de claves e integridad EAV por ola; aborta si algo no cuadra.
El backend (`main.py`), los tests (`conftest.py`) y `render.yaml` apuntan a
`encuesta_multianual.duckdb`.

## De dónde salen los CSV de una ola (ETL)

Las olas que no vienen de la BD original 2025 se generan con el ETL
**`encuesta-asi-vamos-etl`** (repo hermano), que hace el reshape ancho→largo,
las variables derivadas y los atributos, y escribe `data/processed/<año>/*.csv`.
Esos 5 CSV se copian a `db/waves/<año>/` y `build_db.py` los carga.

Las olas en formato ancho (2016–2024) comparten un motor genérico
`src/transform/wave_wide.py` + un módulo de config por año
`src/config/survey_data_<año>.py` (mapeo de atributos, columnas roster, tipos,
nombres de derivadas). Para generar y cargar una ola:

```bash
# en el repo del ETL
.venv/bin/python3 run_etl.py --year 2023      # → data/processed/2023/*.csv
# luego, en este repo
cp ../encuesta-asi-vamos-etl/data/processed/2023/*.csv db/waves/2023/
.venv/bin/python3 db/build_db.py
```

## Agregar una ola futura (formato ancho)

1. En el ETL: crear `src/config/survey_data_<año>.py` (copiar el más parecido y
   ajustar nombres de columnas, roster, atributos y derivadas), registrarlo en
   `WIDE_WAVES` de `run_etl.py`, y correr `run_etl.py --year <año>`.
2. Copiar los 5 CSV a `db/waves/<año>/`.
3. En `build_db.py`: agregar `load_wave_csv(con, "<año>", <año>, "Encuesta <año>")`.
4. Correr `db/build_db.py` y luego los tests (`pytest`).

Cada ola trae su propio `factor_cvnl` (proyección poblacional de ese año); no se
combinan entre olas.

## Cómo consultar por año

`POST /api/query` acepta `wave_id` (opcional). Si se omite, usa la ola más
reciente. Ejemplo:

```json
{ "wave_id": "2025", "question_id": "p9_1", "group_by": "sexo" }
```

> **Comparar entre años** (una consulta que devuelva varias olas a la vez) es la
> Fase 2: requiere `concept_id` poblado y las tablas `concepts` /
> `concept_options`. El esquema ya está listo para soportarlo.
