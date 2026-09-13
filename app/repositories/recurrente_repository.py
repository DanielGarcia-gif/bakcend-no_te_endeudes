"""
SQL de la tabla `recurrentes` — DECLARATIVA.

Gastos fijos. El cambio de modelo importante es que ya no todos son mensuales:
`frecuencia_meses` cubre bimestral, trimestral, semestral y anual, y la FASE
(que meses concretos) sale de `fecha_inicio`. Antes la luz bimestral, el
predial anual y la tenencia simplemente no eran representables.

DOS PREGUNTAS DISTINTAS, DOS CONSULTAS DISTINTAS, y confundirlas garantiza que
una este mal:

  "cuanto de mi ingreso se va en obligaciones?"   -> peso_mensual()
      Una luz de $900 bimestral pesa $450/mes. Sale de
      v_obligaciones_mensuales.fijos_amortizados. Alimenta el score.

  "me alcanza este mes?"                          -> del_mes()
      Esa misma luz sale COMPLETA ($900) el mes que toca, y $0 el que no.
      Sale de v_recurrentes_del_mes. Alimenta la proyeccion de flujo y la
      lista de pendientes por confirmar.

EL MONTO DE LOS VARIABLES SE DERIVA, NO SE DECLARA. Para la luz, el agua o el
gas no se guarda un rango min/max: el rango real sale del historial via
`movimientos.recurrente_id`, y de ahi lo saca v_recurrentes_historial. El
usuario estima mal su propio rango; con tres recibos ya hay datos que le ganan
a esa memoria.

    monto_para_proyectar usa el MAXIMO reciente, no el promedio. En una app
    que previene deuda, equivocarse hacia abajo es el error caro: decirle a
    alguien que debe $500 cuando debe $1,000 lo mete justo en el problema que
    la app promete evitar.
"""

from app.core.conversion import a_dinero
from app.core.exceptions import RecursoNoEncontrado
from app.models.recurrente import Recurrente
from app.repositories.base import MySQLRepository

CAMPOS = ("r.id, r.usuario_id, r.concepto, r.monto, r.es_variable, r.dia_del_mes,"
          " r.frecuencia_meses, r.ajuste_mes_corto, r.categoria_id, r.fecha_inicio,"
          " r.fecha_fin, r.activo, r.creado_en, r.actualizado_en, r.eliminado_en,"
          " c.clave AS categoria_clave, c.nombre AS categoria_nombre")

DESDE = " FROM recurrentes r JOIN categorias c ON c.id = r.categoria_id"


class RecurrenteRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def listar(self, usuario_id: int, solo_activos: bool = True) -> list[Recurrente]:
        sql = (f"SELECT {CAMPOS}{DESDE}"
               " WHERE r.usuario_id = %s AND r.eliminado_en IS NULL")
        if solo_activos:
            sql += (" AND r.activo = 1"
                    " AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())")
        sql += " ORDER BY r.dia_del_mes, r.id"
        return [Recurrente.desde_fila(f) for f in self._todos(sql, (usuario_id,))]

    def obtener(self, recurrente_id: int, usuario_id: int) -> Recurrente:
        fila = self._uno(
            f"SELECT {CAMPOS}{DESDE}"
            " WHERE r.id = %s AND r.usuario_id = %s AND r.eliminado_en IS NULL",
            (recurrente_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Gasto recurrente no encontrado.")
        return Recurrente.desde_fila(fila)

    def peso_mensual(self, usuario_id: int) -> float:
        """
        Cuanto pesan al mes los fijos, amortizados por frecuencia.

        Sale de la vista y no de un SUM(monto) porque ese SUM daba por sentado
        que todo era mensual: un predial de $8,000 anual contaba como $8,000
        cada mes y hundia el componente de deuda del score.
        """
        valor = self._escalar(
            "SELECT fijos_amortizados FROM v_obligaciones_mensuales"
            " WHERE usuario_id = %s",
            (usuario_id,),
            default=0,
        )
        return float(valor or 0)

    def del_mes(self, usuario_id: int) -> list[dict]:
        """
        Los que CAEN este mes, con su monto completo y su historial.

        La vista ya resuelve la fase:
            MOD(TIMESTAMPDIFF(MONTH, fecha_inicio, CURDATE()), frecuencia_meses) = 0
        """
        return self._todos(
            "SELECT recurrente_id, usuario_id, concepto, categoria_id, dia_del_mes,"
            " ajuste_mes_corto, es_variable, frecuencia_meses, monto_para_proyectar,"
            " monto_min, monto_max, pagos_considerados, ultimo_confirmado"
            " FROM v_recurrentes_del_mes WHERE usuario_id = %s"
            " ORDER BY dia_del_mes",
            (usuario_id,),
        )

    def historial(self, recurrente_id: int, usuario_id: int) -> dict | None:
        """
        El rango real de un gasto variable, con datos del usuario y no con su
        suposicion. Considera los ultimos 6 pagos confirmados.
        """
        return self._uno(
            "SELECT recurrente_id, concepto, es_variable, frecuencia_meses,"
            " monto_declarado, pagos_considerados, monto_min, monto_max,"
            " monto_promedio, ultimo_pago, monto_para_proyectar"
            " FROM v_recurrentes_historial"
            " WHERE recurrente_id = %s AND usuario_id = %s",
            (recurrente_id, usuario_id),
        )

    def confirmados_del_mes(self, usuario_id: int) -> set[int]:
        """
        Que recurrentes ya tienen movimiento en el mes en curso.

        Es la resta que convierte "lo que toca" en "lo que falta confirmar".
        """
        filas = self._todos(
            "SELECT DISTINCT recurrente_id FROM movimientos"
            " WHERE usuario_id = %s AND recurrente_id IS NOT NULL"
            " AND eliminado_en IS NULL"
            " AND YEAR(fecha) = YEAR(CURDATE()) AND MONTH(fecha) = MONTH(CURDATE())",
            (usuario_id,),
        )
        return {f["recurrente_id"] for f in filas}

    # --- escritura ----------------------------------------------------------

    def crear(self, usuario_id: int, concepto: str, monto: float,
              dia_del_mes: int, categoria_id: int, fecha_inicio,
              es_variable: bool = False, frecuencia_meses: int = 1,
              ajuste_mes_corto: str = "ultimo_dia", fecha_fin=None) -> int:
        """
        `fecha_inicio` es NOT NULL sin default: define la fase del ciclo. Sin
        ella, dos gastos bimestrales creados el mismo dia caerian siempre en
        los mismos meses aunque en la vida real se alternen.
        """
        return self._insertar(
            "INSERT INTO recurrentes"
            " (usuario_id, concepto, monto, es_variable, dia_del_mes,"
            "  frecuencia_meses, ajuste_mes_corto, categoria_id, fecha_inicio, fecha_fin)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (usuario_id, concepto, a_dinero(monto), int(es_variable), dia_del_mes,
             frecuencia_meses, ajuste_mes_corto, categoria_id, fecha_inicio, fecha_fin),
        )

    def actualizar(self, recurrente_id: int, usuario_id: int, cambios: dict) -> int:
        permitidas = {
            "concepto", "monto", "es_variable", "dia_del_mes", "frecuencia_meses",
            "ajuste_mes_corto", "categoria_id", "fecha_inicio", "fecha_fin", "activo",
        }
        campos, valores = [], []
        for clave, valor in cambios.items():
            if clave not in permitidas:
                continue
            campos.append(f"{clave} = %s")
            if clave == "monto":
                valores.append(a_dinero(valor))
            elif clave in ("es_variable", "activo"):
                valores.append(int(bool(valor)))
            else:
                valores.append(valor)

        if not campos:
            return 0
        valores += [recurrente_id, usuario_id]
        return self._ejecutar(
            f"UPDATE recurrentes SET {', '.join(campos)}"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            tuple(valores),
        )

    def eliminar_logico(self, recurrente_id: int, usuario_id: int) -> int:
        return self._ejecutar(
            "UPDATE recurrentes SET eliminado_en = NOW(), activo = 0"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (recurrente_id, usuario_id),
        )