"""
Los endpoints de consulta y decision: estado, score, categorias, simulador,
deuda y onboarding.

Van juntos porque todos son delgados —delegan en un servicio y devuelven su
DTO— y tenerlos en seis archivos de veinte lineas cada uno solo agregaba
archivos que abrir.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Response, status

from app.dependencies.auth import UsuarioActual
from app.dependencies.idempotencia import get_idempotency_key
from app.dependencies.providers import (
    AuthDep,
    CategoriaDep,
    DeudaDep,
    EstadoDep,
    OnboardingDep,
    ScoreDep,
    SimulacionDep,
)
from app.schemas.auth import LoginRequest, RegistroRequest, TokenResponse
from app.schemas.comunes import Coleccion
from app.schemas.consultas import CategoriaResumen, LiquidezUpdate, UsuarioResumen
from app.schemas.deuda import DeudaResponse, PagoRequest, PagoResponse
from app.schemas.errores import ErrorResponse
from app.schemas.estado import EstadoResponse
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.schemas.score import ScoreResponse
from app.schemas.simulacion import SimulacionRequest, SimulacionResponse

ERRORES = {
    401: {"model": ErrorResponse, "description": "Sin token o sesion vencida"},
    404: {"model": ErrorResponse, "description": "No existe o no es tuyo"},
    409: {"model": ErrorResponse, "description": "Conflicto de estado"},
    422: {"model": ErrorResponse, "description": "Regla de negocio o validacion"},
}


# =====================================================================
# AUTH
# =====================================================================

auth = APIRouter(prefix="/auth", tags=["auth"])


@auth.post("/registro", response_model=TokenResponse,
           status_code=status.HTTP_201_CREATED,
           responses={409: {"model": ErrorResponse, "description": "Correo ya registrado"},
                      422: {"model": ErrorResponse}})
def registro(datos: RegistroRequest, servicio: AuthDep) -> TokenResponse:
    return TokenResponse(**servicio.registrar(datos.nombre, datos.email,
                                              datos.password))


@auth.post("/login", response_model=TokenResponse,
           responses={401: {"model": ErrorResponse, "description": "Credenciales invalidas"}})
def login(datos: LoginRequest, servicio: AuthDep) -> TokenResponse:
    return TokenResponse(**servicio.login(datos.email, datos.password))


@auth.post("/demo", response_model=TokenResponse,
           responses={404: {"model": ErrorResponse, "description": "Base sin sembrar"}})
def demo(servicio: AuthDep) -> TokenResponse:
    """
    Sesion del usuario demo precargado, sin credenciales. Es la puerta de
    entrada del jurado: un clic y ve datos que cuentan una historia.
    """
    return TokenResponse(**servicio.sesion_demo())


@auth.get("/me", response_model=UsuarioResumen, responses=ERRORES)
def yo(usuario_id: UsuarioActual, servicio: AuthDep) -> UsuarioResumen:
    """
    Los datos del usuario en sesion.

    Es lo primero que deberia llamar el frontend al arrancar si encuentra un
    token guardado: devuelve el nombre para la cabecera, si es el usuario demo,
    y si ya paso por el onboarding.

    Un 401 aqui significa que la sesion no vale —token vencido o usuario
    eliminado— y hay que mandar al login.
    """
    return servicio.perfil(usuario_id)


# =====================================================================
# PERFIL
# =====================================================================

usuarios = APIRouter(prefix="/usuarios", tags=["usuarios"])


@usuarios.put("/me/liquidez", response_model=UsuarioResumen, responses=ERRORES)
def corregir_liquidez(usuario_id: UsuarioActual, datos: LiquidezUpdate,
                      servicio: AuthDep) -> UsuarioResumen:
    """
    Corrige el saldo disponible. NO es un movimiento.

    Existe porque antes no habia forma de reponer liquidez: el onboarding era el
    unico camino para fijarla y solo corria una vez, asi que la cuenta se
    vaciaba y no se podia volver a llenar.

    Un ingreso de verdad va por POST /movimientos con tipo=ingreso, que si queda
    en la bitacora. Esto es "mi banco dice otra cosa", exige un `motivo` y deja
    fila en auditoria: un saldo que cambia sin movimiento que lo explique tiene
    que ser rastreable.

    PUT y no PATCH porque reemplaza el valor completo, y `version` evita pisar
    un gasto registrado mientras el formulario estaba abierto.
    """
    return servicio.corregir_liquidez(usuario_id, datos)


# =====================================================================
# CATALOGO
# =====================================================================

categorias = APIRouter(tags=["categorias"])


@categorias.get("/categorias", response_model=Coleccion[CategoriaResumen])
def listar_categorias(servicio: CategoriaDep) -> dict:
    """
    Las claves validas para `categoria` en gastos y recurrentes.

    Publico: es un catalogo fijo, no depende del usuario y el frontend lo
    necesita para armar su selector antes de que nadie inicie sesion.
    """
    return servicio.listar()


# =====================================================================
# ONBOARDING
# =====================================================================

onboarding = APIRouter(tags=["onboarding"])


@onboarding.post("/onboarding", response_model=OnboardingResponse,
                 status_code=status.HTTP_201_CREATED, responses=ERRORES)
def ejecutar_onboarding(usuario_id: UsuarioActual, datos: OnboardingRequest,
                        servicio: OnboardingDep) -> OnboardingResponse:
    """
    La captura inicial completa en una sola llamada y una sola transaccion.

    Devuelve **409** si el usuario ya tiene datos: para corregir estan los
    endpoints individuales. Todo se valida ANTES de la primera escritura, asi
    que un 422 no deja nada a medias.
    """
    return servicio.ejecutar(usuario_id, datos)


# =====================================================================
# ESTADO Y SCORE
# =====================================================================

estado = APIRouter(tags=["estado"])


@estado.get("/estado", response_model=EstadoResponse, responses=ERRORES)
def obtener_estado(usuario_id: UsuarioActual, servicio: EstadoDep) -> EstadoResponse:
    """
    La foto completa que consume el motor y pinta el frontend.

    Solo incluye tarjetas de credito activas y con terminos completos: una sin
    limite ni tasa reventaria el motor con un None en una division.
    """
    return servicio.obtener(usuario_id)


score = APIRouter(tags=["score"])


@score.get("/score", response_model=ScoreResponse, responses=ERRORES)
def obtener_score(usuario_id: UsuarioActual, servicio: ScoreDep) -> ScoreResponse:
    """
    El Financial Health Score: cuatro componentes ponderados, de 0 a 100.

    Basado en reglas, no en ML — es auditable y explicable linea por linea.

    OJO con el usuario recien registrado: sin ingresos ni gastos el score sale
    en 70 ("Estable"), que es falsamente tranquilizador. La senal para no
    pintarlo es `onboarding_completo` en GET /auth/me.
    """
    return servicio.obtener(usuario_id)


# =====================================================================
# SIMULADOR
# =====================================================================

simulaciones = APIRouter(prefix="/simulaciones", tags=["simulador"])


@simulaciones.post("/compra", response_model=SimulacionResponse, responses=ERRORES)
def simular_compra(usuario_id: UsuarioActual, datos: SimulacionRequest,
                   servicio: SimulacionDep) -> SimulacionResponse:
    """
    "Me conviene comprar esto?" — la pantalla estrella.

    SOLO LECTURA: no escribe nada. El servicio ni siquiera recibe un repositorio
    de escritura, asi que es imposible por construccion.

    Los meses sin intereses los ofrece EL COMERCIO, no la tarjeta: Liverpool da
    18 con la misma tarjeta con la que la tienda de la esquina no da ninguno.
    Por eso llegan en el cuerpo y no salen de la base.

    **Y no los ofrece igual con todas.** `tarjetas` es la forma buena de
    pedirlo — cada tarjeta con SUS plazos — y cuando viene define ademas que
    tarjetas entran a la comparacion:

        {"monto": 15000, "tarjetas": [
            {"tarjeta_id": "bbva", "plazos": [3, 6, 12]},
            {"tarjeta_id": "nu",   "plazos": []}
         ], "incluir_contado": true}

    `plazos` (una sola lista para todas las tarjetas del usuario) sigue
    funcionando y es lo que se usa cuando `tarjetas` no viene.

    Los escenarios inviables se devuelven marcados con su motivo, no se filtran:
    el frontend los pinta deshabilitados CON la razon visible, que es mas util
    que hacerlos desaparecer.

    Ademas del ranking, la respuesta trae el `veredicto` del motor: si la mejor
    forma de pagar sigue siendo una mala idea, se dice aqui con sus razones
    calculadas — sin pasar por ninguna IA.

    Es POST porque lleva cuerpo, no porque modifique algo.
    """
    return servicio.simular(usuario_id, datos)


# =====================================================================
# DEUDA
# =====================================================================

deuda = APIRouter(prefix="/deuda", tags=["deuda"])


@deuda.get("/prioridad", response_model=DeudaResponse, responses=ERRORES)
def prioridad(usuario_id: UsuarioActual, servicio: DeudaDep) -> DeudaResponse:
    """
    "Que deuda pago primero?" — ranking con sus razones.

    Cada entrada trae `tarjeta_id` ademas del nombre. Antes solo venia el
    nombre, y el frontend tenia que cruzar este ranking contra GET /estado para
    saber a que tarjeta pagar; dos tarjetas del mismo banco rompian ese cruce.
    """
    return servicio.prioridad(usuario_id)


@deuda.post("/pagos", response_model=PagoResponse,
            status_code=status.HTTP_201_CREATED, responses=ERRORES)
def pagar(
    usuario_id: UsuarioActual, datos: PagoRequest, servicio: DeudaDep,
    idempotency_key: Annotated[Optional[str], Depends(get_idempotency_key)] = None,
) -> PagoResponse:
    """
    Registra un pago a tarjeta y dice cuanto se AHORRA al mes en intereses.

    Existe aparte de POST /movimientos porque esa cifra solo tiene sentido aqui:
    el score puede subir un solo punto, pero dejar de pagar $142 al mes se
    entiende sin explicacion. Por dentro escribe el mismo movimiento
    tipo='pago' — no es un camino alterno de escritura — y ademas abona al corte
    pendiente, para que GET /pagos-pendientes no siga pidiendo lo que ya se pago.
    """
    return servicio.pagar(usuario_id, datos, idempotency_key)