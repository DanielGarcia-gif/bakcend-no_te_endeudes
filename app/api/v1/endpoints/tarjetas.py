"""
POST/GET/DELETE /movimientos — la bitacora.

Sustituye a POST /gastos y absorbe los ingresos extraordinarios. Un movimiento
es un hecho: si esta aqui, el dinero se movio.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.auth import UsuarioActual
from app.dependencies.idempotencia import get_idempotency_key
from app.dependencies.providers import MovimientoDep
from app.schemas.comunes import Borrado, Coleccion
from app.schemas.errores import ErrorResponse
from app.schemas.movimientos import (
    MovimientoCreate,
    MovimientoResponse,
    MovimientoResumen,
)

router = APIRouter(prefix="/movimientos", tags=["movimientos"])

ERRORES = {
    401: {"model": ErrorResponse, "description": "Sin token o sesion vencida"},
    404: {"model": ErrorResponse, "description": "No existe o no es tuyo"},
    409: {"model": ErrorResponse, "description": "Conflicto de estado"},
    422: {"model": ErrorResponse, "description": "Regla de negocio o validacion"},
}


@router.get("", response_model=Coleccion[MovimientoResumen], responses=ERRORES)
def listar(
    usuario_id: UsuarioActual,
    servicio: MovimientoDep,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[Optional[str], Query(
        description="El `siguiente_cursor` de la respuesta anterior. Opaco.",
    )] = None,
    tipo: Annotated[Optional[str], Query(pattern="^(gasto|pago|ingreso)$")] = None,
    medio: Annotated[Optional[str], Query(pattern="^(efectivo|debito|credito)$")] = None,
    categoria: Annotated[Optional[str], Query(description="Clave del catalogo")] = None,
    tarjeta_id: Optional[str] = None,
    desde: Annotated[Optional[str], Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
    hasta: Annotated[Optional[str], Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> dict:
    """
    Historial filtrable, paginado por cursor.

    Cursor y no `page`: es la unica coleccion que crece sin techo, y con OFFSET
    la pagina 50 obliga al motor a leer y descartar 2,450 filas. Ademas, un
    movimiento nuevo mientras el usuario pagina correria el contenido de las
    paginas siguientes y le mostraria filas repetidas.
    """
    return servicio.listar(
        usuario_id, limite=limite, cursor=cursor, tipo=tipo, medio=medio,
        categoria=categoria, tarjeta_id=tarjeta_id, desde=desde, hasta=hasta,
    )


@router.post("", response_model=MovimientoResponse,
             status_code=status.HTTP_201_CREATED, responses=ERRORES)
def registrar(
    usuario_id: UsuarioActual,
    datos: MovimientoCreate,
    servicio: MovimientoDep,
    respuesta: Response,
    idempotency_key: Annotated[Optional[str], Depends(get_idempotency_key)] = None,
) -> MovimientoResponse:
    """
    Registra un movimiento y devuelve su impacto en el score.

    El efecto sobre los saldos va en la misma transaccion:

        gasto   efectivo/debito   baja la liquidez
        gasto   credito           sube el saldo de la tarjeta (la liquidez no se toca)
        pago    efectivo/debito   baja las dos, en direcciones opuestas
        ingreso efectivo/debito   sube la liquidez

    Con `msi`, la compra y su plan a meses nacen juntos y el saldo de la tarjeta
    sube por el TOTAL, no por la mensualidad: el banco presto el total, y la
    utilizacion es el 20% del score.

    Manda `Idempotency-Key` en los reintentos. Si esa clave ya se uso, la
    respuesta es **200** con el movimiento existente y `repetido: true`, y el
    saldo NO se mueve por segunda vez.
    """
    resultado = servicio.registrar(usuario_id, datos, idempotency_key)
    if resultado.repetido:
        # 200, no 201: no se creo nada. Es la diferencia entre "ya estaba" y
        # "acabo de crearlo", y el cliente la necesita para no descontar dos
        # veces en su UI optimista.
        respuesta.status_code = status.HTTP_200_OK
    else:
        respuesta.headers["Location"] = f"/api/v1/movimientos/{resultado.movimiento.id}"
    return resultado


@router.get("/{movimiento_id}", response_model=MovimientoResumen, responses=ERRORES)
def obtener(usuario_id: UsuarioActual, movimiento_id: str,
            servicio: MovimientoDep) -> MovimientoResumen:
    return servicio.obtener(usuario_id, movimiento_id)


@router.delete("/{movimiento_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses=ERRORES)
def eliminar(usuario_id: UsuarioActual, movimiento_id: str, datos: Borrado,
             servicio: MovimientoDep) -> None:
    """
    Borrado logico que REVIERTE su efecto sobre los saldos.

    La fila no se borra: queda con `eliminado_en` y `motivo_eliminacion`, y deja
    rastro en auditoria. Un borrado que no revierte es peor que no borrar,
    porque el dato desaparece de la vista pero el saldo sigue movido.
    """
    servicio.eliminar(usuario_id, movimiento_id, datos.motivo)