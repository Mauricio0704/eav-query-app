"""
Encuesta NL — AI chat (text-to-query) module.
"""

import os
import logging
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

logger = logging.getLogger("encuesta.chat")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_TOOL_ROUNDS = 4  # safety cap on function-call/answer iterations

router = APIRouter()


# ── Gemini client (lazy singleton) ─────────────────────────────────────────
_client = None


def _get_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="El chat de IA no está disponible: falta GEMINI_API_KEY en el servidor.",
            )
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ── Schema context (built once from the live DB metadata) ───────────────────
@lru_cache(maxsize=1)
def _schema_context() -> str:
    """Compact description of every question / attribute / recode the model may
    reference. Built from the same helpers that power the manual UI so it can
    never drift from the real data."""
    from main import list_questions, list_attributes
    from metadata import RECODES, AMM_ID, PERIFERIA_ID, ID_TO_CITY_NAME

    questions = list_questions()
    attributes = list_attributes()
    amm_cities = ", ".join(ID_TO_CITY_NAME[c] for c in AMM_ID)
    periferia_cities = ", ".join(ID_TO_CITY_NAME[c] for c in PERIFERIA_ID)

    lines = ["PREGUNTAS DISPONIBLES (usa el q_id EXACTO como question_id):"]
    for q in questions:
        lines.append(
            f"- {q['q_id']} [{q['q_type']}] ({q['q_section']}): {q['q_text']}"
        )

    lines.append("")
    lines.append(
        "ATRIBUTOS (sirven como group_by y para filtrar). En los filtros usa el "
        "número (value), no la etiqueta:"
    )
    for a in attributes:
        vals = ", ".join(f"{v['value']}={v['label']}" for v in a["values"])
        lines.append(f"- {a['attribute']}: {vals}")

    if RECODES:
        lines.append("")
        lines.append(
            "RECODES válidos como group_by (agrupan un atributo en categorías): "
            + ", ".join(RECODES.keys())
        )

    lines.append("")
    lines.append(
        "GEOGRAFÍA — para cualquier pregunta sobre zonas, municipios, el AMM, "
        "la periferia o Nuevo León en general, usa group_by=\"city_id\". Eso "
        "devuelve una fila/columna por cada municipio MÁS estos agregados:"
    )
    lines.append(
        f"- AMM = Área Metropolitana de Monterrey (suma de: {amm_cities}). "
        "Sinónimos: zona metropolitana, área metro, AMM, ZMM."
    )
    lines.append(f"- Periferia = {periferia_cities}.")
    lines.append("- Resto NL = los demás municipios de Nuevo León fuera del AMM y la Periferia.")
    lines.append("- Nuevo León = el estado completo (todos los municipios).")
    lines.append(
        "Para limitar a una zona o municipio (AMM, Periferia, Monterrey, etc.) "
        "SIEMPRE usa group_by=\"city_id\" y lee la fila/columna correspondiente. "
        "NUNCA pongas 'AMM', 'Periferia', 'Resto NL', 'Nuevo León' ni un nombre de "
        "municipio como `value` de un filtro: 'AMM' NO es un city_id válido. "
        "Los filtros de city_id solo aceptan ids numéricos de municipio."
    )

    return "\n".join(lines)


@lru_cache(maxsize=1)
def _system_instruction() -> str:
    return (
        "Eres un asistente de análisis de datos de la Encuesta de percepción "
        "ciudadana de Cómo Vamos Nuevo León (Nuevo León, México, 2025). "
        "Respondes preguntas en lenguaje natural consultando la base de datos "
        "ÚNICAMENTE mediante la herramienta `query`.\n\n"
        "REGLAS:\n"
        "- Para cualquier cifra, SIEMPRE llama a `query`. Nunca inventes números.\n"
        "- `question_id` debe ser uno de los q_id listados abajo, exactamente.\n"
        "- `group_by`: \"answer\" (sin agrupar), \"city_id\" (por municipio), o el "
        "nombre de un atributo o recode listado abajo.\n"
        "- `filters`: lista de objetos {attribute, value}. `value` es una lista de "
        "uno o más ids numéricos (option_id) del atributo. Usa SIEMPRE el id que "
        "aparece en el catálogo de abajo para ese atributo; nunca adivines el número. "
        "Ej.: si el catálogo dice 'sexo: 0=Hombre, 1=Mujer', filtrar mujeres es "
        "{\"attribute\": \"sexo\", \"value\": [1]}.\n"
        "- `initial_only` = true proyecta a la población (metodología oficial CVNL); "
        "úsalo por defecto, salvo que pidan conteos crudos del muestreo.\n"
        "- Los códigos 7777/8888/9999 (No aplica / No sabe / No contesta) se manejan "
        "automáticamente; no los filtres a mano.\n"
        "- Si la pregunta no se puede responder con las preguntas/atributos "
        "disponibles, dilo claramente en vez de forzar una consulta.\n"
        "- Tras obtener los datos, responde en español, claro y conciso, citando los "
        "porcentajes o cifras relevantes e indicando la pregunta de la encuesta usada.\n\n"
        "=== CATÁLOGO DE DATOS ===\n" + _schema_context()
    )


# ── Tool declaration ────────────────────────────────────────────────────────
def _query_tool():
    from google.genai import types

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="query",
                description=(
                    "Consulta agregada sobre la encuesta. Devuelve conteos y "
                    "porcentajes (ponderados a población por defecto) de una "
                    "pregunta, opcionalmente filtrada y/o agrupada."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "question_id": types.Schema(
                            type=types.Type.STRING,
                            description="q_id exacto de la pregunta a analizar.",
                        ),
                        "group_by": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "'answer', 'city_id', o el nombre de un atributo "
                                "o recode. Por defecto 'answer'."
                            ),
                        ),
                        "initial_only": types.Schema(
                            type=types.Type.BOOLEAN,
                            description=(
                                "true = proyectar a población (default). "
                                "false = conteos crudos del muestreo."
                            ),
                        ),
                        "filters": types.Schema(
                            type=types.Type.ARRAY,
                            description="Filtros por atributo del respondiente.",
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "attribute": types.Schema(
                                        type=types.Type.STRING,
                                        description="Nombre del atributo (o 'city_id').",
                                    ),
                                    "value": types.Schema(
                                        type=types.Type.ARRAY,
                                        description="Uno o más ids numéricos.",
                                        items=types.Schema(type=types.Type.INTEGER),
                                    ),
                                },
                                required=["attribute", "value"],
                            ),
                        ),
                    },
                    required=["question_id"],
                ),
            )
        ]
    )


# ── Query execution ─────────────────────────────────────────────────────────
def _norm_value(v):
    if isinstance(v, (list, tuple)):
        return [int(x) for x in v]
    return int(v)


def _exec_query(args: dict):
    """Run one `query` tool call. Returns (full_result_for_frontend, summary_for_model).

    Any bad argument from the model is returned as an `error` summary (never
    raised) so the conversation loop can let the model self-correct instead of
    crashing the whole request."""
    from main import run_query, QueryRequest

    try:
        norm_filters = []
        for f in args.get("filters") or []:
            attr = f.get("attribute")
            val = f.get("value")
            if not attr or val is None:
                continue
            if attr == "city_id":
                norm_filters.append({"attribute": attr, "value": _norm_city_value(val)})
            else:
                norm_filters.append({"attribute": attr, "value": _norm_value(val)})

        req = QueryRequest(
            question_id=args["question_id"],
            filters=norm_filters,
            group_by=args.get("group_by") or "answer",
            initial_only=args.get("initial_only", True),
        )
        result = run_query(req)
    except HTTPException as e:
        return None, {"error": str(e.detail)}
    except (ValueError, TypeError, KeyError) as e:
        return None, {"error": f"Argumentos inválidos: {e}"}

    return result, _summarize(result)


def _norm_city_value(v):
    """city_id filters only accept numeric municipality ids. Reject zone names
    like 'AMM' with a clear hint so the model switches to group_by='city_id'."""
    items = v if isinstance(v, (list, tuple)) else [v]
    out = []
    for x in items:
        try:
            out.append(int(x))
        except (ValueError, TypeError):
            raise ValueError(
                f"'{x}' no es un city_id válido. Las zonas (AMM, Periferia, etc.) "
                "no se filtran: usa group_by='city_id' y lee esa fila/columna."
            )
    return out


def _summarize(result: dict) -> dict:
    """Compact view of a query result to feed back to the model (drops SQL)."""
    out = {
        "question": result.get("question"),
        "group_by": result.get("group_by"),
        "total_respondents": result.get("total_respondents"),
        "format": result.get("format"),
    }
    if result.get("format") == "flat":
        out["columns"] = result.get("column_labels")
        out["rows"] = result.get("rows")
    else:
        out["counts"] = result.get("counts")
        out["percentages"] = result.get("percentages")
    return out


# ── Conversation ─────────────────────────────────────────────────────────────
def _history_to_contents(history):
    from google.genai import types

    out = []
    for m in history or []:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        role = "model" if m.get("role") == "assistant" else "user"
        out.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return out


def _run_chat(message: str, history: list) -> dict:
    from google.genai import types

    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=_system_instruction(),
        tools=[_query_tool()],
        temperature=0,
    )

    contents = _history_to_contents(history)
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    tool_calls: list = []
    data_result = None
    reply_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=config
        )
        candidate = resp.candidates[0]
        parts = candidate.content.parts or []
        fcalls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not fcalls:
            try:
                reply_text = resp.text or ""
            except Exception:
                reply_text = ""
            break

        # Record the model's tool-call turn, then answer each call.
        contents.append(candidate.content)
        response_parts = []
        for fc in fcalls:
            args = dict(fc.args) if fc.args else {}
            result, summary = _exec_query(args)
            tool_calls.append(args)
            if result is not None:
                data_result = result  # keep the last successful table for the UI
            response_parts.append(
                types.Part.from_function_response(name=fc.name, response=summary)
            )
        contents.append(types.Content(role="user", parts=response_parts))
    else:
        if not reply_text:
            reply_text = "No pude completar la consulta. Intenta reformular la pregunta."

    logger.info("chat message=%r tool_calls=%s", message, tool_calls)
    return {"reply": reply_text, "tool_calls": tool_calls, "data": data_result}


class ChatRequest(BaseModel):
    message: str
    # Prior turns as [{"role": "user"|"assistant", "text": "..."}]
    history: list[dict] = []


def _friendly_error(e: Exception) -> tuple[int, str]:
    """Map a Gemini/SDK exception to (status_code, user-facing message)."""
    code = getattr(e, "code", None)
    text = str(e)
    if code == 429 or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return 429, (
            "Se alcanzó el límite de solicitudes de la API de Gemini. Espera un "
            "momento e intenta de nuevo. (El plan gratuito permite solo 20 "
            "consultas por día y por modelo; considera habilitar facturación o "
            "subir el límite para uso real.)"
        )
    if code in (401, 403) or "API key" in text or "PERMISSION_DENIED" in text:
        return 502, "Problema de autenticación con la API de Gemini. Revisa GEMINI_API_KEY."
    return 502, "El asistente no pudo procesar la solicitud. Intenta de nuevo."


@router.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje está vacío.")
    try:
        return await run_in_threadpool(_run_chat, req.message, req.history)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("chat failed")
        status, msg = _friendly_error(e)
        raise HTTPException(status_code=status, detail=msg)


@router.get("/api/chat/health")
def chat_health():
    return {"enabled": bool(GEMINI_API_KEY), "model": GEMINI_MODEL}
