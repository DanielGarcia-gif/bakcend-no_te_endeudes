"""
No te endeudes _ Backend — punto de entrada de la API.

Este archivo solo ENSAMBLA: crea la app, monta el router raiz y registra los
manejadores de error. No tiene logica de negocio, ni consultas, ni calculos.
Todo eso vive en app/services/, app/domain/ y app/repositories/.

    HTTP -> Router -> Schema -> Service -> Motor -> Repository -> MySQL
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import router as api_router
from app.core.config import settings
from app.core.database import verificar_conexion
from app.core.exceptions import DominioError

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):

    info = verificar_conexion()
    log.info("Conectado a MySQL %(mysql)s, base %(base)s, migracion %(migracion)s", info)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    description=(
        "Tu banco te dice si tienes el dinero; nosotros te decimos si "
        "deberias gastarlo. Los numeros salen de un motor de reglas "
        "determinista y auditable."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # El cliente manda Idempotency-Key en los POST que mueven dinero; sin
    # exponerla aqui, el navegador la bloquea antes de que salga el request.
    expose_headers=["Location"],
)


# =====================================================================
# MANEJO DE ERRORES — centralizado
# =====================================================================
# Todos los errores salen con la misma forma:
#     {"error": {"codigo": "...", "mensaje": "...", "detalle": {...}}}
# Gracias a esto los endpoints no llevan un solo try/except.
#
# Antes eso era cierto solo a medias: habia handler para DominioError y para
# los errores de validacion, pero no para el resto. Un 404 de ruta inexistente,
# un 405 por metodo equivocado o cualquier excepcion no capturada salian como
# {"detail": "..."}, sin la clave `error`, y el cliente degradaba en silencio a
# codigo 'desconocido'. Los dos handlers del final cierran ese hueco.

def _respuesta_error(status_code: int, codigo: str, mensaje: str,
                     detalle: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"codigo": codigo, "mensaje": mensaje,
                           "detalle": detalle or {}}},
    )


@app.exception_handler(DominioError)
async def _error_de_dominio(request: Request, exc: DominioError) -> JSONResponse:
    """Cubre toda la jerarquia: no encontrado, regla de negocio, auth, etc."""
    return _respuesta_error(exc.status_code, exc.codigo, exc.mensaje, exc.detalle)


@app.exception_handler(RequestValidationError)
async def _error_de_validacion(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Errores de forma de Pydantic, traducidos a la misma envoltura para que el
    frontend parsee una sola estructura.
    """
    return _respuesta_error(
        422,
        "validacion",
        "Los datos enviados no son validos",
        {"campos": [
            {"campo": ".".join(str(p) for p in e["loc"][1:]), "error": e["msg"]}
            for e in exc.errors()
        ]},
    )


# Codigos para los errores HTTP que no nacen del dominio (ruta o metodo malos).
_CODIGO_POR_ESTADO = {
    401: "no_autenticado",
    403: "prohibido",
    404: "no_encontrado",
    405: "metodo_no_permitido",
    409: "conflicto",
    429: "demasiadas_peticiones",
}


@app.exception_handler(StarletteHTTPException)
async def _error_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    404 de ruta, 405 de metodo y cualquier HTTPException suelta.

    Sin esto, la promesa de "todos los errores tienen la misma forma" era falsa
    justo en los casos que mas ve un frontend en desarrollo.
    """
    return _respuesta_error(
        exc.status_code,
        _CODIGO_POR_ESTADO.get(exc.status_code, "error_http"),
        str(exc.detail),
    )


@app.exception_handler(Exception)
async def _error_no_previsto(request: Request, exc: Exception) -> JSONResponse:
    """
    Ultima red. Registra el detalle en el log y devuelve un mensaje generico:
    un stack trace o un mensaje de MySQL en la respuesta filtra estructura de
    la base a quien sea que este llamando.
    """
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return _respuesta_error(500, "error_interno", "Ocurrio un error inesperado.")


# =====================================================================
# RUTAS
# =====================================================================

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Sonda de vida. Fuera del prefijo versionado y sin tocar la base."""
    return {"ok": True, "version": settings.app_version}