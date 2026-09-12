"""Endpoints del catálogo."""

from fastapi import APIRouter

from services import catalog_service, wave_service

router = APIRouter(prefix="/api", tags=["catálogo"])


@router.get("/questions")
def list_questions(wave: str | None = None):
    """Preguntas de una ola con su tipo, sección y opciones de respuesta."""
    return catalog_service.get_questions(wave)


@router.get("/attributes")
def list_attributes(wave: str | None = None):
    """Atributos demográficos de una ola con sus valores posibles."""
    return catalog_service.get_attributes(wave)


@router.get("/recodes")
def list_recodes():
    """Definiciones de recode utilizables como `group_by` en /api/query."""
    return catalog_service.get_recodes()


@router.get("/presets")
def list_presets(wave: str | None = None):
    """Presets de análisis, traducidos a la codificación de la ola pedida."""
    return catalog_service.get_presets(wave)


@router.get("/cities")
def list_cities(wave: str | None = None):
    """Ciudades (municipios) con respondientes en una ola."""
    return catalog_service.get_cities(wave)


@router.get("/waves")
def list_waves():
    """Encuestas disponibles. `is_default` marca la ola a cargar."""
    return wave_service.list_waves()
