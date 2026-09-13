"""
DTOs de autenticacion.

No estan en el contrato congelado de tipos.py porque no cruzan al motor:
solo viven en la frontera HTTP. Las formas salen de
contexto/endpoints_ejemplo.json.
"""

from pydantic import BaseModel, EmailStr, Field


class RegistroRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """
    Respuesta de /auth/registro, /auth/login y /auth/demo.

    TODO: endpoints_ejemplo.json solo documenta la respuesta de /auth/registro
    y /auth/demo. Se asume que /auth/login devuelve la misma forma; confirmar
    con quien esta construyendo el frontend.
    """
    token: str
    usuario_id: int
    nombre: str