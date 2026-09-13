"""
SQL de la tabla `msi_vigentes`.

Repositorio nuevo, separado de tarjetas. Antes los MSI eran una lista que se
borraba y se reinsertaba entera cada vez que se guardaban los terminos de una
tarjeta. Eso funcionaba mientras un MSI fuera un dato suelto; deja de funcionar
en cuanto un MSI puede ser la consecuencia de una compra concreta.

DOS ORIGENES, y el modelo los distingue:

  crear_ligado()      Nace de una compra registrada en la app. Lleva
                      `movimiento_id`, y `uq_msi_movimiento` garantiza que una
                      compra no genere dos planes.

  crear_declarado()   Se capturo de un estado de cuenta. `movimiento_id` es
                      NULL porque esa compra ocurrio antes de que el usuario
                      usara la app, y no se va a inventar un movimiento para
                      ella: seria un hecho falso en la bitacora.

MESES RESTANTES: la columna existe, pero la verdad es la vista.
v_msi_calculado los deriva de la fecha de inicio y los meses totales, en vez de
confiar en un contador que alguien tendria que decrementar cada mes. Un
contador mutable que nadie actualiza es una deuda que parece pagarse sola.

    meses_restantes           lo guardado (puede estar viejo)
    meses_restantes_real      lo derivado de la fecha  <- este manda

SALDO PENDIENTE: `monto_total` es la verdad y `monto_mensual` es informativo.
$10,899 a 12 meses da 908.25 exacto, pero la mayoria de las compras no dan
redondo y la ultima mensualidad absorbe la diferencia. Calcular la deuda como
mensual * restantes arrastra centavos hasta el final.
"""

from app.core.conversion import a_dinero
from app.core.exceptions import RecursoNoEncontrado
from app.models.tarjeta import MSIVigente
from app.repositories.base import MySQLRepository

CAMPOS_VISTA = ("id, usuario_id, tarjeta_id, movimiento_id, descripcion,"
                " monto_total, monto_mensual, meses_totales, fecha_inicio,"
                " meses_restantes_guardado, meses_restantes_real, saldo_msi_pendiente")


class MSIRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def listar(self, usuario_id: int, solo_vigentes: bool = True) -> list[MSIVigente]:
        """Lee de la vista: los meses restantes salen derivados, no guardados."""
        sql = f"SELECT {CAMPOS_VISTA} FROM v_msi_calculado WHERE usuario_id = %s"
        if solo_vigentes:
            sql += " AND meses_restantes_real > 0"
        sql += " ORDER BY tarjeta_id, id"
        return [MSIVigente.desde_fila(f) for f in self._todos(sql, (usuario_id,))]

    def por_tarjeta(self, usuario_id: int) -> dict[int, list[MSIVigente]]:
        """
        Todos los MSI del usuario agrupados por tarjeta, en UNA consulta.

        Antes armar el estado hacia una consulta de MSI por cada tarjeta (N+1).
        Con tres tarjetas se notaba poco y con SQLite en un archivo local, nada;
        contra un servidor son tres viajes de red evitables por request.
        """
        agrupado: dict[int, list[MSIVigente]] = {}
        for msi in self.listar(usuario_id, solo_vigentes=True):
            agrupado.setdefault(msi.tarjeta_id, []).append(msi)
        return agrupado

    def obtener(self, msi_id: int, usuario_id: int) -> MSIVigente:
        fila = self._uno(
            f"SELECT {CAMPOS_VISTA} FROM v_msi_calculado"
            " WHERE id = %s AND usuario_id = %s",
            (msi_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Plan a meses no encontrado.")
        return MSIVigente.desde_fila(fila)

    def total_mensual(self, usuario_id: int) -> float:
        """Lo que suman las mensualidades vigentes. Alimenta las obligaciones."""
        valor = self._escalar(
            "SELECT msi_mensual FROM v_obligaciones_mensuales WHERE usuario_id = %s",
            (usuario_id,),
            default=0,
        )
        return float(valor or 0)

    # --- escritura ----------------------------------------------------------

    def crear_ligado(self, usuario_id: int, tarjeta_id: int, movimiento_id: int,
                     monto_total: float, meses: int, fecha_inicio,
                     descripcion: str | None = None,
                     monto_mensual: float | None = None) -> int:
        """
        El plan a meses de una compra registrada aqui.

        `monto_mensual` se calcula si no se pasa, pero es informativo: la deuda
        real sale de monto_total. No se redondea al alza ni a la baja a
        proposito, porque ese numero solo se muestra.
        """
        mensual = monto_mensual if monto_mensual is not None else monto_total / meses
        return self._insertar(
            "INSERT INTO msi_vigentes"
            " (usuario_id, tarjeta_id, movimiento_id, descripcion, monto_total,"
            "  monto_mensual, meses_totales, meses_restantes, fecha_inicio)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (usuario_id, tarjeta_id, movimiento_id, descripcion,
             a_dinero(monto_total), a_dinero(mensual), meses, meses, fecha_inicio),
        )

    def crear_declarado(self, usuario_id: int, tarjeta_id: int,
                        monto_mensual: float, meses_totales: int,
                        meses_restantes: int, fecha_inicio,
                        descripcion: str | None = None,
                        monto_total: float | None = None) -> int:
        """
        Un plan capturado de un estado de cuenta, sin compra en la app.

        `movimiento_id` queda NULL. El UNIQUE de esa columna admite varios NULL
        en MySQL, asi que cualquier cantidad de planes declarados conviven.
        """
        return self._insertar(
            "INSERT INTO msi_vigentes"
            " (usuario_id, tarjeta_id, movimiento_id, descripcion, monto_total,"
            "  monto_mensual, meses_totales, meses_restantes, fecha_inicio)"
            " VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s)",
            (usuario_id, tarjeta_id, descripcion, a_dinero(monto_total),
             a_dinero(monto_mensual), meses_totales, meses_restantes, fecha_inicio),
        )

    def eliminar_logico(self, msi_id: int, usuario_id: int) -> int:
        return self._ejecutar(
            "UPDATE msi_vigentes SET eliminado_en = NOW()"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (msi_id, usuario_id),
        )

    def eliminar_por_movimiento(self, movimiento_id: int, usuario_id: int) -> int:
        """
        Al borrar la compra hay que borrar su plan a meses.

        Sin esto, `fk_msi_movimiento ON DELETE RESTRICT` bloquearia el borrado
        del movimiento, y con razon: un plan a meses colgando de una compra que
        ya no existe seguiria contando como obligacion mensual para siempre.
        """
        return self._ejecutar(
            "UPDATE msi_vigentes SET eliminado_en = NOW()"
            " WHERE movimiento_id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (movimiento_id, usuario_id),
        )

    def pendiente_por_tarjeta(self, usuario_id: int) -> dict[int, float]:
        """
        Cuanto queda comprometido en MSI por tarjeta.

        Es lo que hay que restar del saldo para obtener la parte REVOLVENTE, que
        es la unica que genera intereses: los MSI en Mexico son 0%. Meterlos en
        el calculo de intereses es lo que hacia que revolver saldo le ganara a
        pagar a meses en el ranking de deuda.
        """
        filas = self._todos(
            "SELECT tarjeta_id, COALESCE(SUM(saldo_msi_pendiente), 0) AS pendiente"
            " FROM v_msi_calculado WHERE usuario_id = %s AND meses_restantes_real > 0"
            " GROUP BY tarjeta_id",
            (usuario_id,),
        )
        return {f["tarjeta_id"]: float(f["pendiente"]) for f in filas}