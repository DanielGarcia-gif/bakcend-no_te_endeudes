"""
Constructores de repositorios y servicios para el sistema de Depends.

Todo el cableado del grafo de dependencias vive aqui: los routers piden el
servicio que necesitan y no saben como se construye.

Cambiar una implementacion (otro repositorio, un motor distinto, un doble de
prueba) es sustituir un provider, sin tocar endpoints ni servicios. Ese
desacoplamiento acaba de pagarse solo: la base paso de SQLite a MySQL y de este
archivo solo cambio el tipo del alias `Conexion`.
"""

from typing import Annotated

from fastapi import Depends

from app.dependencies.database import get_conexion
from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.categoria_repository import CategoriaRepository
from app.repositories.estado_repository import EstadoRepository
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.msi_repository import MSIRepository
from app.repositories.periodo_repository import PeriodoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.services.auth_service import AuthService
from app.services.categoria_service import CategoriaService
from app.services.declarativa_service import (
    IngresoService,
    PendientesService,
    RecurrenteService,
)
from app.services.deuda_service import DeudaService
from app.services.estado_service import EstadoService
from app.services.ia_service import IAService
from app.services.motor_service import MotorService
from app.services.movimiento_service import MovimientoService
from app.services.onboarding_service import OnboardingService
from app.services.score_service import ScoreService
from app.services.simulacion_service import SimulacionService
from app.services.tarjeta_service import TarjetaService

# Sin anotar el tipo del driver: el alias es lo unico que sabe cual es, y
# dejarlo generico es lo que hizo que cambiar de sqlite3 a PyMySQL no tocara
# ninguna de las factories de abajo.
Conexion = Annotated[object, Depends(get_conexion)]


# =====================================================================
# REPOSITORIOS
# =====================================================================

def get_usuario_repository(cx: Conexion) -> UsuarioRepository:
    return UsuarioRepository(cx)


def get_categoria_repository(cx: Conexion) -> CategoriaRepository:
    return CategoriaRepository(cx)


def get_ingreso_repository(cx: Conexion) -> IngresoRepository:
    return IngresoRepository(cx)


def get_tarjeta_repository(cx: Conexion) -> TarjetaRepository:
    return TarjetaRepository(cx)


def get_msi_repository(cx: Conexion) -> MSIRepository:
    return MSIRepository(cx)


def get_periodo_repository(cx: Conexion) -> PeriodoRepository:
    return PeriodoRepository(cx)


def get_recurrente_repository(cx: Conexion) -> RecurrenteRepository:
    return RecurrenteRepository(cx)


def get_movimiento_repository(cx: Conexion) -> MovimientoRepository:
    return MovimientoRepository(cx)


def get_auditoria_repository(cx: Conexion) -> AuditoriaRepository:
    return AuditoriaRepository(cx)


def get_estado_repository(cx: Conexion) -> EstadoRepository:
    return EstadoRepository(cx)


UsuarioRepo = Annotated[UsuarioRepository, Depends(get_usuario_repository)]
CategoriaRepo = Annotated[CategoriaRepository, Depends(get_categoria_repository)]
IngresoRepo = Annotated[IngresoRepository, Depends(get_ingreso_repository)]
TarjetaRepo = Annotated[TarjetaRepository, Depends(get_tarjeta_repository)]
MSIRepo = Annotated[MSIRepository, Depends(get_msi_repository)]
PeriodoRepo = Annotated[PeriodoRepository, Depends(get_periodo_repository)]
RecurrenteRepo = Annotated[RecurrenteRepository, Depends(get_recurrente_repository)]
MovimientoRepo = Annotated[MovimientoRepository, Depends(get_movimiento_repository)]
AuditoriaRepo = Annotated[AuditoriaRepository, Depends(get_auditoria_repository)]
EstadoRepo = Annotated[EstadoRepository, Depends(get_estado_repository)]


# =====================================================================
# SERVICIOS
# =====================================================================

def get_motor_service(estados: EstadoRepo) -> MotorService:
    """La unica puerta al motor. Todo lo que calcula pasa por aqui."""
    return MotorService(estados)


MotorDep = Annotated[MotorService, Depends(get_motor_service)]


def get_auth_service(usuarios: UsuarioRepo, ingresos: IngresoRepo,
                     tarjetas: TarjetaRepo, recurrentes: RecurrenteRepo,
                     auditoria: AuditoriaRepo) -> AuthService:
    # Los tres repositorios declarativos son para GET /auth/me: decirle al
    # frontend si el usuario ya paso por el onboarding.
    return AuthService(usuarios, ingresos, tarjetas, recurrentes, auditoria)


def get_categoria_service(categorias: CategoriaRepo) -> CategoriaService:
    return CategoriaService(categorias)


def get_onboarding_service(usuarios: UsuarioRepo, ingresos: IngresoRepo,
                           tarjetas: TarjetaRepo, recurrentes: RecurrenteRepo,
                           categorias: CategoriaRepo,
                           motor: MotorDep) -> OnboardingService:
    """
    El servicio con mas dependencias del sistema, y esta bien: su trabajo es
    justamente coordinar la captura inicial de cuatro tablas de una vez.
    """
    return OnboardingService(usuarios, ingresos, tarjetas, recurrentes,
                             categorias, motor)


def get_estado_service(motor: MotorDep) -> EstadoService:
    return EstadoService(motor)


def get_score_service(motor: MotorDep) -> ScoreService:
    return ScoreService(motor)


def get_ingreso_service(ingresos: IngresoRepo, movimientos: MovimientoRepo,
                        auditoria: AuditoriaRepo, motor: MotorDep) -> IngresoService:
    return IngresoService(ingresos, movimientos, auditoria, motor)


def get_recurrente_service(recurrentes: RecurrenteRepo, categorias: CategoriaRepo,
                           movimientos: MovimientoRepo, auditoria: AuditoriaRepo,
                           motor: MotorDep) -> RecurrenteService:
    return RecurrenteService(recurrentes, categorias, movimientos, auditoria, motor)


def get_pendientes_service(ingresos: IngresoRepo,
                           recurrentes: RecurrenteRepo) -> PendientesService:
    """
    Sin repositorios de escritura: los pendientes se DERIVAN y no se guardan.
    Que el servicio no pueda escribir lo vuelve imposible por construccion.
    """
    return PendientesService(ingresos, recurrentes)


def get_tarjeta_service(tarjetas: TarjetaRepo, msi: MSIRepo, periodos: PeriodoRepo,
                        auditoria: AuditoriaRepo, motor: MotorDep) -> TarjetaService:
    return TarjetaService(tarjetas, msi, periodos, auditoria, motor)


def get_movimiento_service(movimientos: MovimientoRepo, categorias: CategoriaRepo,
                           msi: MSIRepo, auditoria: AuditoriaRepo,
                           motor: MotorDep) -> MovimientoService:
    return MovimientoService(movimientos, categorias, msi, auditoria, motor)


def get_simulacion_service(motor: MotorDep) -> SimulacionService:
    """
    Sin repositorios de escritura a proposito: el simulador es de SOLO LECTURA
    y asi es imposible que persista algo por accidente.
    """
    return SimulacionService(motor)


def get_deuda_service(movimientos: MovimientoRepo, periodos: PeriodoRepo,
                      motor: MotorDep) -> DeudaService:
    return DeudaService(movimientos, periodos, motor)


AuthDep = Annotated[AuthService, Depends(get_auth_service)]
CategoriaDep = Annotated[CategoriaService, Depends(get_categoria_service)]
OnboardingDep = Annotated[OnboardingService, Depends(get_onboarding_service)]
EstadoDep = Annotated[EstadoService, Depends(get_estado_service)]
ScoreDep = Annotated[ScoreService, Depends(get_score_service)]
IngresoDep = Annotated[IngresoService, Depends(get_ingreso_service)]
RecurrenteDep = Annotated[RecurrenteService, Depends(get_recurrente_service)]
PendientesDep = Annotated[PendientesService, Depends(get_pendientes_service)]
TarjetaDep = Annotated[TarjetaService, Depends(get_tarjeta_service)]
MovimientoDep = Annotated[MovimientoService, Depends(get_movimiento_service)]
SimulacionDep = Annotated[SimulacionService, Depends(get_simulacion_service)]
DeudaDep = Annotated[DeudaService, Depends(get_deuda_service)]


# El unico servicio construido sobre OTRO servicio y no sobre repositorios,
# y por eso va aqui abajo: necesita que TarjetaDep ya exista.
def get_ia_service(tarjetas: TarjetaDep, motor: MotorDep,
                   categorias: CategoriaDep) -> IAService:
    """
    El unico servicio que sale a internet.

    Depende de TarjetaService (no del repositorio) porque necesita justo lo que
    ese servicio ya resuelve: la tarjeta del usuario o un 404 si no es suya.
    Por el mismo motivo depende de CategoriaService: el analisis de compra le
    entrega al modelo las claves reales del catalogo para que elija una de
    ellas en vez de inventar una.

    Sin repositorios de escritura, como el simulador: la extraccion PRELLENA un
    formulario y nada entra a la base hasta que la persona confirma. Que el
    servicio no pueda escribir lo vuelve imposible por construccion.

    Este provider es ademas la costura por la que los tests inyectan un doble
    sin red.
    """
    return IAService(tarjetas, motor, categorias)


IADep = Annotated[IAService, Depends(get_ia_service)]