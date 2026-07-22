-- =====================================================================
-- Encuesta NL — Esquema multi-año (optimizado para lectura, write-once)
-- =====================================================================
-- Diseño:
--   * `wave_id` (id de la ola/levantamiento) está presente en TODAS las
--     tablas de datos y forma parte de cada clave primaria. Esto elimina la
--     colisión de identidad entre años: un mismo `respondent_id` ('1000_1')
--     o `q_id` ('p9') puede existir en varias olas sin mezclarse.
--   * Modelo normalizado (EAV) idéntico al actual: las etiquetas se resuelven
--     por JOIN, no se hornean. En DuckDB (columnar) esos JOINs son baratos.
--   * `answers` es la tabla de hechos: se ordena FÍSICAMENTE al cargar (ver
--     build_db.py) para que DuckDB pode por zone-maps al filtrar por pregunta.
--   * Columnas RESERVADAS para la Fase 2 (armonización entre años):
--       questions.concept_id           → pregunta armonizada (NULL por ahora)
--       options.concept_option_id      → opción armonizada  (NULL por ahora)
--     Las tablas `concepts` / `concept_options` NO se crean todavía: se
--     construyen en la Fase 2 con los datos reales de armonización. Reservar
--     las columnas ahora hace que esa fase sea un UPDATE, no una re-migración.
-- =====================================================================

-- Catálogo de conceptos (Fase 2 — armonización entre años). Un concepto agrupa
-- preguntas equivalentes de distintas olas (p. ej. "principal ocupación" = p3 en
-- 2023/2024 y p1 en 2025). `comparable` = las opciones también son equivalentes,
-- así que se puede comparar la distribución/promedio entre años ("group_by=year").
-- Se puebla en build_db.py desde db/concepts/*.csv; questions.concept_id y
-- options.concept_option_id enlazan cada pregunta/opción a su concepto.
CREATE TABLE concepts (
    concept_id VARCHAR NOT NULL,
    label      VARCHAR,
    q_type     VARCHAR,          -- 'numerica' | 'categorica' (tipo unificado)
    comparable BOOLEAN,          -- TRUE = comparable entre años
    PRIMARY KEY (concept_id)
);

-- Opciones canónicas de un concepto (armonización de opciones entre años). Cada
-- `options.concept_option_id` de cada ola apunta a una de estas filas, de modo
-- que códigos distintos entre años (p. ej. sexo 1/2 en 2022 vs 0/1 en 2023-25)
-- se comparan como la misma opción canónica. La comparación "year" agrupa por
-- `concept_option_id`, no por el `option_id` crudo.
CREATE TABLE concept_options (
    concept_id        VARCHAR NOT NULL,
    concept_option_id VARCHAR NOT NULL,
    label             VARCHAR,
    sort_order        INTEGER,
    PRIMARY KEY (concept_id, concept_option_id)
);

-- Catálogo de olas. Tabla madre: una fila por levantamiento.
CREATE TABLE waves (
    wave_id       VARCHAR NOT NULL,   -- id estable de la ola, p. ej. '2025'
    year          INTEGER NOT NULL,   -- año numérico (orden / group_by)
    label         VARCHAR,            -- nombre para mostrar
    period        VARCHAR,            -- trabajo de campo, p. ej. 'Oct-Nov 2025'
    n_respondents INTEGER,            -- conteo de respondientes (cache UI)
    notes         VARCHAR,            -- notas metodológicas
    PRIMARY KEY (wave_id)
);

-- Un respondiente por fila (dentro de su ola).
CREATE TABLE responses (
    wave_id               VARCHAR NOT NULL,
    respondent_id         VARCHAR NOT NULL,   -- id original del año, tal cual
    is_initial_respondent BIGINT,             -- 0/1
    nombre                VARCHAR,
    factor_cvnl           DOUBLE,             -- factor de expansión de ESA ola
    city_id               BIGINT,             -- municipio
    PRIMARY KEY (wave_id, respondent_id)
);

-- El cuestionario tal como se aplicó en cada ola.
CREATE TABLE questions (
    wave_id    VARCHAR NOT NULL,
    q_id       VARCHAR NOT NULL,   -- id posicional del año, p. ej. 'p9' (único por ola)
    q_text     VARCHAR,            -- texto tal como se preguntó ese año
    q_section  VARCHAR,
    q_type     VARCHAR,            -- 'numerica' | 'categorica' | ...
    q_notes    VARCHAR,
    q_info     VARCHAR,
    q_block    VARCHAR,
    concept_id VARCHAR,            -- RESERVADO (Fase 2): NULL por ahora
    PRIMARY KEY (wave_id, q_id)
);

-- Opciones de respuesta de cada pregunta, tal como aparecieron ese año.
CREATE TABLE options (
    wave_id           VARCHAR NOT NULL,
    question_id       VARCHAR NOT NULL,
    option_id         BIGINT  NOT NULL,
    option_label      VARCHAR,
    concept_option_id VARCHAR,     -- RESERVADO (Fase 2): NULL por ahora
    PRIMARY KEY (wave_id, question_id, option_id)
);

-- Atributos de cruce/filtro por respondiente. `attribute` es el nombre
-- amigable estable ('sexo', 'ingreso', ...); `question_id` es el q_id de
-- origen de ese año (puede variar entre años → el ancla es `attribute`).
CREATE TABLE respondent_attributes (
    wave_id       VARCHAR NOT NULL,
    respondent_id VARCHAR NOT NULL,
    question_id   VARCHAR,
    attribute     VARCHAR NOT NULL,
    value         BIGINT,          -- option_id (o valor numérico, p. ej. edad)
    PRIMARY KEY (wave_id, respondent_id, attribute)
);

-- Tabla de hechos (EAV). Categóricas: option_id lleno, value NULL.
-- Numéricas: option_id NULL, value lleno.
-- Sin PRIMARY KEY: option_id es NULL en numéricas (no puede ir en PK) y un
--   índice ART sobre 1.1M+ filas no ayuda a scans/agregados y engorda el
--   archivo. La unicidad de (wave_id, respondent_id, question_id) se valida
--   en build_db.py.
-- Sin FOREIGN KEY: existen ~76 referencias (question_id, option_id) sin fila
--   en `options` que el backend ya maneja con LEFT JOIN; una FK las rechazaría.
CREATE TABLE answers (
    wave_id       VARCHAR NOT NULL,
    respondent_id VARCHAR NOT NULL,
    question_id   VARCHAR NOT NULL,
    option_id     BIGINT,
    value         DOUBLE
);
