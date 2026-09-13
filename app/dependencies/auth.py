"""
Dependencia de autenticacion.

Resuelve el usuario a partir del Bearer token. Los endpoints protegidos piden
`usuario_id: UsuarioActual` y no saben nada de tokens.
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import NoAutenticado
from app.core.security import leer_token
from app.dependencies.database import get_conexion
from app.repositories.usuario_repository import UsuarioRepository

# auto_error=False para lanzar nuestra excepcion en vez del HTTPException de
# FastAPI: asi todos los errores salen con la misma forma.
_bearer = HTTPBearer(auto_error=False)


def get_usuario_actual(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    cx=Depends(get_conexion),
) -> int:
    """
    Devuelve el usuario_id, verificando que el usuario siga existiendo.

    La version anterior no consultaba la base: si el token era valido, daba el
    id por bueno. El resultado era que el token de un usuario ya eliminado
    pasaba la autenticacion y reventaba mas adelante con un 404 al no encontrar
    sus datos — un "no existe ese recurso" cuando lo correcto es "tu sesion ya
    no vale". Son dos cosas distintas y el frontend actua distinto en cada una:
    con 401 manda a login, con 404 muestra una pantalla vacia.

    Cuesta una consulta por request, servida por la PK.
    """
    if credenciales is None:
        raise NoAutenticado("Falta el token de sesion")

    usuario_id = leer_token(credenciales.credentials)

    if UsuarioRepository(cx).buscar(usuario_id) is None:
        raise NoAutenticado("La sesion ya no es valida")
    return usuario_id


UsuarioActual = Annotated[int, Depends(get_usuario_actual)]