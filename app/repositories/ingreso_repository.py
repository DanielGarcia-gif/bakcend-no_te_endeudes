"""
SQL de la tabla `ingresos` — DECLARATIVA.

Una foto del mundo del usuario ("gano 6,000 quincenales"), no historia. Los
cobros reales viven en `movimientos` con `ingreso_id` apuntando aqui.

NO EXISTE `ultimo_pago_confirmado`, y es deliberado: se deriva.

    SELECT MAX(fecha) FROM movimientos
     WHERE ingreso_id = ? AND usuario_id = ? AND eliminado_en IS NULL

Guardarlo como columna significaria mantenerlo al dia en cada alta, cada
borrado y cada correccion de un movimiento, y bastaria con olvidarlo en un solo
camino para que el calendario se desincronizara sin que nadie lo notara. Como
derivado, es imposible que mienta.

Ese MAX es lo que `ultimo_confirmado()` devuelve, y con el
app/domain/calendario.py reancla el ciclo: cada confirmacion del usuario
resincroniza el calendario con la realidad del banco.
"""

from app.core.conversion import a_dinero
from app.core.exceptions import RecursoNoEncontrado
from app.models.ingreso import Ingreso
from app.repositories.base import MySQLRepository

CAMPOS = ("id, usuario_id, concepto, monto, frecuencia, dia_pago, dia_pago_2,"
          " fecha_ancla, ajuste_mes_corto, activo, creado_en, actualizado_en,"
          " eliminado_en")


class IngresoRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def listar(self, usuario_id: int, solo_activos: bool = True) -> list[Ingreso]:
        sql = (f"SELECT {CAMPOS} FROM ingresos"
               " WHERE usuario_id = %s AND eliminado_en IS NULL")
        if solo_activos:
            sql += " AND activo = 1"
        sql += " ORDER BY id"
        return [Ingreso.desde_fila(f) for f in self._todos(sql, (usuario_id,))]

    def obtener(self, ingreso_id: int, usuario_id: int) -> Ingreso:
        """
        Siempre con usuario_id. No es defensa en profundidad decorativa: es lo
        que convierte "la tarjeta de otro" en un 404 en vez de en una lectura.
        """
        fila = self._uno(
            f"SELECT {CAMPOS} FROM ingresos"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (ingreso_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Ingreso no encontrado.")
        return Ingreso.desde_fila(fila)

    def ultimo_confirmado(self, ingreso_id: int, usuario_id: int):
        """
        La fecha del ultimo cobro que el usuario confirmo, o None.

        Sustituye a la columna que no existe. Devuelve un date, que es lo que
        consume app/domain/calendario.py para reanclar el ciclo.
        """
        return self._escalar(
            "SELECT MAX(fecha) FROM movimientos"
            " WHERE ingreso_id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (ingreso_id, usuario_id),
        )

    def ultimos_confirmados(self, usuario_id: int) -> dict[int, object]:
        """
        Lo mismo para todos los ingresos del usuario, en UNA consulta.

        Armar el estado pedia una consulta por ingreso; con esto es una sola.
        """
        filas = self._todos(
            "SELECT ingreso_id, MAX(fecha) AS ultimo FROM movimientos"
            " WHERE usuario_id = %s AND ingreso_id IS NOT NULL"
            " AND eliminado_en IS NULL GROUP BY ingreso_id",
            (usuario_id,),
        )
        return {f["ingreso_id"]: f["ultimo"] for f in filas}

    # --- escritura ----------------------------------------------------------

    def crear(self, usuario_id: int, concepto: str, monto: float,
              frecuencia: str, dia_pago: int | None = None,
              dia_pago_2: int | None = None, fecha_ancla=None,
              ajuste_mes_corto: str = "ultimo_dia") -> int:
        """
        ck_ingresos_ancla exige fecha_ancla en semanal/catorcenal y dia_pago en
        quincenal/mensual. Si falta, sale un 422 con el mensaje de
        MENSAJE_POR_CHECK, no un 500.
        """
        return self._insertar(
            "INSERT INTO ingresos"
            " (usuario_id, concepto, monto, frecuencia, dia_pago, dia_pago_2,"
            "  fecha_ancla, ajuste_mes_corto)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (usuario_id, concepto, a_dinero(monto), frecuencia,
             dia_pago, dia_pago_2, fecha_ancla, ajuste_mes_corto),
        )

    def actualizar(self, ingreso_id: int, usuario_id: int, cambios: dict) -> int:
        """
        PATCH parcial: solo escribe las columnas que vienen en `cambios`.

        Un PUT que exige el objeto completo obliga al cliente a reenviar campos
        que no toco, y ahi es donde se pierden datos cuando el formulario no
        traia alguno.
        """
        permitidas = {
            "concepto", "monto", "frecuencia", "dia_pago", "dia_pago_2",
            "fecha_ancla", "ajuste_mes_corto", "activo",
        }
        campos, valores = [], []
        for clave, valor in cambios.items():
            if clave not in permitidas:
                continue
            campos.append(f"{clave} = %s")
            valores.append(a_dinero(valor) if clave == "monto" else valor)

        if not campos:
            return 0
        valores += [ingreso_id, usuario_id]
        return self._ejecutar(
            f"UPDATE ingresos SET {', '.join(campos)}"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            tuple(valores),
        )

    def eliminar_logico(self, ingreso_id: int, usuario_id: int) -> int:
        """
        Borrado logico. Los movimientos ya confirmados NO se tocan: son hechos
        que ocurrieron, y su ingreso_id queda en NULL por el ON DELETE SET NULL
        solo si algun dia se borrara de verdad la fila. Aqui no se borra.
        """
        return self._ejecutar(
            "UPDATE ingresos SET eliminado_en = NOW(), activo = 0"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (ingreso_id, usuario_id),
        )