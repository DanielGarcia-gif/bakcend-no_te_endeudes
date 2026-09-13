"""
DTOs de GET /estado.

Reexporta el contrato congelado en vez de redefinirlo.
"""

from app.domain.tipos import (
    Compromiso,
    Estado,
    Gastos,
    Ingreso,
    IngresoProgramado,
    MSIVigente,
    TarjetaEstado,
)

# El estado se devuelve tal cual: es el mismo objeto que consume el motor.
EstadoResponse = Estado

__all__ = [
    "EstadoResponse",
    "Estado",
    "TarjetaEstado",
    "MSIVigente",
    "Ingreso",
    "IngresoProgramado",
    "Gastos",
    "Compromiso",
]