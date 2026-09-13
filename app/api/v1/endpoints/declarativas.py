"""
Los recursos DECLARATIVOS: ingresos, gastos recurrentes y pendientes.

    declaracion  ->  el usuario confirma  ->  movimiento

`/confirmaciones` es un sub-recurso y no un verbo (`/confirmar`) a proposito:
confirmar CREA algo — un movimiento — asi que es un POST a una coleccion, y por
eso responde 201 con Location. Un `/confirmar` seria una accion sin recurso, y
aqui si lo hay.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.auth import UsuarioActual
from app.dependencies.idempotencia import get_idempotency_key
from app.dependencies.providers import IngresoDep, PendientesDep, RecurrenteDep
from app.schemas.comunes import Coleccion, Confirmacion
from app.schemas.declarativas import (
    ConfirmacionCreate,
    IngresoCreate,
    IngresoResumen,
    IngresoUpdate,
    PendientesResponse,
    RecurrenteCreate,
    RecurrenteHistorial,
    RecurrenteResumen,
    RecurrenteUpdate,
)
from app.schemas.errores import ErrorResponse

ERRORES = {
    401: {"model": ErrorResponse, "description": "Sin token o sesion vencida"},
    404: {"model": ErrorResponse, "description": "No existe o no es tuyo"},
    409: {"model": ErrorResponse, "description": "Conflicto de estado"},
    422: {"model": ErrorResponse, "description": "Regla de negocio o validacion"},
}


# =====================================================================
# INGRESOS
# =====================================================================

ingresos = APIRouter(prefix="/ingresos", tags=["ingresos"])


@ingresos.get("", response_model=Coleccion[IngresoResumen], responses=ERRORES)
def listar_ingresos(usuario_id: UsuarioActual, servicio: IngresoDep) -> dict:
    """
    Las fuentes de ingreso recurrente.

    `ultimo_cobro` y `proximo_cobro` son DERIVADOS, no columnas: el primero sale
    de MAX(movimientos.fecha) y el segundo del calendario aplicado sobre el.
    Guardarlos obligaria a mantenerlos al dia en cada alta, borrado y correccion
    de un movimiento, y bastaria olvidarlo en un camino para que mintieran.
    """
    return servicio.listar(usuario_id)


@ingresos.post("", response_model=IngresoResumen,
               status_code=status.HTTP_201_CREATED, responses=ERRORES)
def crear_ingreso(usuario_id: UsuarioActual, datos: IngresoCreate,
                  servicio: IngresoDep, respuesta: Response) -> IngresoResumen:
    """
    Declara una fuente de ingreso RECURRENTE.

    Un ingreso extraordinario (aguinaldo, un freelance suelto, la venta de algo)
    NO va aqui: va a POST /movimientos con tipo=ingreso. Si estuviera aqui, la
    proyeccion lo trataria como capacidad mensual permanente y un aguinaldo de
    $15,000 haria creer al sistema que el usuario gana eso cada mes, para
    siempre.
    """
    creado = servicio.crear(usuario_id, datos)
    respuesta.headers["Location"] = f"/api/v1/ingresos/{creado.id}"
    return creado


@ingresos.get("/{ingreso_id}", response_model=IngresoResumen, responses=ERRORES)
def obtener_ingreso(usuario_id: UsuarioActual, ingreso_id: str,
                    servicio: IngresoDep) -> IngresoResumen:
    return servicio.obtener(usuario_id, ingreso_id)


@ingresos.patch("/{ingreso_id}", response_model=IngresoResumen, responses=ERRORES)
def actualizar_ingreso(usuario_id: UsuarioActual, ingreso_id: str,
                       datos: IngresoUpdate, servicio: IngresoDep) -> IngresoResumen:
    """PATCH y no PUT: solo se escribe lo que viene en el cuerpo."""
    return servicio.actualizar(usuario_id, ingreso_id, datos)


@ingresos.delete("/{ingreso_id}", status_code=status.HTTP_204_NO_CONTENT,
                 responses=ERRORES)
def eliminar_ingreso(usuario_id: UsuarioActual, ingreso_id: str,
                     servicio: IngresoDep) -> None:
    """
    Borrado logico. Los cobros ya confirmados NO se tocan: son hechos que
    ocurrieron y siguen explicando de donde salio el dinero del pasado.
    """
    servicio.eliminar(usuario_id, ingreso_id)


@ingresos.post("/{ingreso_id}/confirmaciones", response_model=Confirmacion,
               status_code=status.HTTP_201_CREATED, responses=ERRORES)
def confirmar_ingreso(
    usuario_id: UsuarioActual, ingreso_id: str, datos: ConfirmacionCreate,
    servicio: IngresoDep, respuesta: Response,
    idempotency_key: Annotated[Optional[str], Depends(get_idempotency_key)] = None,
) -> Confirmacion:
    """
    "Si, me pagaron." Materializa el movimiento y sube la liquidez.

    Ademas resincroniza el calendario: el proximo cobro se cuenta desde esta
    fecha, no desde la `fecha_ancla` original, asi que el ciclo deja de derivar.
    """
    resultado = servicio.confirmar(usuario_id, ingreso_id, datos, idempotency_key)
    respuesta.headers["Location"] = f"/api/v1/movimientos/{resultado['movimiento_id']}"
    return Confirmacion(ok=True, score_actualizado=resultado["score_actualizado"])


# =====================================================================
# RECURRENTES
# =====================================================================

recurrentes = APIRouter(prefix="/recurrentes", tags=["recurrentes"])


@recurrentes.get("", response_model=Coleccion[RecurrenteResumen], responses=ERRORES)
def listar_recurrentes(usuario_id: UsuarioActual, servicio: RecurrenteDep) -> dict:
    """
    Los gastos fijos.

    `peso_mensual` viene amortizado: una luz de $900 bimestral pesa $450. Es la
    cifra para "cuanto de mi ingreso se va en obligaciones" y la INCORRECTA para
    "me alcanza este mes" — para eso esta GET /pendientes, donde sale completa.
    """
    return servicio.listar(usuario_id)


@recurrentes.post("", response_model=RecurrenteResumen,
                  status_code=status.HTTP_201_CREATED, responses=ERRORES)
def crear_recurrente(usuario_id: UsuarioActual, datos: RecurrenteCreate,
                     servicio: RecurrenteDep,
                     respuesta: Response) -> RecurrenteResumen:
    """
    Declara un gasto fijo. No mueve ningun saldo: es una declaracion.

    Recurso nuevo. Antes esto se hacia de refilon con `POST /gastos` y
    `tipo=recurrente`, donde la misma cadena servia como concepto Y como
    categoria, y no se podia listar, editar ni borrar lo declarado.
    """
    creado = servicio.crear(usuario_id, datos)
    respuesta.headers["Location"] = f"/api/v1/recurrentes/{creado.id}"
    return creado


@recurrentes.get("/{recurrente_id}", response_model=RecurrenteResumen,
                 responses=ERRORES)
def obtener_recurrente(usuario_id: UsuarioActual, recurrente_id: str,
                       servicio: RecurrenteDep) -> RecurrenteResumen:
    return servicio.obtener(usuario_id, recurrente_id)


@recurrentes.patch("/{recurrente_id}", response_model=RecurrenteResumen,
                   responses=ERRORES)
def actualizar_recurrente(usuario_id: UsuarioActual, recurrente_id: str,
                          datos: RecurrenteUpdate,
                          servicio: RecurrenteDep) -> RecurrenteResumen:
    return servicio.actualizar(usuario_id, recurrente_id, datos)


@recurrentes.delete("/{recurrente_id}", status_code=status.HTTP_204_NO_CONTENT,
                    responses=ERRORES)
def eliminar_recurrente(usuario_id: UsuarioActual, recurrente_id: str,
                        servicio: RecurrenteDep) -> None:
    servicio.eliminar(usuario_id, recurrente_id)


@recurrentes.get("/{recurrente_id}/historial", response_model=RecurrenteHistorial,
                 responses=ERRORES)
def historial_recurrente(usuario_id: UsuarioActual, recurrente_id: str,
                         servicio: RecurrenteDep) -> RecurrenteHistorial:
    """
    El rango REAL de un gasto variable, sacado de los ultimos 6 pagos.

    Por eso `es_variable` no guarda un rango min/max: el usuario estima mal su
    propio rango, y con tres recibos ya hay datos que le ganan a esa memoria.
    """
    return servicio.historial(usuario_id, recurrente_id)


@recurrentes.post("/{recurrente_id}/confirmaciones", response_model=Confirmacion,
                  status_code=status.HTTP_201_CREATED, responses=ERRORES)
def confirmar_recurrente(
    usuario_id: UsuarioActual, recurrente_id: str, datos: ConfirmacionCreate,
    servicio: RecurrenteDep, respuesta: Response,
    idempotency_key: Annotated[Optional[str], Depends(get_idempotency_key)] = None,
) -> Confirmacion:
    """
    "Si, ya pague la luz." Materializa el gasto con su categoria heredada.

    En un recurrente VARIABLE el `monto` es obligatorio y devuelve 422 si falta:
    el monto de la luz no existe hasta que llega el recibo, asi que no hay nada
    que dar por sentado.
    """
    resultado = servicio.confirmar(usuario_id, recurrente_id, datos, idempotency_key)
    respuesta.headers["Location"] = f"/api/v1/movimientos/{resultado['movimiento_id']}"
    return Confirmacion(ok=True, score_actualizado=resultado["score_actualizado"])


# =====================================================================
# PENDIENTES
# =====================================================================

pendientes = APIRouter(tags=["pendientes"])


@pendientes.get("/pendientes", response_model=PendientesResponse, responses=ERRORES)
def listar_pendientes(
    usuario_id: UsuarioActual, servicio: PendientesDep,
    dias: Annotated[int, Query(ge=1, le=90)] = 30,
) -> PendientesResponse:
    """
    Lo que toca y aun no se ha confirmado.

    NO lee ninguna tabla de pendientes: no existe. Cruza las declaraciones
    contra los movimientos que ya hay y devuelve la resta. Materializarlos
    obligaria a un proceso que los genere, a decidir que pasa con los que nadie
    confirma, y a limpiar los que quedaron con datos viejos.

    Los montos vienen COMPLETOS, no amortizados: la pregunta aqui es "me alcanza
    este mes", y la luz bimestral llega entera el mes que toca.
    """
    return servicio.listar(usuario_id, dias)