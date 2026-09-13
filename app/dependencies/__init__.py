"""
Dependencias de FastAPI: conexion, autenticacion, idempotencia y el cableado
de repositorios y servicios.

Los endpoints declaran lo que necesitan con Depends y no construyen nada. Es
lo que permite sustituir la conexion por una de prueba sin tocar un solo
servicio (ver tests/conftest.py).
"""

from app.dependencies.auth import UsuarioActual, get_usuario_actual
from app.dependencies.database import get_conexion
from app.dependencies.idempotencia import get_idempotency_key

__all__ = [
    "get_conexion",
    "get_usuario_actual",
    "UsuarioActual",
    "get_idempotency_key",
]