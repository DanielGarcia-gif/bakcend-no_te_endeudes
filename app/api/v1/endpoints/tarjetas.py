"""
Tarjetas, planes a meses (MSI) y cortes.

Tres routers delgados sobre el mismo servicio, porque son el mismo agregado
visto desde tres angulos: la tarjeta es el estado de hoy, el periodo es la
obligacion fechada y el MSI es el compromiso a futuro.

La extraccion de un estado de cuenta con IA (POST /tarjetas/{id}/extraccion)
vive en ia.py: es el unico camino de esta familia que sale a internet.
"""

from fastapi import APIRouter, Response, status

from app.dependencies.auth import UsuarioActual
from app.dependencies.providers import TarjetaDep
from app.schemas.comunes import Coleccion
from app.schemas.errores import ErrorResponse
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

ERRORES = {
    401: {"model": ErrorResponse, "description": "Sin token o sesion vencida"},
    404: {"model": ErrorResponse, "description": "No existe o no es tuya"},
    409: {"model": ErrorResponse, "description": "Conflicto de estado"},
    422: {"model": ErrorResponse, "description": "Regla de negocio o validacion"},
}


# =====================================================================
# TARJETAS
# =====================================================================

router = APIRouter(prefix="/tarjetas", tags=["tarjetas"])


@router.get("", response_model=Coleccion[TarjetaResumen], responses=ERRORES)
def listar_tarjetas(usuario_id: UsuarioActual, servicio: TarjetaDep) -> dict:
    """Todas las tarjetas del usuario, cada una con sus planes a meses vigentes."""
    return servicio.listar(usuario_id)


@router.post("", response_model=TarjetaResumen,
             status_code=status.HTTP_201_CREATED, responses=ERRORES)
def crear_tarjeta(usuario_id: UsuarioActual, datos: TarjetaCreate,
                  servicio: TarjetaDep, respuesta: Response) -> TarjetaResumen:
    """
    Alta minima: banco, nombre y tipo. Los terminos de una de credito se
    capturan despues con `PATCH /tarjetas/{id}`; mientras falten, la tarjeta
    sale con `requiere_terminos: true` y no entra al motor.
    """
    creada = servicio.crear(usuario_id, datos)
    respuesta.headers["Location"] = f"/api/v1/tarjetas/{creada.id}"
    return creada


@router.get("/{tarjeta_id}", response_model=TarjetaResumen, responses=ERRORES)
def obtener_tarjeta(usuario_id: UsuarioActual, tarjeta_id: str,
                    servicio: TarjetaDep) -> TarjetaResumen:
    return servicio.obtener(usuario_id, tarjeta_id)


@router.patch("/{tarjeta_id}", response_model=TarjetaResumen, responses=ERRORES)
def actualizar_tarjeta(usuario_id: UsuarioActual, tarjeta_id: str,
                       datos: TarjetaUpdate, servicio: TarjetaDep) -> TarjetaResumen:
    """
    PATCH parcial de los terminos. Manda `version` para no pisar un gasto que
    movio el saldo mientras el formulario estaba abierto: si cambio, 409.
    """
    return servicio.actualizar(usuario_id, tarjeta_id, datos)


@router.delete("/{tarjeta_id}", status_code=status.HTTP_204_NO_CONTENT,
               responses=ERRORES)
def eliminar_tarjeta(usuario_id: UsuarioActual, tarjeta_id: str,
                     servicio: TarjetaDep) -> None:
    """Borrado logico, con rastro en auditoria."""
    servicio.eliminar(usuario_id, tarjeta_id)


@router.get("/{tarjeta_id}/periodos", response_model=Coleccion[PeriodoResumen],
            responses=ERRORES)
def listar_periodos(usuario_id: UsuarioActual, tarjeta_id: str,
                    servicio: TarjetaDep) -> dict:
    return servicio.listar_periodos(usuario_id, tarjeta_id)


@router.post("/{tarjeta_id}/periodos", response_model=PeriodoResumen,
             status_code=status.HTTP_201_CREATED, responses=ERRORES)
def abrir_periodo(usuario_id: UsuarioActual, tarjeta_id: str, datos: PeriodoCreate,
                  servicio: TarjetaDep) -> PeriodoResumen:
    """
    Abre un corte con sus tres fechas reales, tal como vienen en el estado de
    cuenta: los bancos recorren el corte por fines de semana y festivos.
    """
    return servicio.abrir_periodo(usuario_id, tarjeta_id, datos)


@router.post("/{tarjeta_id}/periodos/{periodo_id}/cierre",
             response_model=PeriodoResumen, responses=ERRORES)
def cerrar_periodo(usuario_id: UsuarioActual, tarjeta_id: str, periodo_id: str,
                   servicio: TarjetaDep) -> PeriodoResumen:
    """Congela las cifras del corte. Despues de esto dejan de moverse."""
    return servicio.cerrar_periodo(usuario_id, tarjeta_id, periodo_id)


# =====================================================================
# MSI
# =====================================================================

msi = APIRouter(prefix="/msi", tags=["tarjetas"])


@msi.get("", response_model=Coleccion[MSIResumen], responses=ERRORES)
def listar_msi(usuario_id: UsuarioActual, servicio: TarjetaDep) -> dict:
    """Los planes a meses vigentes de todas las tarjetas."""
    return servicio.listar_msi(usuario_id)


@msi.post("", response_model=MSIResumen,
          status_code=status.HTTP_201_CREATED, responses=ERRORES)
def crear_msi(usuario_id: UsuarioActual, datos: MSICreate, servicio: TarjetaDep,
              respuesta: Response) -> MSIResumen:
    """
    Un plan capturado de un estado de cuenta, sin compra en la app. Para una
    compra NUEVA a meses se usa el bloque `msi` de POST /movimientos.
    """
    creado = servicio.crear_msi(usuario_id, datos)
    respuesta.headers["Location"] = f"/api/v1/msi/{creado.id}"
    return creado


@msi.delete("/{msi_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORES)
def eliminar_msi(usuario_id: UsuarioActual, msi_id: str, servicio: TarjetaDep) -> None:
    servicio.eliminar_msi(usuario_id, msi_id)


# =====================================================================
# PAGOS PENDIENTES
# =====================================================================

pagos_pendientes = APIRouter(tags=["tarjetas"])


@pagos_pendientes.get("/pagos-pendientes", response_model=Coleccion[PagoPendiente],
                      responses=ERRORES)
def listar_pagos_pendientes(usuario_id: UsuarioActual, servicio: TarjetaDep) -> dict:
    """
    El consejo accionable: paga `falta_para_no_intereses` antes de
    `fecha_limite_pago` y la tasa no corre.
    """
    return servicio.pagos_pendientes(usuario_id)
