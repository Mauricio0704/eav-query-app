"""Modo IA: el modelo responde consultando la encuesta por tool use.

El modelo NUNCA emite SQL. Sólo puede actuar invocando `query`, que es la misma
función del motor que usa la UI manual, así que una respuesta del chat pasa por
el mismo camino validado y ponderado que una consulta hecha a mano.

    prompts.py       el texto que se le da al modelo (contenido, no lógica)
    gemini.py        lo único que sabe que el proveedor es Gemini
    query_tool.py    la herramienta `query`: declaración, ejecución y resumen
    conversation.py  el ciclo de tool use

Todo el modo es opcional: sin `GEMINI_API_KEY` la app corre en modo manual.
"""
