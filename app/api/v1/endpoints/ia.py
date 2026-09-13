"""
Los tres endpoints que pasan por Gemini.

Van en su propio archivo, y no dentro de `tarjetas.py` y `consulta.py`, porque
son los unicos del sistema que salen a internet: si algun dia hay que meterles
un limite de peticiones, una cola o una metrica de costo, se ve de un vistazo
cuales son.

Los tres EXIGEN SESION. Sin `UsuarioActual` esto seria un proxy abierto a la
cuota de Gemini de quien despliegue la app.

Y los tres son PRESCINDIBLES por diseno: si este archivo entero devolviera 503,
la app sigue funcionando. Los terminos se capturan a mano, el ranking de deuda
se lee con sus razones calculadas y el simulador sigue recomendando y
advirtiendo con el veredicto del motor. Lo que se pierde es la prosa.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.dependencies.auth import UsuarioActual
from app.dependencies.providers import IADep
from app.schemas.errores import ErrorResponse
from app.schemas.ia import (
    AnalisisCompraResponse,
    ExplicacionDeudaResponse,
    ExtraccionResponse,
    ModoPago,
)
from app.schemas.simulacion import SimulacionRequest

ERRORES = {
    401: {"model": ErrorResponse, "description": "Sin token o sesion vencida"},
    404: {"model": ErrorResponse, "description": "No existe o no es tuya"},
    422: {"model": ErrorResponse, "description": "El archivo no sirve"},
    503: {"model": ErrorResponse, "description": "Gemini no esta disponible"},
}


# =====================================================================
# EXTRACCION DE ESTADO DE CUENTA
# =====================================================================

extraccion = APIRouter(prefix="/tarjetas", tags=["ia"])


@extraccion.post("/{tarjeta_id}/extraccion", response_model=ExtraccionResponse,
                 responses=ERRORES)
async def extraer(
    usuario_id: UsuarioActual,
    tarjeta_id: str,
    servicio: IADep,
    archivo: Annotated[UploadFile, File(description="El estado de cuenta, en PDF")],
    modo: Annotated[ModoPago, Form(
        description="Como paga la persona esta tarjeta. Decide cual de los dos "
                    "pagos impresos se prellena; los dos viajan en la respuesta."
    )] = "minimo",
) -> ExtraccionResponse:
    """
    Lee un estado de cuenta y devuelve los terminos listos para el formulario.

    **No persiste nada.** Lo que dice el modelo prellena la pantalla; entra a la
    base cuando la persona guarda con `PATCH /tarjetas/{id}`, y los planes a
    meses con `POST /msi`.

    Multipart y no JSON: el PDF viaja como archivo, sin el 33% que le agregaria
    codificarlo en base64.

    Errores que se ven seguido:
    - **422** si no es un PDF, si pesa mas de 15 MB o si viene protegido con
      contrasena (el mensaje dice que hacer en cada caso).
    - **503** si el servidor no tiene llave de Gemini o el modelo no contesto.
      No es fatal: la captura manual del formulario nunca dependio de esto.
    """
    # Se lee entero a memoria a proposito: el tope son 15 MB y de aqui va
    # derecho al cuerpo de la peticion a Gemini.
    contenido = await archivo.read()
    # Al threadpool: el SDK de Google es sincrono y la llamada tarda decenas de
    # segundos. Hacerla aqui dentro congelaria el event loop, o sea la API
    # entera, mientras se lee un PDF de una sola persona. El endpoint tiene que
    # seguir siendo async por el `await archivo.read()` de arriba.
    return await run_in_threadpool(
        servicio.extraer_estado_de_cuenta,
        usuario_id, tarjeta_id, contenido, archivo.content_type, modo,
    )


# =====================================================================
# EXPLICACION DE LA PRIORIDAD DE DEUDA
# =====================================================================

explicacion = APIRouter(prefix="/deuda", tags=["ia"])


@explicacion.get("/explicacion", response_model=ExplicacionDeudaResponse,
                 responses=ERRORES)
def explicar(usuario_id: UsuarioActual, servicio: IADep) -> ExplicacionDeudaResponse:
    """
    El ranking de `GET /deuda/prioridad`, contado en espanol llano.

    **Sin cuerpo.** El ranking se recalcula aqui adentro: antes el frontend
    subia el `DeudaResponse` completo para que se lo explicaran, lo que gastaba
    red y dejaba que el cliente eligiera sobre que numeros se redacta.

    Es adorno, no dato: cada cifra del texto salio del motor determinista. Si
    esto devuelve 503, la pantalla de deuda se pinta igual con el ranking y sus
    razones calculadas.
    """
    return servicio.explicar_prioridad(usuario_id)


# =====================================================================
# ANALISIS PROFUNDO DE UNA COMPRA
# =====================================================================

analisis = APIRouter(prefix="/simulaciones", tags=["ia"])


@analisis.post("/analisis", response_model=AnalisisCompraResponse, responses=ERRORES)
async def analizar(usuario_id: UsuarioActual, datos: SimulacionRequest,
                   servicio: IADep) -> AnalisisCompraResponse:
    """
    "Y esto, ¿por que me conviene asi?" — la simulacion, contada.

    **Mismo cuerpo que POST /simulaciones/compra**, y a proposito: la simulacion
    se rehace en el servidor en vez de recibir los escenarios ya calculados. Si
    el cliente los subiera, seria el cliente quien decide sobre que numeros se
    redacta, y mandar una lista recortada bastaria para conseguir la explicacion
    que uno quiera.

    Al modelo le llega LA MEJOR OPCION DE CADA TARJETA mas el contado, con los
    campos etiquetados —el efectivo y la linea de credito no se comparan entre
    si— y el veredicto que ya calculo el motor. Gemini redacta, contrasta y
    categoriza el articulo; NO decide si la compra es sana.

    **No persiste nada.** Si la persona decide comprar, eso es otra peticion:
    POST /movimientos con la modalidad que eligio.

    **503** si el servidor no tiene llave de Gemini o el modelo no contesto. No
    es fatal: POST /simulaciones/compra ya trae el veredicto y sus razones, y la
    pantalla se pinta entera sin este endpoint.

    Es POST porque lleva cuerpo, no porque modifique algo.
    """
    # Al threadpool, como la extraccion: el SDK de Google es sincrono y esta
    # llamada tarda segundos. Hacerla en el event loop congelaria la API entera
    # mientras se le explica una compra a una sola persona.
    return await run_in_threadpool(servicio.analizar_compra, usuario_id, datos)