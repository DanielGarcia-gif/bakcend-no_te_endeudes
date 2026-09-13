"""Forma uniforme de los errores de la API."""

from pydantic import BaseModel


class DetalleError(BaseModel):
    codigo: str
    mensaje: str
    detalle: dict = {}


class ErrorResponse(BaseModel):
    """
    Todos los errores salen con esta forma, sin importar si vienen de una
    regla de negocio, de un recurso inexistente o de una validacion de
    Pydantic. El frontend parsea una sola estructura.
    """
    error: DetalleError