"""
SQL de la tabla `usuarios`.

`saldo_disponible` es efectivo + banco + debito en un solo numero: lo que la
persona puede gastar hoy. Se actualiza en la MISMA transaccion que el
movimiento que lo mueve, nunca por separado.

DOS FORMAS DE ESCRIBIR UN SALDO, y no son intercambiables:

  ajustar()   SET saldo_disponible = saldo_disponible + %s
              Delta. La suma la hace el motor, asi que es atomica: dos
              requests concurrentes suman los dos. Es la que usan los
              movimientos.

  fijar()     SET saldo_disponible = %s ... AND version = %s
              Valor absoluto, con bloqueo optimista. Es una correccion humana
              ("mi banco dice que tengo 19,500"), no un movimiento, y por eso
              exige saber contra que version se esta escribiendo: si alguien
              registro un gasto mientras el usuario tenia el formulario
              abierto, guardar el absoluto lo borraria.

Con SQLite el read-modify-write en Python pasaba desapercibido porque la base
se bloqueaba entera en cada escritura y todo quedaba serializado por accidente.
InnoDB bloquea por fila: los dos requests corren de verdad en paralelo.
"""

from app.core.conversion import a_dinero
from app.core.exceptions import ConflictoDeEstado, RecursoNoEncontrado
from app.models.usuario import Usuario
from app.repositories.base import MySQLRepository

CAMPOS = ("id, nombre, email, password_hash, saldo_disponible, es_demo,"
          " version, creado_en, actualizado_en, eliminado_en")


class UsuarioRepository(MySQLRepository):

    # --- lectura ------------------------------------------------------------

    def obtener(self, usuario_id: int) -> Usuario:
        fila = self._uno(
            f"SELECT {CAMPOS} FROM usuarios"
            " WHERE id = %s AND eliminado_en IS NULL",
            (usuario_id,),
        )
        if fila is None:
            raise RecursoNoEncontrado("Usuario no encontrado.")
        return Usuario.desde_fila(fila)

    def buscar(self, usuario_id: int) -> Usuario | None:
        """Como obtener() pero sin lanzar. Lo usa la dependencia de auth."""
        fila = self._uno(
            f"SELECT {CAMPOS} FROM usuarios"
            " WHERE id = %s AND eliminado_en IS NULL",
            (usuario_id,),
        )
        return Usuario.desde_fila(fila) if fila else None

    def buscar_por_email(self, email: str) -> Usuario | None:
        # utf8mb4_0900_ai_ci ya es case-insensitive, asi que el viejo bug de
        # 'Hola@x.com' contra 'hola@x.com' desaparece solo. El .lower() del
        # servicio se queda por si algun dia cambia la collation.
        fila = self._uno(
            f"SELECT {CAMPOS} FROM usuarios"
            " WHERE email = %s AND eliminado_en IS NULL",
            (email,),
        )
        return Usuario.desde_fila(fila) if fila else None

    def buscar_demo(self) -> Usuario | None:
        fila = self._uno(
            f"SELECT {CAMPOS} FROM usuarios"
            " WHERE es_demo = 1 AND eliminado_en IS NULL ORDER BY id LIMIT 1"
        )
        return Usuario.desde_fila(fila) if fila else None

    # --- escritura ----------------------------------------------------------

    def crear(self, nombre: str, email: str, password_hash: str,
              saldo_disponible: float = 0.0, es_demo: bool = False) -> Usuario:
        nuevo_id = self._insertar(
            "INSERT INTO usuarios"
            " (nombre, email, password_hash, saldo_disponible, es_demo)"
            " VALUES (%s, %s, %s, %s, %s)",
            (nombre, email, password_hash, a_dinero(saldo_disponible), int(es_demo)),
        )
        return self.obtener(nuevo_id)

    def ajustar_liquidez(self, usuario_id: int, delta: float) -> None:
        """
        Suma (o resta) al saldo. La aritmetica la hace el motor.

        MAL, y era lo que pasaba antes con SQLite sin que se notara:
            saldo = SELECT saldo ...        # request A y B leen 19500
            UPDATE SET saldo = saldo_leido - monto
        Dos gastos simultaneos y se pierde uno.

        BIEN: `saldo_disponible = saldo_disponible - %s` es una sola sentencia
        y InnoDB la serializa por fila.
        """
        self._ejecutar(
            "UPDATE usuarios SET saldo_disponible = saldo_disponible + %s,"
            " version = version + 1"
            " WHERE id = %s AND eliminado_en IS NULL",
            (a_dinero(delta), usuario_id),
        )

    def fijar_liquidez(self, usuario_id: int, saldo: float,
                       version: int | None = None) -> Usuario:
        """
        Escribe el saldo absoluto. Correccion manual, no movimiento.

        Con `version`, 0 filas afectadas significa que alguien escribio primero
        y el valor que el usuario esta guardando ya es viejo: se responde 409 en
        vez de pisar en silencio un gasto recien registrado.
        """
        if version is None:
            sql = ("UPDATE usuarios SET saldo_disponible = %s, version = version + 1"
                   " WHERE id = %s AND eliminado_en IS NULL")
            params = (a_dinero(saldo), usuario_id)
        else:
            sql = ("UPDATE usuarios SET saldo_disponible = %s, version = version + 1"
                   " WHERE id = %s AND version = %s AND eliminado_en IS NULL")
            params = (a_dinero(saldo), usuario_id, version)

        if self._ejecutar(sql, params) == 0:
            if version is not None and self.buscar(usuario_id) is not None:
                raise ConflictoDeEstado(
                    "Alguien mas actualizo tu saldo mientras editabas. "
                    "Vuelve a cargar y reintenta.",
                    {"version_enviada": version},
                )
            raise RecursoNoEncontrado("Usuario no encontrado.")
        return self.obtener(usuario_id)

    def eliminar_logico(self, usuario_id: int) -> None:
        self._ejecutar(
            "UPDATE usuarios SET eliminado_en = NOW()"
            " WHERE id = %s AND eliminado_en IS NULL",
            (usuario_id,),
        )