"""
Router raiz de la API.

Punto unico de montaje: main.py incluye este y nada mas. Cuando exista una v2,
se agrega aqui sin tocar main.py.
"""

from fastapi import APIRouter

from app.api.v1.router import router as router_v1

router = APIRouter()
router.include_router(router_v1)