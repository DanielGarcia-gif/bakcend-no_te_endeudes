"""
Piezas compartidas del contrato HTTP.

CONVENCIONES DE /api/v1, en un solo sitio para que no se decidan tres veces:

  Coleccion       {"data": [...], "meta": {...}}
                  El sobre existe porque una lista desnuda no tiene donde
                  colgar la paginacion, y anadirla despues obliga a un cambio
                  incompatible. Con `meta` presente desde el principio, agregar
                  un total o un cursor no rompe a nadie.

  Recurso         objeto plano, sin sobre. Un GET de un movimiento devuelve el
                  movimiento; envolverlo en {"data": {...}} solo agrega una
                  indireccion que el cliente tiene que deshacer.

  Error           {"error": {"codigo", "mensaje", "detalle"}}, SIEMPRE, para
                  los cuatro digitos y para los cinco. Lo arma main.py.

  Ids             string, todos. `movimientos.id` es BIGINT UNSIGNED y en
                  JavaScript los enteros dejan de ser exactos pasados los 2^53;
                  y antes el contrato mezclaba int y str para la misma clase de
                  dato segun el endpoint.

  Dinero          number con 2 decimales. Decimal vive dentro del backend (ver
                  app/core/conversion.py) y no cruza el cable: los montos de
                  esta app caben de sobra en un float64.

  Fechas          date -> "YYYY-MM-DD", datetime -> ISO-8601 con T y Z.
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class MetaPagina(BaseModel):
    """
    Paginacion por cursor, no por offset.

    Con OFFSET, la pagina 50 obliga al motor a leer y descartar 2,450 filas, y
    una insercion concurrente corre el contenido de las paginas siguientes. El
    cursor es (fecha, id) —exactamente el orden de ix_mov_usuario_fecha— asi que
    la consulta cuesta lo mismo en la pagina 1 que en la 500 y es estable.

    El cursor es opaco a proposito: el cliente lo devuelve tal cual y no debe
    interpretarlo.
    """
    hay_mas: bool = False
    siguiente_cursor: Optional[str] = None
    total: Optional[int] = None


class Coleccion(BaseModel, Generic[T]):
    data: list[T]
    meta: MetaPagina = Field(default_factory=MetaPagina)


def coleccion(items: list, hay_mas: bool = False,
              siguiente_cursor: str | None = None,
              total: int | None = None) -> dict:
    """Arma el sobre. Que lo haga una funcion evita 12 dicts a mano."""
    return {
        "data": items,
        "meta": {"hay_mas": hay_mas, "siguiente_cursor": siguiente_cursor,
                 "total": total},
    }


class Borrado(BaseModel):
    """
    Cuerpo de un DELETE.

    El motivo es obligatorio y no es burocracia: el borrado es logico y queda en
    `motivo_eliminacion` y en la auditoria. Cuando alguien revise por que un
    saldo no cuadra, "capturado dos veces" contra "no se sabe" es la diferencia
    entre entenderlo y no.
    """
    motivo: str = Field(min_length=3, max_length=160)


class Confirmacion(BaseModel):
    """
    Respuesta de una accion que no devuelve recurso.

    `score_actualizado` va aqui porque cada escritura que mueve dinero cambia el
    score, y el frontend lo muestra en la barra superior: sin esto tendria que
    pedir GET /score detras de cada POST.
    """
    ok: bool = True
    score_actualizado: Optional[int] = None