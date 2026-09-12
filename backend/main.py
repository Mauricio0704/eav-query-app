"""
Punto de entrada de la API (FastAPI + DuckDB de solo lectura).

Arranque:  uvicorn main:app --reload --port 8000
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sentry_sdk

from config import STATIC_DIR
from routers.chat import router as chat_router
from routers.catalog import router as catalog_router
from routers.health import router as health_router
from routers.query import router as query_router

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    send_default_pii=True,
)

app = FastAPI(title="Encuesta NL API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your frontend domain in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog_router)
app.include_router(query_router)
app.include_router(health_router)
app.include_router(chat_router)

# Serve the built Vite frontend (frontend/dist) at the root path.
if os.path.isdir(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
