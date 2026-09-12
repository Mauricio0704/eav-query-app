"""El ciclo de tool use: pregunta → llamadas a `query` → respuesta en español.

El modelo alterna entre pedir datos y redactar. Se le deja hacerlo hasta
`MAX_TOOL_ROUNDS` veces para que pueda encadenar consultas (p. ej. pedir el
total y luego el desglose) sin quedarse en un ciclo infinito si nunca concluye.
"""

import logging

from services.chat import gemini, prompts, query_tool

logger = logging.getLogger("encuesta.chat")

MAX_TOOL_ROUNDS = 4

NO_ANSWER_REPLY = "No pude completar la consulta. Intenta reformular la pregunta."


def run_chat(message: str, history: list) -> dict:
    """Responde un mensaje del chat. Devuelve respuesta, consultas y datos."""
    client = gemini.get_client()
    config = gemini.build_config(
        system_instruction=prompts.system_instruction(),
        tools=[query_tool.query_tool_declaration()],
    )

    contents = gemini.history_to_contents(history)
    contents.append(gemini.user_message(message))

    executed_queries: list = []
    data_result = None
    reply_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        response = gemini.generate(client, contents, config)
        content, function_calls = gemini.function_calls_in(response)

        if not function_calls:
            try:
                reply_text = response.text or ""
            except Exception:
                reply_text = ""
            break

        # Se registra el turno de herramientas del modelo y luego se contesta
        # cada llamada.
        if content is not None:
            contents.append(content)
        response_parts = []
        for function_call in function_calls:
            if function_call is None:
                continue
            args = dict(function_call.args) if function_call.args else {}
            result, summary, effective_query = query_tool.execute(args)
            # Registramos la consulta EFECTIVA (q_id ya traducido a la ola + año),
            # no los args crudos del modelo, para que la tarjeta del chat sea fiel.
            executed_queries.append(effective_query)
            if result is not None:
                data_result = result
                
            tool_name = function_call.name or ""
            response_parts.append(
                gemini.tool_response_part(tool_name, summary)
            )
        contents.append(gemini.tool_response_message(response_parts))
    else:
        # Se agotaron las rondas sin que el modelo redactara una respuesta.
        if not reply_text:
            reply_text = NO_ANSWER_REPLY

    logger.info("chat message=%r tool_calls=%s", message, executed_queries)
    return {"reply": reply_text, "tool_calls": executed_queries, "data": data_result}
