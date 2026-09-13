"""
DTOs de solo lectura: perfil, catalogo y liquidez.

No forman parte del contrato congelado de tipos.py: son formas de conveniencia
para el frontend y pueden crecer sin tocar el espejo con tipos.ts.
"""

from typing import Optional

from pydantic import BaseModel, Field


class UsuarioResumen(BaseModel):
    id: str
    nombre: str
    email: str
    es_demo: bool
    onboarding_completo: bool
    saldo_disponible: float
    creado_en: str
    version: int


class CategoriaResumen(BaseModel):
    """
    El catalogo que sustituye al texto libre.

    `clave` es lo que el cliente manda en los POST ('comida'); `nombre` es para
    mostrar ('Comida'). La clave es estable y el nombre puede cambiar sin
    romper nada.
    """
    id: str
    clave: str
    nombre: str


class LiquidezUpdate(BaseModel):
    """
    Correccion manual del saldo disponible, no un movimiento.

    Existe porque antes NO habia forma de reponer liquidez: el onboarding era el
    unico camino para fijarla y solo corria una vez, asi que la cuenta se vaciaba
    y no se podia volver a llenar.

    Un ingreso de verdad NO va por aqui: va por POST /movimientos con
    tipo=ingreso, que si queda en la bitacora. Esto es "mi banco dice que tengo
    19,500 y la app dice otra cosa", y por eso deja fila en auditoria.
    """
    saldo: float = Field(ge=0)
    motivo: str = Field(min_length=3, max_length=160)
    version: Optional[int] = Field(
        default=None,
        description="La version que traia el usuario al leerlo. Si cambio, devuelve 409.",
    )