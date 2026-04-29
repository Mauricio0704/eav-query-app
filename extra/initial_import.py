import duckdb

conn = duckdb.connect("ruta/encuesta.duckdb")  # crea el archivo si no existe

conn.execute("""
    CREATE TABLE questions AS
    SELECT * FROM read_csv_auto('ruta/questions.csv')
""")

conn.execute("""
    CREATE TABLE answers AS
    SELECT * FROM read_csv_auto('ruta/answers.csv')
""")

conn.execute("""
    CREATE TABLE options AS
    SELECT * FROM read_csv_auto('ruta/options.csv')
""")

conn.execute("""
    CREATE TABLE respondent_attributes AS
    SELECT * FROM read_csv_auto('ruta/respondent_attributes.csv')
""")

conn.execute("""
    CREATE TABLE responses AS
    SELECT * FROM read_csv_auto('ruta/responses.csv')
""")

conn.close()
print("Listo — archivo encuesta.duckdb creado")