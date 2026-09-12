"""Configuración compartida por módulos del backend."""

import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "../data/encuesta_multianual.duckdb")
STATIC_DIR = os.getenv("STATIC_DIR", "../frontend/dist")
