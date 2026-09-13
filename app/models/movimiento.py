"""
Fila de la tabla `movimientos` — TRANSACCIONAL.

La unica bitacora. Cada fila es un hecho exacto: no hay rangos, no hay
estimaciones, no hay estados "pendiente". Si esta aqui, el dinero se movio.
Lo esperado se deriva al vuelo de las tablas declarativas y solo se materializa
como fila cuando el usuario confirma.

Cambios de fondo respecto a SQLite:

 (1) `medio` EXPLICITO. Antes el medio de pago se INFERIA de
     tarjeta_id IS NULL, que significaba "efectivo O debito" — dos cosas
     distintas que colapsaban en una. Peor: el servicio decidia por req.medio y
     el repositorio por tarjeta_id, asi que la respuesta al usuario y lo que
     quedaba en la base podian contradecirse.

 (2) `categoria_id` FK en vez de texto libre.

 (3) `idempotency_key`. Sin ella, un doble tap o un reintento de la libreria
     HTTP inserta el gasto dos veces y baja el saldo dos veces, sin rastro.
     Con el UNIQUE el segundo intento choca (error 1062) y el servicio
     devuelve el movimiento que YA existe, con 200. El cliente manda un UUID
     por GESTO del usuario, no por request.

 (4) `periodo_id` — un movimiento a credito cae dentro de un corte. Se asigna
     al cerrar el periodo, por eso admite NULL.

 (5) `ingreso_id` / `recurrente_id` — de que declaracion vino este hecho.
     NULL en ingreso_id (con tipo='ingreso') significa ingreso extraordinario:
     aguinaldo, freelance suelto, venta de algo. Sube la liquidez sin inflar
     la capacidad mensual, que es justo lo que debe pasar.

 (6) `eliminado_en` + `motivo_eliminacion`: el borrado es logico. Y borrar no
     es solo marcar la fecha: hay que revertir el efecto sobre el saldo en la
     MISMA transaccion. Un borrado que no revierte es peor que no borrar,
     porque el dato desaparece de la vista pero sigue contando.

ck_mov_coherencia codifica el modelo completo de flujo de dinero:
    gasto   -> tarjeta_id NOT NULL  <=>  medio = 'credito'
    pago    -> tarjeta_id NOT NULL (cual pagas) y medio efectivo/debito (de
               donde salio). Baja saldo_disponible Y baja tarjetas.saldo.
    ingreso -> tarjeta_id NULL y medio efectivo/debito. Sube saldo_disponible.
"""

from dataclasses import dataclass
from typing import Literal

from app.core.conversion import a_fecha_iso, a_float, a_instante_iso

TipoMovimiento = Literal["gasto", "pago", "ingreso"]
MedioMovimiento = Literal["efectivo", "debito", "credito"]


@dataclass(frozen=True, slots=True)
class Movimiento:
    id: int
    usuario_id: int
    tipo: str                       # gasto | pago | ingreso
    medio: str                      # efectivo | debito | credito
    monto: float
    categoria_id: int | None
    descripcion: str | None
    fecha: str                      # 'YYYY-MM-DD'
    tarjeta_id: int | None
    periodo_id: int | None = None
    ingreso_id: int | None = None
    recurrente_id: int | None = None
    idempotency_key: str | None = None
    creado_en: str | None = None
    eliminado_en: str | None = None
    motivo_eliminacion: str | None = None
    # Se rellenan cuando la fila viene de un JOIN.
    categoria_clave: str | None = None
    categoria_nombre: str | None = None
    tarjeta_nombre: str | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "Movimiento":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            tipo=f["tipo"],
            medio=f["medio"],
            monto=a_float(f["monto"]),
            categoria_id=f.get("categoria_id"),
            descripcion=f.get("descripcion"),
            fecha=a_fecha_iso(f["fecha"]),
            tarjeta_id=f.get("tarjeta_id"),
            periodo_id=f.get("periodo_id"),
            ingreso_id=f.get("ingreso_id"),
            recurrente_id=f.get("recurrente_id"),
            idempotency_key=f.get("idempotency_key"),
            creado_en=a_instante_iso(f.get("creado_en")),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
            motivo_eliminacion=f.get("motivo_eliminacion"),
            categoria_clave=f.get("categoria_clave"),
            categoria_nombre=f.get("categoria_nombre"),
            tarjeta_nombre=f.get("tarjeta_nombre"),
        )

    @property
    def es_confirmacion(self) -> bool:
        """Vino de una declaracion (un ingreso o un recurrente), no suelto."""
        return self.ingreso_id is not None or self.recurrente_id is not None