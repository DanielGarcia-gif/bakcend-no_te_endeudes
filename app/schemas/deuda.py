"""DTOs de deuda. El request de pago no esta en tipos.py: se define aqui."""

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.tipos import DeudaRanking, DeudaResponse, PagoResponse


class PagoRequest(BaseModel):
    """
    Registrar un pago a tarjeta.

    Es una accion de dominio y no un POST /movimientos crudo porque la respuesta
    lleva algo que solo tiene sentido aqui: cuanto AHORRA el usuario al mes en
    intereses. Por dentro crea el mismo movimiento tipo='pago'.
    """
    tarjeta_id: str
    monto: float = Field(gt=0)
    fecha: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    medio: str = Field(default="debito", pattern="^(efectivo|debito)$")


__all__ = ["DeudaResponse", "DeudaRanking", "PagoRequest", "PagoResponse"]