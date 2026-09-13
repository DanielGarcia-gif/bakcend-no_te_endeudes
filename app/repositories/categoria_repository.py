"""
SQL de la tabla `categorias`.

Repositorio nuevo. Antes no existia porque `categoria` era texto libre en dos
tablas que ya habian divergido: `movimientos` guardaba
Comida/Compras/Entretenimiento/Salud/Transporte y `recurrentes` guardaba
Servicios/Transporte/Entretenimiento. La lista CATEGORIAS vivia en tipos.py y
no la validaba nadie, asi que cualquier cadena entraba y agrupar gastos por
categoria daba un resultado distinto segun quien hubiera capturado.

Son 10 filas inmutables que se consultan en cada gasto, asi que el catalogo se
cachea a nivel de proceso. La cache es segura porque las categorias son parte
del esquema (las inserta la migracion 001), no datos de usuario: nadie las crea
ni las borra en caliente.
"""

from app.core.exceptions import ReglaDeNegocioViolada
from app.models.categoria import Categoria
from app.repositories.base import MySQLRepository

# Cache de proceso. Se llena una vez y sobrevive a los requests.
_catalogo: list[Categoria] | None = None


class CategoriaRepository(MySQLRepository):

    def listar(self) -> list[Categoria]:
        global _catalogo
        if _catalogo is None:
            filas = self._todos(
                "SELECT id, clave, nombre, activa FROM categorias"
                " WHERE activa = 1 ORDER BY id"
            )
            _catalogo = [Categoria.desde_fila(f) for f in filas]
        return _catalogo

    def por_clave(self, clave: str) -> Categoria | None:
        objetivo = (clave or "").strip().lower()
        return next((c for c in self.listar() if c.clave == objetivo), None)

    def por_id(self, categoria_id: int) -> Categoria | None:
        return next((c for c in self.listar() if c.id == categoria_id), None)

    def resolver(self, clave: str | None, obligatoria: bool = True) -> int | None:
        """
        Traduce la clave que manda el cliente ('comida') al id que guarda la
        base. Un 422 con la lista de claves validas es mucho mas util que un
        error 1452 de clave foranea saliendo del driver.
        """
        if clave is None or str(clave).strip() == "":
            if obligatoria:
                raise ReglaDeNegocioViolada(
                    "Falta la categoria.",
                    {"validas": [c.clave for c in self.listar()]},
                )
            return None

        categoria = self.por_clave(str(clave))
        if categoria is None:
            raise ReglaDeNegocioViolada(
                f"La categoria '{clave}' no existe.",
                {"validas": [c.clave for c in self.listar()]},
            )
        return categoria.id


def limpiar_cache() -> None:
    """Para los tests, que crean y destruyen la base entre sesiones."""
    global _catalogo
    _catalogo = None