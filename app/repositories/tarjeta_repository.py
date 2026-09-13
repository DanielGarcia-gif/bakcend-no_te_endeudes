"""
SQL de la tabla `tarjetas`.

Dos cambios de fondo respecto a la version de SQLite:

1. LOS MSI SE FUERON A SU PROPIO REPOSITORIO. Antes `actualizar_terminos` hacia
   `DELETE FROM msi_vigentes WHERE tarjeta_id=?` y reinsertaba la lista
   completa. Ese borrar-y-reemplazar ya no es valido: ahora un MSI puede estar
   ligado a la compra que lo origino (`movimiento_id`, con `uq_msi_movimiento`
   y `ON DELETE RESTRICT`), y borrarlo destruiria ese vinculo o fallaria con un
   error 1451. Ver msi_repository.py.

2. TODA ESCRITURA LLEVA usuario_id. El bug viejo era
   `UPDATE tarjetas SET saldo = saldo + ? WHERE id = ?`, sin filtrar por dueno:
   bastaba mandar el id de la tarjeta de otro para moverle el saldo. El esquema
   lo cierra desde el motor con `uq_tarjetas_identidad (id, usuario_id)` y las
   FK compuestas, pero el filtro va igual: la defensa buena es la que no
   depende de que la otra funcione.

SOBRE pago_minimo: sigue siendo columna aqui, pero es el estado DE HOY (una
cache de lo que decia el ultimo estado de cuenta), no la obligacion del
periodo. La verdad de cada corte vive en `periodos_tarjeta.pago_minimo`, que es
un hecho fechado. Quien calcule obligaciones debe preferir el periodo abierto y
caer a esta columna solo si no hay ninguno.
"""

from app.core.conversion import a_dinero, a_tasa
from app.core.exceptions import ConflictoDeEstado, RecursoNoEncontrado
from app.models.tarjeta import Tarjeta
from app.repositories.base import MySQLRepository

CAMPOS = ("id, usuario_id, banco, nombre, tipo, limite, saldo, tasa_anual,"
          " pago_minimo, dia_corte, dia_limite_pago, monto_minimo_msi, activa,"
          " version, creado_en, actualizado_en, eliminado_en")


class TarjetaRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def listar(self, usuario_id: int, solo_activas: bool = False,
               solo_credito: bool = False) -> list[Tarjeta]:
        sql = (f"SELECT {CAMPOS} FROM tarjetas"
               " WHERE usuario_id = %s AND eliminado_en IS NULL")
        if solo_activas:
            sql += " AND activa = 1"
        if solo_credito:
            sql += " AND tipo = 'credito'"
        sql += " ORDER BY id"
        return [Tarjeta.desde_fila(f) for f in self._todos(sql, (usuario_id,))]

    def listar_credito_activas(self, usuario_id: int) -> list[Tarjeta]:
        return self.listar(usuario_id, solo_activas=True, solo_credito=True)

    def obtener(self, tarjeta_id: int, usuario_id: int) -> Tarjeta:
        fila = self._uno(
            f"SELECT {CAMPOS} FROM tarjetas"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (tarjeta_id, usuario_id),
        )
        if fila is None:
            raise RecursoNoEncontrado("Tarjeta no encontrada.")
        return Tarjeta.desde_fila(fila)

    # --- escritura ----------------------------------------------------------

    def crear(self, usuario_id: int, banco: str, nombre: str, tipo: str) -> int:
        """
        Alta minima. Los terminos se capturan despues, porque el usuario suele
        tener la tarjeta a mano antes que su estado de cuenta.

        ck_tarjetas_debito impide que una debito reciba limite, tasa, pago
        minimo o fechas de corte, asi que aqui no hay nada que validar a mano.
        """
        return self._insertar(
            "INSERT INTO tarjetas (usuario_id, banco, nombre, tipo)"
            " VALUES (%s, %s, %s, %s)",
            (usuario_id, banco, nombre, tipo),
        )

    def actualizar(self, tarjeta_id: int, usuario_id: int, cambios: dict,
                   version: int | None = None) -> Tarjeta:
        """
        PATCH parcial con bloqueo optimista.

        Los terminos son lo mas releido y reescrito de la app (el usuario abre
        la pantalla, va por su estado de cuenta, vuelve diez minutos despues), y
        mientras tanto un gasto pudo mover el saldo. Sin `version`, guardar el
        formulario pisaria ese gasto en silencio; con ella, 0 filas afectadas
        significa que alguien escribio primero y se responde 409.

        MSI aparte, a proposito: ver el punto 1 del docstring del modulo.
        """
        permitidas = {
            "banco", "nombre", "limite", "saldo", "tasa_anual", "pago_minimo",
            "dia_corte", "dia_limite_pago", "monto_minimo_msi", "activa",
        }
        dinero = {"limite", "saldo", "pago_minimo", "monto_minimo_msi"}

        campos, valores = [], []
        for clave, valor in cambios.items():
            if clave not in permitidas:
                continue
            campos.append(f"{clave} = %s")
            if clave in dinero:
                valores.append(a_dinero(valor))
            elif clave == "tasa_anual":
                valores.append(a_tasa(valor))
            elif clave == "activa":
                valores.append(int(bool(valor)))
            else:
                valores.append(valor)

        if not campos:
            return self.obtener(tarjeta_id, usuario_id)

        campos.append("version = version + 1")
        sql = (f"UPDATE tarjetas SET {', '.join(campos)}"
               " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL")
        valores += [tarjeta_id, usuario_id]
        if version is not None:
            sql += " AND version = %s"
            valores.append(version)

        if self._ejecutar(sql, tuple(valores)) == 0:
            # Distinguir "no existe" de "cambio debajo" importa: el primero es
            # 404 y el segundo 409, y el frontend actua distinto en cada caso.
            actual = self._uno(
                "SELECT version FROM tarjetas"
                " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
                (tarjeta_id, usuario_id),
            )
            if actual is None:
                raise RecursoNoEncontrado("Tarjeta no encontrada.")
            raise ConflictoDeEstado(
                "La tarjeta cambio mientras editabas. Vuelve a cargar y reintenta.",
                {"version_enviada": version, "version_actual": actual["version"]},
            )
        return self.obtener(tarjeta_id, usuario_id)

    def ajustar_saldo(self, tarjeta_id: int, usuario_id: int, delta: float) -> None:
        """
        Suma o resta al saldo. La aritmetica la hace el motor: atomica y sin
        read-modify-write.

        GREATEST y no MAX: en MySQL MAX() es funcion de agregacion y
        `SET saldo = MAX(0, saldo - %s)` falla con el error 1111. Es la
        traduccion que mas facil se pasa por alto al venir de SQLite, porque no
        rompe al arrancar sino la primera vez que alguien paga una tarjeta.
        """
        self._ejecutar(
            "UPDATE tarjetas SET saldo = GREATEST(0, saldo + %s)"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (a_dinero(delta), tarjeta_id, usuario_id),
        )

    def eliminar_logico(self, tarjeta_id: int, usuario_id: int) -> int:
        """
        Borrado logico. Los movimientos que la referencian se quedan: con
        `ON DELETE RESTRICT` un borrado fisico ni siquiera seria posible, y esta
        bien que sea asi. Con el viejo `SET NULL`, borrar una tarjeta reescribia
        sus gastos a credito como si hubieran sido en efectivo y cambiaba la
        liquidez calculada del pasado.
        """
        return self._ejecutar(
            "UPDATE tarjetas SET eliminado_en = NOW(), activa = 0"
            " WHERE id = %s AND usuario_id = %s AND eliminado_en IS NULL",
            (tarjeta_id, usuario_id),
        )