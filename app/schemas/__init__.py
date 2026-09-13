"""
DTOs de la frontera HTTP: request, response, validacion y serializacion.

No confundir con app/models/, que es la forma de las filas en MySQL.

Parte de estos schemas REEXPORTA app/domain/tipos.py en lugar de redefinirlo.
Ese modulo es el contrato congelado y espejo de tipos.ts; una segunda
definicion de Estado o ScoreResponse divergiria sin que nadie lo note.
"""

from app.schemas.auth import LoginRequest, RegistroRequest, TokenResponse
from app.schemas.comunes import Borrado, Coleccion, Confirmacion, MetaPagina, coleccion
from app.schemas.consultas import CategoriaResumen, LiquidezUpdate, UsuarioResumen
from app.schemas.declarativas import (
    ConfirmacionCreate,
    IngresoCreate,
    IngresoResumen,
    IngresoUpdate,
    Pendiente,
    PendientesResponse,
    RecurrenteCreate,
    RecurrenteHistorial,
    RecurrenteResumen,
    RecurrenteUpdate,
)
from app.schemas.deuda import DeudaRanking, DeudaResponse, PagoRequest, PagoResponse
from app.schemas.errores import DetalleError, ErrorResponse
from app.schemas.estado import EstadoResponse
from app.schemas.movimientos import (
    Impacto,
    MovimientoCreate,
    MovimientoResponse,
    MovimientoResumen,
    MSIEnCompra,
)
from app.schemas.onboarding import (
    OnboardingRequest,
    OnboardingResponse,
    TarjetaOnboarding,
    TerminosOnboarding,
)
from app.schemas.score import Flujo30d, ScoreResponse
from app.schemas.simulacion import Escenario, SimulacionRequest, SimulacionResponse
from app.schemas.tarjetas import (
    MSICreate,
    MSIResumen,
    PagoPendiente,
    PeriodoCreate,
    PeriodoResumen,
    TarjetaCreate,
    TarjetaResumen,
    TarjetaUpdate,
)

__all__ = [
    # comunes
    "Coleccion", "MetaPagina", "coleccion", "Borrado", "Confirmacion",
    "ErrorResponse", "DetalleError",
    # auth y perfil
    "RegistroRequest", "LoginRequest", "TokenResponse", "UsuarioResumen",
    "CategoriaResumen", "LiquidezUpdate",
    # declarativas
    "IngresoCreate", "IngresoUpdate", "IngresoResumen",
    "RecurrenteCreate", "RecurrenteUpdate", "RecurrenteResumen",
    "RecurrenteHistorial", "ConfirmacionCreate",
    "Pendiente", "PendientesResponse",
    # tarjetas
    "TarjetaCreate", "TarjetaUpdate", "TarjetaResumen",
    "MSICreate", "MSIResumen",
    "PeriodoCreate", "PeriodoResumen", "PagoPendiente",
    # movimientos
    "MovimientoCreate", "MovimientoResponse", "MovimientoResumen",
    "MSIEnCompra", "Impacto",
    # onboarding
    "OnboardingRequest", "OnboardingResponse", "TarjetaOnboarding",
    "TerminosOnboarding",
    # consulta y decision
    "EstadoResponse", "ScoreResponse", "Flujo30d",
    "SimulacionRequest", "SimulacionResponse", "Escenario",
    "DeudaResponse", "DeudaRanking", "PagoRequest", "PagoResponse",
]