"""
Router de la version 1 de la API.

Agrega los routers de cada dominio. Donde se montan lo decide
settings.api_prefix (/api/v1), no este archivo.

EL ORDEN IMPORTA EN UN CASO: `movimientos` va antes que nada que pueda declarar
una ruta con parametro en la raiz, porque FastAPI resuelve por orden de registro
y `/movimientos/{id}` no debe capturar peticiones de otro recurso.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import consulta, declarativas, ia, movimientos, tarjetas

router = APIRouter()

# --- sesion, catalogo y captura inicial ---
router.include_router(consulta.auth)
router.include_router(consulta.usuarios)
router.include_router(consulta.categorias)
router.include_router(consulta.onboarding)

# --- declarativas: lo que el usuario declara que se repite ---
router.include_router(declarativas.ingresos)
router.include_router(declarativas.recurrentes)
router.include_router(declarativas.pendientes)

# --- tarjetas, planes a meses y cortes ---
router.include_router(tarjetas.router)
# router.include_router(tarjetas.msi)
# router.include_router(tarjetas.pagos_pendientes)

# POST /tarjetas/{id}/extraccion. Va con las tarjetas aunque viva en ia.py:
# lo que cuelga de la ruta es la tarjeta, no la IA.
router.include_router(ia.extraccion)

# --- transaccional: la bitacora ---
router.include_router(movimientos.router)

# --- consulta y decision ---
router.include_router(consulta.estado)
router.include_router(consulta.score)
router.include_router(consulta.simulaciones)
# POST /simulaciones/analisis. Va con el simulador aunque viva en ia.py: lo que
# analiza es una simulacion. Despues de consulta.simulaciones, aunque aqui da
# igual: ninguno de los dos declara un parametro de ruta que capture al otro.
router.include_router(ia.analisis)
router.include_router(consulta.deuda)
# GET /deuda/explicacion. Despues de /deuda/prioridad, aunque aqui da igual:
# ninguno de los dos declara un parametro de ruta que pueda capturar al otro.
router.include_router(ia.explicacion)