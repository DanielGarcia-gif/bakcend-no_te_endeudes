"""DTOs de POST /simulaciones/compra. Reexporta el contrato congelado."""

from app.domain.tipos import (
    Escenario,
    MetricasCompra,
    OpcionTarjeta,
    SimulacionRequest,
    SimulacionResponse,
)

__all__ = [
    "SimulacionRequest",
    "SimulacionResponse",
    "Escenario",
    "OpcionTarjeta",
    "MetricasCompra",
]