"""
Primitivas de seguridad: hash de password y token de sesion.

Auth minima, segun el briefing: passlib + token simple. Sin verificacion de
correo, sin recuperacion, sin OAuth. Este modulo solo sabe de criptografia;
quien decide si unas credenciales son validas es AuthService.
"""

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.exceptions import NoAutenticado

_contexto_hash = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =====================================================================
# PASSWORDS
# =====================================================================

def hashear_password(password: str) -> str:
    return _contexto_hash.hash(password)


def verificar_password(password: str, password_hash: str) -> bool:
    """Devuelve False en vez de reventar si el hash almacenado no es valido."""
    try:
        return _contexto_hash.verify(password, password_hash)
    except ValueError:
        return False


# =====================================================================
# TOKEN
# =====================================================================

def crear_token(usuario_id: int) -> str:
    ahora = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario_id),
        "iat": ahora,
        "exp": ahora + timedelta(minutes=settings.token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algoritmo_token)


def leer_token(token: str) -> int:
    """Devuelve el usuario_id que viaja en el token, o lanza NoAutenticado."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algoritmo_token]
        )
        return int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise NoAutenticado("La sesion expiro, vuelve a iniciar sesion")
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise NoAutenticado("Token invalido")