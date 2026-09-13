"""
Fila de la tabla `categorias`.

Tabla nueva. Antes `categoria` era texto libre en dos tablas que ya habian
divergido: `movimientos` usaba Comida/Compras/Entretenimiento/Salud/Transporte
y `recurrentes` usaba Servicios/Transporte/Entretenimiento. La lista CATEGORIAS
existia en tipos.py pero no la validaba nadie, asi que cualquier cadena entraba
y agrupar gastos por categoria daba resultados distintos segun quien capturo.

Ahora es un catalogo con FK: `movimientos.categoria_id` y
`recurrentes.categoria_id` apuntan aqui, y ck_mov_categoria exige que todo
gasto tenga una.

Son 10 filas inmutables. El repositorio las cachea: se consultan en cada gasto
y no cambian.
"""

from dataclasses import dataclass

from app.core.conversion import a_bool


@dataclass(frozen=True, slots=True)
class Categoria:
    id: int
    clave: str      # 'comida' — estable, es lo que manda el cliente
    nombre: str     # 'Comida' — para mostrar
    activa: bool

    @classmethod
    def desde_fila(cls, f: dict) -> "Categoria":
        return cls(
            id=f["id"],
            clave=f["clave"],
            nombre=f["nombre"],
            activa=a_bool(f.get("activa", 1)),
        )