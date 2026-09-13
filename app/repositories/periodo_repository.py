"""
SQL de la tabla `periodos_tarjeta` — el corte.

Repositorio nuevo. Antes solo existian `dia_corte` y `dia_limite_pago` como dos
enteros sueltos en `tarjetas`, y con eso la app no podia decir la frase mas util
que puede decir:

    "tu corte fue el 15 con $6,000; paga eso antes del 5 y no generas intereses"

Porque en credito mexicano lo que determina si pagas intereses NO es el saldo de
hoy: es el saldo al corte. Un usuario que gasta $3,000 el dia 16 no debe verlos
en la obligacion de este periodo — caen en el siguiente.

TRES CIFRAS QUE LA GENTE CONFUNDE Y QUE AQUI QUEDAN SEPARADAS:

  saldo_al_corte      lo que debias el dia del corte.
  pago_minimo         lo que el banco exige para no caer en mora. Deja de ser
                      columna estatica de `tarjetas` y pasa a ser un hecho
                      fechado de cada periodo.
  pago_no_intereses   saldo_al_corte menos la parte en promocion a meses. Es el
                      numero que de verdad importa: pagando esto la tasa no
                      corre.

MIENTRAS `cerrado = 0` LAS CIFRAS SON PROYECTADAS. Al cerrar se congelan y los
movimientos del rango reciben su `periodo_id`. El cierre es explicito (un
endpoint), no un cron: la app no tiene nocion del paso del tiempo, es una foto
del presente, y un proceso de fondo que hay que dejar corriendo es justo lo que
no queremos que falle en mitad de una demo.
"""

from app.core.conversion import a_dinero
from app.core.exceptions import ConflictoDeEstado, RecursoNoEncontrado
from app.models.periodo import PeriodoTarjeta
from app.repositories.base import MySQLRepository

CAMPOS = ("id, usuario_id, tarjeta_id, fecha_inicio, fecha_corte, fecha_limite_pago,"
          " saldo_al_corte, pago_minimo, pago_no_intereses, msi_del_periodo,"
          " pagado, intereses_generados, cerrado, creado_en, actualizado_en")


class PeriodoRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def listar(self, tarjeta_id: int, usuario_id: int,
               limite: int = 24) -> list[PeriodoTarjeta]:
        filas = self._todos(
            f"SELECT {CAMPOS} FROM periodos_tarjeta"
            " WHERE tarjeta_id = %s AND usuario_id = %s"
            " ORDER BY fecha_corte DESC LIMIT %s",
            (tarjeta_id, usuario_id, limite),
        )
        return [PeriodoTarjeta.desde_fila(f) for f in filas]

    def obtener(self, periodo_id: int, usuario_id: int) -> PeriodoTarjeta:
        fila = self._uno(
            f"SELECT {CAMPOS} FROM periodos_tarjeta"
            " WHERE id = %s AND usuario_id = %s",
            (periodo_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Periodo no encontrado.")
        return PeriodoTarjeta.desde_fila(fila)

    def abierto_de(self, tarjeta_id: int, usuario_id: int) -> PeriodoTarjeta | None:
        """El periodo en curso de una tarjeta, si lo hay."""
        fila = self._uno(
            f"SELECT {CAMPOS} FROM periodos_tarjeta"
            " WHERE tarjeta_id = %s AND usuario_id = %s AND cerrado = 0"
            " ORDER BY fecha_corte DESC LIMIT 1",
            (tarjeta_id, usuario_id),
        )
        return PeriodoTarjeta.desde_fila(fila) if fila else None

    def abiertos_por_tarjeta(self, usuario_id: int) -> dict[int, PeriodoTarjeta]:
        """
        Los periodos abiertos de todas las tarjetas, en UNA consulta.

        Lo usa el armado del estado para preferir `periodos_tarjeta.pago_minimo`
        sobre la columna cache de `tarjetas`, sin pagar una consulta por tarjeta.
        """
        filas = self._todos(
            f"SELECT {CAMPOS} FROM periodos_tarjeta"
            " WHERE usuario_id = %s AND cerrado = 0"
            " ORDER BY tarjeta_id, fecha_corte DESC",
            (usuario_id,),
        )
        salida: dict[int, PeriodoTarjeta] = {}
        for f in filas:
            # ORDER BY deja el mas reciente primero; solo se queda ese.
            salida.setdefault(f["tarjeta_id"], PeriodoTarjeta.desde_fila(f))
        return salida

    def pagos_pendientes(self, usuario_id: int) -> list[dict]:
        """
        Lo que hay que pagar y antes de cuando. Es la vista que da el consejo
        accionable: pagar `pago_no_intereses` antes de `fecha_limite_pago`
        evita que corra la tasa.
        """
        return self._todos(
            "SELECT usuario_id, tarjeta_id, banco, tarjeta, fecha_corte,"
            " fecha_limite_pago, dias_restantes, saldo_al_corte, pago_minimo,"
            " pago_no_intereses, pagado, falta_para_no_intereses, falta_para_no_mora"
            " FROM v_pagos_pendientes WHERE usuario_id = %s"
            " ORDER BY fecha_limite_pago",
            (usuario_id,),
        )

    # --- escritura ----------------------------------------------------------

    def abrir(self, usuario_id: int, tarjeta_id: int, fecha_inicio,
              fecha_corte, fecha_limite_pago) -> int:
        """
        Abre un periodo. `uq_periodo_corte (tarjeta_id, fecha_corte)` impide
        duplicarlo, asi que reintentar el alta da 409 en vez de dos periodos
        compitiendo por el mismo corte.
        """
        return self._insertar(
            "INSERT INTO periodos_tarjeta"
            " (usuario_id, tarjeta_id, fecha_inicio, fecha_corte, fecha_limite_pago)"
            " VALUES (%s, %s, %s, %s, %s)",
            (usuario_id, tarjeta_id, fecha_inicio, fecha_corte, fecha_limite_pago),
        )

    def actualizar_cifras(self, periodo_id: int, usuario_id: int,
                          saldo_al_corte: float, pago_minimo: float,
                          pago_no_intereses: float, msi_del_periodo: float,
                          intereses_generados: float = 0.0) -> int:
        """
        Refresca las cifras proyectadas de un periodo ABIERTO.

        No toca los cerrados: ahi las cifras estan congeladas y reescribirlas
        seria reescribir el pasado. El WHERE lo impone.
        """
        return self._ejecutar(
            "UPDATE periodos_tarjeta SET saldo_al_corte = %s, pago_minimo = %s,"
            " pago_no_intereses = %s, msi_del_periodo = %s, intereses_generados = %s"
            " WHERE id = %s AND usuario_id = %s AND cerrado = 0",
            (a_dinero(saldo_al_corte), a_dinero(pago_minimo),
             a_dinero(pago_no_intereses), a_dinero(msi_del_periodo),
             a_dinero(intereses_generados), periodo_id, usuario_id),
        )

    def registrar_pago(self, periodo_id: int, usuario_id: int, monto: float) -> int:
        """
        Abona a un periodo. Delta, no absoluto: la suma la hace el motor.

        Se aplica tambien a periodos cerrados, y debe ser asi: un corte cerrado
        es el que TIENE una fecha limite que vence, y pagarlo es justo lo que la
        app le esta pidiendo al usuario que haga.
        """
        return self._ejecutar(
            "UPDATE periodos_tarjeta SET pagado = pagado + %s"
            " WHERE id = %s AND usuario_id = %s",
            (a_dinero(monto), periodo_id, usuario_id),
        )

    def cerrar(self, periodo_id: int, usuario_id: int) -> int:
        """
        Congela el periodo y adopta sus movimientos.

        Las dos sentencias van en la transaccion del request: un periodo
        marcado como cerrado cuyos movimientos siguen sin `periodo_id` seria
        peor que uno abierto, porque parece completo y no lo esta.
        """
        periodo = self.obtener(periodo_id, usuario_id)
        if periodo.cerrado:
            raise ConflictoDeEstado("Ese periodo ya estaba cerrado.")

        self._ejecutar(
            "UPDATE movimientos SET periodo_id = %s"
            " WHERE usuario_id = %s AND tarjeta_id = %s"
            " AND fecha BETWEEN %s AND %s"
            " AND periodo_id IS NULL AND eliminado_en IS NULL",
            (periodo_id, usuario_id, periodo.tarjeta_id,
             periodo.fecha_inicio, periodo.fecha_corte),
        )
        return self._ejecutar(
            "UPDATE periodos_tarjeta SET cerrado = 1"
            " WHERE id = %s AND usuario_id = %s AND cerrado = 0",
            (periodo_id, usuario_id),
        )

    def cargos_del_rango(self, usuario_id: int, tarjeta_id: int,
                         desde, hasta) -> dict:
        """
        Lo que se cargo a esa tarjeta dentro del rango del periodo.

        Separa MSI de revolvente porque son las dos mitades de
        `pago_no_intereses`: lo que esta a meses no genera intereses y lo demas
        si. Es la resta que el usuario no hace y por la que acaba pagando tasa.
        """
        fila = self._uno(
            "SELECT"
            " COALESCE(SUM(CASE WHEN m.tipo = 'gasto' THEN m.monto ELSE 0 END), 0)"
            "   AS cargos,"
            " COALESCE(SUM(CASE WHEN m.tipo = 'gasto'"
            "   AND EXISTS (SELECT 1 FROM msi_vigentes s"
            "               WHERE s.movimiento_id = m.id AND s.eliminado_en IS NULL)"
            "   THEN m.monto ELSE 0 END), 0) AS cargos_msi,"
            " COALESCE(SUM(CASE WHEN m.tipo = 'pago' THEN m.monto ELSE 0 END), 0)"
            "   AS pagos"
            " FROM movimientos m"
            " WHERE m.usuario_id = %s AND m.tarjeta_id = %s"
            " AND m.fecha BETWEEN %s AND %s AND m.eliminado_en IS NULL",
            (usuario_id, tarjeta_id, desde, hasta),
        )
        return {
            "cargos": float(fila["cargos"]),
            "cargos_msi": float(fila["cargos_msi"]),
            "pagos": float(fila["pagos"]),
        }