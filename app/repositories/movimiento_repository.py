"""
SQL de la tabla `movimientos` — TRANSACCIONAL.

La unica bitacora. Cada fila es un hecho exacto que ocurrio en una fecha: no
hay rangos, no hay estimaciones, no hay estados "pendiente". Si esta aqui, el
dinero se movio.

EL EFECTO SOBRE LOS SALDOS Y EL MOVIMIENTO SE GUARDAN JUNTOS O NO SE GUARDAN.
Van en la transaccion del request (get_conexion commitea al final), y de ahi
sale toda la coherencia del sistema. La tabla completa:

    tipo     medio              usuarios.saldo_disponible   tarjetas.saldo
    gasto    efectivo/debito    - monto                     --
    gasto    credito            --                          + monto
    pago     efectivo/debito    - monto                     - monto
    ingreso  efectivo/debito    + monto                     --

Un gasto a credito NO baja la liquidez: no salio dinero del bolsillo, subio la
deuda. Un pago mueve los dos saldos en direcciones opuestas. Y una compra a 12
MSI sube el saldo de la tarjeta por el TOTAL, no por la mensualidad: el banco
presto los doce mil completos y la utilizacion es el 20% del score.

`medio` ES UNA COLUMNA, YA NO SE INFIERE. Antes el medio salia de
`tarjeta_id IS NULL`, que significaba "efectivo O debito" — dos cosas distintas
colapsadas en una. Peor: el servicio decidia por `req.medio` y el repositorio
por `tarjeta_id`, asi que un gasto con medio='debito' y un tarjeta_id ajeno se
validaba contra la liquidez, se reportaba como liquidez, y terminaba sumando al
saldo de la tarjeta de otro usuario. Ahora `medio` viaja hasta la columna y
`ck_mov_coherencia` valida la combinacion en el motor de la base.

IDEMPOTENCIA. Sin ella un doble tap inserta el gasto dos veces y baja el saldo
dos veces, sin dejar rastro de que fue un accidente. Con `uq_mov_idempotencia`
el segundo intento choca (error 1062) y el servicio devuelve el movimiento que
YA existe. La clave la manda el cliente por GESTO del usuario, no por request:
un reintento de la libreria HTTP debe reusar la misma.
"""

from datetime import date, timedelta

from app.core.conversion import a_dinero
from app.core.exceptions import RecursoNoEncontrado
from app.models.movimiento import Movimiento
from app.repositories.base import MySQLRepository

# Ventana del gasto variable promedio.
DIAS_VENTANA_VARIABLE = 90

CAMPOS = ("m.id, m.usuario_id, m.tipo, m.medio, m.monto, m.categoria_id,"
          " m.descripcion, m.fecha, m.tarjeta_id, m.periodo_id, m.ingreso_id,"
          " m.recurrente_id, m.idempotency_key, m.creado_en, m.eliminado_en,"
          " m.motivo_eliminacion, c.clave AS categoria_clave,"
          " c.nombre AS categoria_nombre, t.nombre AS tarjeta_nombre")

DESDE = (" FROM movimientos m"
         " LEFT JOIN categorias c ON c.id = m.categoria_id"
         " LEFT JOIN tarjetas t ON t.id = m.tarjeta_id")


class MovimientoRepository(MySQLRepository):

    # =====================================================================
    # LECTURA
    # =====================================================================

    def obtener(self, movimiento_id: int, usuario_id: int) -> Movimiento:
        fila = self._uno(
            f"SELECT {CAMPOS}{DESDE}"
            " WHERE m.id = %s AND m.usuario_id = %s AND m.eliminado_en IS NULL",
            (movimiento_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Movimiento no encontrado.")
        return Movimiento.desde_fila(fila)

    def buscar_por_idempotencia(self, usuario_id: int,
                                clave: str) -> Movimiento | None:
        """
        El movimiento que ya se creo con esa clave, si existe.

        Se consulta ANTES de intentar el INSERT (para responder rapido al caso
        comun del doble tap) y tambien DESPUES de un error 1062 (para cerrar la
        carrera entre dos requests simultaneos con la misma clave).
        """
        if not clave:
            return None
        fila = self._uno(
            f"SELECT {CAMPOS}{DESDE}"
            " WHERE m.usuario_id = %s AND m.idempotency_key = %s",
            (usuario_id, clave),
        )
        return Movimiento.desde_fila(fila) if fila else None

    def listar(self, usuario_id: int, limite: int = 50, tipo: str | None = None,
               medio: str | None = None, tarjeta_id: int | None = None,
               categoria_id: int | None = None, desde: str | None = None,
               hasta: str | None = None, cursor_fecha: str | None = None,
               cursor_id: int | None = None) -> list[Movimiento]:
        """
        Historial filtrable y paginado por cursor.

        Cursor y no OFFSET: es la unica coleccion que crece sin techo, y con
        OFFSET la pagina 50 obliga al motor a leer y descartar 2,450 filas. El
        cursor es (fecha, id), que es exactamente el orden de ix_mov_usuario_fecha,
        asi que la consulta cuesta lo mismo en la pagina 1 que en la 500.
        """
        sql = (f"SELECT {CAMPOS}{DESDE}"
               " WHERE m.usuario_id = %s AND m.eliminado_en IS NULL")
        params: list = [usuario_id]

        if tipo:
            sql += " AND m.tipo = %s"
            params.append(tipo)
        if medio:
            sql += " AND m.medio = %s"
            params.append(medio)
        if tarjeta_id is not None:
            sql += " AND m.tarjeta_id = %s"
            params.append(tarjeta_id)
        if categoria_id is not None:
            sql += " AND m.categoria_id = %s"
            params.append(categoria_id)
        if desde:
            sql += " AND m.fecha >= %s"
            params.append(desde)
        if hasta:
            sql += " AND m.fecha <= %s"
            params.append(hasta)
        if cursor_fecha and cursor_id is not None:
            # Comparacion de tupla: la fila siguiente en el orden (fecha DESC,
            # id DESC), sin saltarse empates de fecha ni repetirlos.
            sql += " AND (m.fecha < %s OR (m.fecha = %s AND m.id < %s))"
            params += [cursor_fecha, cursor_fecha, cursor_id]

        sql += " ORDER BY m.fecha DESC, m.id DESC LIMIT %s"
        params.append(limite)
        return [Movimiento.desde_fila(f) for f in self._todos(sql, tuple(params))]

    def gasto_variable_promedio(self, usuario_id: int) -> float:
        """
        Cuanto se le va al mes en gastos sueltos, en promedio.

        DOS FILTROS, no uno, y cada uno arregla una forma distinta de mentir:

          medio <> 'credito'      Una compra a credito no es salida de efectivo.
                                  Antes contaba aqui Y subia el saldo de la
                                  tarjeta: el mismo gasto castigaba dos veces.

          recurrente_id IS NULL   Los fijos ya se cuentan por su propio lado. Sin
                                  esto la renta entra dos veces.

          NOT EXISTS (msi...)     Una compra a meses no es consumo del mes, es
                                  deuda financiada. Con $12,000 a 12 MSI dentro
                                  del promedio, el usuario aparece gastando
                                  $4,000 extra al mes durante tres meses y su
                                  score se hunde sin razon.

        Y se divide entre los meses que HAY, no siempre entre 3. Un usuario con
        tres semanas de historial no gasta un tercio de lo que gasta: dividir su
        mes real entre 3 le inventa una frugalidad que no tiene.
        """
        fila = self._uno(
            "SELECT COALESCE(SUM(m.monto), 0) AS total, MIN(m.fecha) AS primera"
            " FROM movimientos m"
            " WHERE m.usuario_id = %s"
            "   AND m.tipo = 'gasto'"
            "   AND m.medio <> 'credito'"
            "   AND m.recurrente_id IS NULL"
            "   AND m.eliminado_en IS NULL"
            "   AND NOT EXISTS (SELECT 1 FROM msi_vigentes s"
            "                    WHERE s.movimiento_id = m.id"
            "                      AND s.eliminado_en IS NULL)"
            "   AND m.fecha >= %s",
            (usuario_id, date.today() - timedelta(days=DIAS_VENTANA_VARIABLE)),
        )
        total = float(fila["total"] or 0)
        if total == 0 or fila["primera"] is None:
            return 0.0

        dias = max((date.today() - fila["primera"]).days, 1)
        meses = max(dias / 30.0, 1.0)      # menos de un mes cuenta como uno
        return total / meses

    # =====================================================================
    # ESCRITURA
    # =====================================================================

    def registrar(self, usuario_id: int, tipo: str, medio: str, monto: float,
                  fecha, categoria_id: int | None = None,
                  descripcion: str | None = None, tarjeta_id: int | None = None,
                  ingreso_id: int | None = None, recurrente_id: int | None = None,
                  idempotency_key: str | None = None) -> int:
        """
        Inserta el movimiento y aplica su efecto sobre los saldos, juntos.

        El orden importa poco (todo esta en la misma transaccion) pero el INSERT
        va primero para que un fallo de ck_mov_coherencia aborte antes de tocar
        ningun saldo, y el error salga como 422 explicando la regla en vez de
        como un saldo movido a medias.
        """
        movimiento_id = self._insertar(
            "INSERT INTO movimientos"
            " (usuario_id, tipo, medio, monto, categoria_id, descripcion, fecha,"
            "  tarjeta_id, ingreso_id, recurrente_id, idempotency_key)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (usuario_id, tipo, medio, a_dinero(monto), categoria_id, descripcion,
             fecha, tarjeta_id, ingreso_id, recurrente_id, idempotency_key),
        )
        self._aplicar_efecto(usuario_id, tipo, medio, monto, tarjeta_id, signo=1)
        return movimiento_id

    def eliminar_logico(self, movimiento_id: int, usuario_id: int,
                        motivo: str) -> Movimiento:
        """
        Borrado logico que REVIERTE su efecto sobre los saldos.

        Un borrado que no revierte es peor que no borrar: el dato desaparece de
        la vista pero el saldo sigue movido, y el usuario ve un numero que no
        corresponde con ninguna fila que pueda mirar.

        El SELECT ... FOR UPDATE bloquea la fila hasta el commit. Sin el, dos
        peticiones de borrado del mismo movimiento leerian ambas que esta vivo y
        revertirian el saldo dos veces. Con SQLite no pasaba porque la base se
        bloqueaba entera; InnoDB bloquea por fila y este es justo el caso.
        """
        fila = self._uno(
            "SELECT id, tipo, medio, monto, tarjeta_id FROM movimientos"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL"
            " FOR UPDATE",
            (movimiento_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Movimiento no encontrado.")

        anterior = self.obtener(movimiento_id, usuario_id)
        self._aplicar_efecto(usuario_id, fila["tipo"], fila["medio"],
                             float(fila["monto"]), fila["tarjeta_id"], signo=-1)
        self._ejecutar(
            "UPDATE movimientos SET eliminado_en = NOW(), motivo_eliminacion = %s"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (motivo, movimiento_id, usuario_id),
        )
        return anterior

    def _aplicar_efecto(self, usuario_id: int, tipo: str, medio: str,
                        monto: float, tarjeta_id: int | None, signo: int) -> None:
        """
        Mueve los saldos segun la tabla del docstring del modulo.

        `signo` es 1 al registrar y -1 al borrar, asi que el borrado usa
        exactamente la misma logica invertida y es imposible que las dos rutas
        se desincronicen.

        Toda la aritmetica va dentro del SQL (`saldo = saldo + %s`): es atomica
        por fila. Leer el saldo, sumar en Python y escribir el resultado pierde
        una de dos escrituras simultaneas, y con SQLite eso quedaba oculto
        porque la base se serializaba sola.
        """
        delta = monto * signo

        if tipo == "gasto":
            if medio == "credito":
                self._saldo_tarjeta(tarjeta_id, usuario_id, +delta)
            else:
                self._liquidez(usuario_id, -delta)

        elif tipo == "pago":
            # Los dos saldos, en direcciones opuestas, en la misma transaccion.
            self._liquidez(usuario_id, -delta)
            self._saldo_tarjeta(tarjeta_id, usuario_id, -delta)

        elif tipo == "ingreso":
            self._liquidez(usuario_id, +delta)

    def _liquidez(self, usuario_id: int, delta: float) -> None:
        self._ejecutar(
            "UPDATE usuarios SET saldo_disponible = saldo_disponible + %s,"
            " version = version + 1"
            " WHERE id = %s AND eliminado_en IS NULL",
            (a_dinero(delta), usuario_id),
        )

    def _saldo_tarjeta(self, tarjeta_id: int | None, usuario_id: int,
                       delta: float) -> None:
        if tarjeta_id is None:
            return
        # GREATEST, no MAX: en MySQL MAX() es agregacion y `SET saldo = MAX(0, ...)`
        # falla con el error 1111. Y el `AND usuario_id` cierra la escritura
        # cruzada entre usuarios que permitia la version anterior.
        self._ejecutar(
            "UPDATE tarjetas SET saldo = GREATEST(0, saldo + %s)"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (a_dinero(delta), tarjeta_id, usuario_id),
        )