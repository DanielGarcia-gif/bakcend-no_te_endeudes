"""
Fila de la tabla `usuarios`.

Sin ORM, por decision cerrada del briefing: estas dataclasses son el espejo
tipado de la fila que devuelve el cursor. Aislan al resto del codigo de los
nombres de columna y le dan autocompletado a los repositorios.

Aqui ocurre la conversion de tipos de MySQL: DECIMAL -> float y DATETIME ->
str ISO. Ver app/core/conversion.py para el porque. A partir de esta frontera
el resto de la app trabaja con los tipos de siempre.

No llevan comportamiento: la logica de negocio vive en app/domain/.
"""

from dataclasses import dataclass

from app.core.conversion import a_bool, a_float, a_instante_iso


@dataclass(frozen=True, slots=True)
class Usuario:
    id: int
    nombre: str
    email: str
    password_hash: str
    # Efectivo + banco + debito en un solo numero. Es lo que la persona puede
    # gastar hoy y se actualiza en la misma transaccion que cada movimiento.
    saldo_disponible: float
    es_demo: bool
    # Contador de bloqueo optimista. Un UPDATE que lleve `AND version = %s` y
    # afecte 0 filas significa que alguien escribio primero.
    version: int
    creado_en: str
    actualizado_en: str | None = None
    eliminado_en: str | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "Usuario":
        return cls(
            id=f["id"],
            nombre=f["nombre"],
            email=f["email"],
            password_hash=f["password_hash"],
            saldo_disponible=a_float(f["saldo_disponible"]),
            es_demo=a_bool(f["es_demo"]),
            version=f.get("version", 0),
            creado_en=a_instante_iso(f["creado_en"]),
            actualizado_en=a_instante_iso(f.get("actualizado_en")),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
        )

    @property
    def esta_vivo(self) -> bool:
        return self.eliminado_en is None