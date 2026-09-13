"""
Cliente de Gemini. La UNICA parte del backend que sale a internet.

Esta llamada vivia en el frontend (`lib/gemini.ts`). Alli la API key la
inyectaba Vite en el bundle, o sea que cualquiera con las devtools abiertas se
la llevaba. Aqui la llave sale de settings y el navegador no la ve nunca.

SOBRE EL SDK: la primera version de este modulo eran ~40 lineas de
`urllib.request`, con el argumento de que un POST con un JSON no paga un SDK.
Lo que paga el SDK no es el transporte, es `response_schema`: el esquema deja
de ser texto dentro del prompt (una promesa que el modelo podia romper y que
solo se descubria al parsear) y pasa a ser una garantia del servicio. Con eso
se fue el parseo defensivo entero.

Que Gemini extrae y redacta pero NO calcula sigue igual de cierto que antes:
los numeros salen del motor determinista, y este modulo solo devuelve el dict
que contesto el modelo.
"""

import json
import logging

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import ServicioIANoDisponible

log = logging.getLogger("app.gemini")

# Precio publicado por millon de tokens para la familia flash-lite, que es el
# primer modelo de la lista. Solo alimenta la linea de log: el dato de cuanto
# cuesta una extraccion va a la hoja "Supuestos" del modelo financiero, y antes
# solo lo veia quien abriera la consola del navegador.
_USD_ENTRADA = 0.075
_USD_SALIDA = 0.30

_cliente: genai.Client | None = None


def disponible() -> bool:
    """Si esto es False, ningun endpoint de IA puede responder."""
    return bool(settings.gemini_api_key)


def _obtener_cliente() -> genai.Client:
    """
    El cliente, construido la primera vez que hace falta y reusado despues.

    Perezoso a proposito: sin llave la app tiene que arrancar igual, con los dos
    endpoints de IA en 503 y todo lo demas funcionando. Construirlo en el import
    haria que un `.env` sin GEMINI_API_KEY tumbara el servidor entero.
    """
    global _cliente
    if _cliente is None:
        _cliente = genai.Client(
            api_key=settings.gemini_api_key,
            # El SDK lo toma en MILISEGUNDOS; settings lo guarda en segundos,
            # que es como se midio en contexto/test_gemini.py.
            http_options=types.HttpOptions(timeout=settings.gemini_timeout * 1000),
        )
    return _cliente


def generar(partes: list[types.Part], prompt: str,
            esquema: type[BaseModel]) -> dict:
    """
    Manda `partes` (texto o un PDF) mas el prompt, exigiendo que la respuesta
    tenga la forma de `esquema`. Devuelve el dict que contesto el modelo.

    Recorre `settings.gemini_modelos` en orden. Solo el 503 hace pasar al
    siguiente: un 404 significa que la llave no tiene ese modelo y reintentar
    no lo arregla, y un 429 es cuota, que tampoco se cura cambiando de modelo.
    """
    if not disponible():
        raise ServicioIANoDisponible(
            "El servidor no tiene configurada la llave de Gemini."
        )

    config = types.GenerateContentConfig(
        # 0 porque esto extrae datos de un documento, no escribe prosa: la
        # misma pagina tiene que dar el mismo numero las dos veces.
        temperature=0,
        response_mime_type="application/json",
        response_schema=esquema,
    )

    ultimo_error = "Gemini no contesto"

    for modelo in settings.gemini_modelos:
        try:
            respuesta = _obtener_cliente().models.generate_content(
                model=modelo,
                contents=[*partes, prompt],
                config=config,
            )
        except errors.APIError as e:
            if e.code == 503:
                # Saturado: este es el unico caso que vale la pena reintentar
                # con otro modelo.
                log.warning("Gemini 503 con %s, probando el siguiente", modelo)
                ultimo_error = "Gemini esta saturado. Intenta de nuevo en un momento"
                continue
            if e.code == 404:
                raise ServicioIANoDisponible(
                    f"El modelo {modelo} no esta disponible con esta llave"
                ) from e
            if e.code == 429:
                raise ServicioIANoDisponible(
                    "Gemini esta saturado. Intenta de nuevo en un momento"
                ) from e
            log.error("Gemini %s: %s", e.code, e.message)
            raise ServicioIANoDisponible(f"Gemini respondio {e.code}") from e
        except Exception as e:
            # Red caida o timeout: el SDK va por httpx y levanta sus
            # excepciones, no las de urllib. Tampoco se arregla cambiando de
            # modelo.
            log.error("No se pudo alcanzar a Gemini: %s", e)
            raise ServicioIANoDisponible(
                "No se pudo conectar con Gemini. Intenta de nuevo en un momento"
            ) from e

        return _leer(respuesta, modelo)

    raise ServicioIANoDisponible(ultimo_error)


def _leer(respuesta: types.GenerateContentResponse, modelo: str) -> dict:
    """Registra lo que costo la llamada y devuelve el objeto que ya valido el SDK."""
    uso = respuesta.usage_metadata
    t_in = (uso.prompt_token_count or 0) if uso else 0
    t_out = (uso.candidates_token_count or 0) if uso else 0
    log.info(
        "gemini modelo=%s tokens_entrada=%s tokens_salida=%s costo_usd=%.5f",
        modelo, t_in, t_out,
        t_in / 1e6 * _USD_ENTRADA + t_out / 1e6 * _USD_SALIDA,
    )

    # Con `response_schema` el SDK ya valido y construyo el modelo. Se devuelve
    # dict y no la instancia porque `domain.extraccion.mapear()` es una funcion
    # pura sobre dicts y sus pruebas le pasan diccionarios a mano.
    if isinstance(respuesta.parsed, BaseModel):
        return respuesta.parsed.model_dump()

    # `parsed` viene vacio cuando el modelo no produjo nada util: filtro de
    # seguridad, corte por longitud, respuesta truncada. El texto crudo es el
    # ultimo recurso antes de rendirse.
    if not respuesta.text:
        raise ServicioIANoDisponible("Gemini devolvio una respuesta vacia")

    try:
        datos = json.loads(respuesta.text)
    except json.JSONDecodeError:
        raise ServicioIANoDisponible("Gemini no devolvio JSON valido") from None

    if not isinstance(datos, dict):
        raise ServicioIANoDisponible("Gemini no devolvio un objeto JSON")
    return datos