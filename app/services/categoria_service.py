"""
Caso de uso: GET /categorias — el catalogo.

Es delgado a proposito. Existe como servicio y no como una llamada directa del
endpoint al repositorio para que la regla siga valiendo sin excepciones: los
routers no conocen repositorios. Una excepcion "porque este es facil" es como
empiezan las capas que no se respetan.
"""

from app.repositories.categoria_repository import CategoriaRepository
from app.schemas.comunes import coleccion
from app.schemas.consultas import CategoriaResumen


class CategoriaService:

    def __init__(self, categoria_repository: CategoriaRepository):
        self.categorias = categoria_repository

    def listar(self) -> dict:
        """
        Las claves validas para `categoria` en gastos y recurrentes.

        El frontend las pide una vez y arma su selector con ellas. Antes esta
        lista vivia duplicada en tipos.py y en tipos.ts, no la validaba nadie, y
        las dos tablas que la usaban ya habian divergido.
        """
        filas = self.categorias.listar()
        return coleccion(
            [CategoriaResumen(id=str(c.id), clave=c.clave, nombre=c.nombre)
             for c in filas],
            total=len(filas),
        )