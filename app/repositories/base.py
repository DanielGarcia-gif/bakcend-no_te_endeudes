"""
Base comun de los repositorios.

Un repositorio recibe la conexion por constructor (nunca la abre, ni la cierra,
ni la commitea: de eso se encarga la dependencia get_conexion) y encapsula
TODO el SQL de su tabla. Los servicios no escriben consultas.

SOBRE LAS TRANSACCIONES: aqui no se hace commit. La conexion se abre con
autocommit=False (app/core/database.py) y get_conexion cierra la transaccion al
terminar el request, con commit si todo fue bien o rollback si algo reviento.
Asi un caso de uso que escribe en varias tablas (POST /onboarding, o un gasto
que mueve un saldo y guarda su movimiento) es atomico sin trabajo extra.

    Ojo con el default de MySQL: autocommit=1. Si esa bandera se pierde, cada
    UPDATE se confirma solo, el rollback de get_conexion se vuelve decorativo y
    la atomicidad desaparece SIN ERROR. Es el fallo mas silencioso posible aqui.

SOBRE LOS ERRORES: traducir_error es la red de seguridad que antes daba
`except sqlite3.IntegrityError`, y no es un cambio cosmetico de nombres. En
MySQL una violacion de CHECK NO es un IntegrityError: es el error 3819, que
PyMySQL entrega como OperationalError. Un `except IntegrityError` portado tal
cual dejaria de disparar, y las reglas que el esquema apoya en CHECKs
(ck_mov_coherencia, ck_periodo_coherencia, ck_msi_resto) saldrian como un 500
opaco en vez de un 422 que dice que regla se rompio. Por eso aqui se discrimina
por CODIGO de error, nunca por clase de excepcion.
"""

import pymysql

from app.core.exceptions import (
    ConflictoDeEstado,
    ErrorDePersistencia,
    ReglaDeNegocioViolada,
)

# --- codigos de error de MySQL que significan algo de negocio ---
DUPLICADO = 1062          # ER_DUP_ENTRY
FK_INEXISTENTE = 1452     # ER_NO_REFERENCED_ROW_2: apunta a algo que no existe
FK_REFERENCIADA = 1451    # ER_ROW_IS_REFERENCED_2: ON DELETE RESTRICT lo impide
CHECK_VIOLADO = 3819      # ER_CHECK_CONSTRAINT_VIOLATED  <-- NO es IntegrityError
FUERA_DE_RANGO = 1264     # ER_WARN_DATA_OUT_OF_RANGE
DATO_MUY_LARGO = 1406     # ER_DATA_TOO_LONG
DEADLOCK = 1213           # ER_LOCK_DEADLOCK
ESPERA_AGOTADA = 1205     # ER_LOCK_WAIT_TIMEOUT

# Los CHECK del esquema traducidos a algo accionable. MySQL solo dice
# "Check constraint 'X' is violated", que al usuario no le sirve de nada.
MENSAJE_POR_CHECK = {
    "ck_mov_coherencia": (
        "La combinacion de tipo, medio y tarjeta no es valida: un gasto a "
        "credito exige tarjeta, un pago exige tarjeta y salir de efectivo o "
        "debito, y un ingreso no puede ir a una tarjeta."
    ),
    "ck_mov_categoria": "Todo gasto necesita una categoria.",
    "ck_mov_origen_unico": "Un movimiento viene de un ingreso o de un recurrente, no de ambos.",
    "ck_mov_origen_ingreso": "Solo un movimiento de tipo ingreso puede venir de un ingreso declarado.",
    "ck_mov_origen_recurrente": "Solo un gasto puede venir de un gasto recurrente.",
    "ck_mov_monto": "El monto debe ser mayor que cero.",
    "ck_mov_periodo": "Un movimiento solo cae en un periodo si tiene tarjeta.",
    "ck_mov_eliminado": "Un borrado necesita motivo, y un motivo necesita borrado.",
    "ck_ingresos_ancla": (
        "Un ingreso semanal o catorcenal se define por fecha de referencia; "
        "uno quincenal o mensual, por dia de pago."
    ),
    "ck_ingresos_dia2_quincenal": "Solo un ingreso quincenal puede tener un segundo dia de pago.",
    "ck_ingresos_monto": "El monto del ingreso debe ser mayor que cero.",
    "ck_tarjetas_debito": (
        "Una tarjeta de debito no lleva limite, tasa, pago minimo ni fechas de corte."
    ),
    "ck_tarjetas_saldo": "El saldo de una tarjeta no puede ser negativo.",
    "ck_tarjetas_limite": "El limite debe ser mayor que cero.",
    "ck_tarjetas_tasa": "La tasa anual debe expresarse como fraccion entre 0 y 2.",
    "ck_recurrentes_frecuencia": "La frecuencia debe estar entre 1 y 12 meses.",
    "ck_recurrentes_rango": "La fecha de fin no puede ser anterior a la de inicio.",
    "ck_recurrentes_monto": "El monto del gasto recurrente debe ser mayor que cero.",
    "ck_periodo_fechas": (
        "El corte no puede ser anterior al inicio del periodo, ni la fecha "
        "limite de pago anterior al corte."
    ),
    "ck_periodo_coherencia": (
        "Ni el pago para no generar intereses ni el pago minimo pueden superar "
        "el saldo al corte."
    ),
    "ck_periodo_montos": "Ninguna cifra del periodo puede ser negativa.",
    "ck_msi_resto": "Los meses restantes no pueden superar los meses totales.",
    "ck_msi_totales": "Un plan a meses va de 1 a 60 mensualidades.",
    "ck_msi_monto": "La mensualidad debe ser mayor que cero.",
    "ck_usuarios_email": "El correo no tiene un formato valido.",
}


def _nombre_de_constraint(mensaje: str) -> str | None:
    """
    Extrae el nombre de la restriccion del mensaje de MySQL.

    El texto llega como:  Check constraint 'ck_mov_coherencia' is violated.
    """
    if "'" not in mensaje:
        return None
    return mensaje.split("'")[1]


def traducir_error(e: pymysql.err.MySQLError) -> Exception:
    """
    Traduce un error del driver a una excepcion de dominio.

    Se discrimina por CODIGO, no por clase: PyMySQL reparte los codigos entre
    IntegrityError, OperationalError e InternalError de una forma que no
    corresponde con lo que significan para el negocio.
    """
    codigo = e.args[0] if e.args else None
    mensaje = str(e.args[1]) if len(e.args) > 1 else str(e)

    if codigo == DUPLICADO:
        return ConflictoDeEstado("Ese registro ya existe.", {"sql": mensaje})
    if codigo == FK_INEXISTENTE:
        return ReglaDeNegocioViolada(
            "El registro hace referencia a algo que no existe o no es tuyo.",
            {"sql": mensaje},
        )
    if codigo == FK_REFERENCIADA:
        return ConflictoDeEstado(
            "No se puede eliminar: hay otros registros que dependen de este.",
            {"sql": mensaje},
        )
    if codigo == CHECK_VIOLADO:
        nombre = _nombre_de_constraint(mensaje)
        return ReglaDeNegocioViolada(
            MENSAJE_POR_CHECK.get(nombre, "Los datos violan una regla del modelo."),
            {"restriccion": nombre},
        )
    if codigo in (FUERA_DE_RANGO, DATO_MUY_LARGO):
        return ReglaDeNegocioViolada("Un valor esta fuera de rango.", {"sql": mensaje})
    if codigo == DEADLOCK:
        return ErrorDePersistencia("Conflicto de concurrencia. Reintentar.")
    if codigo == ESPERA_AGOTADA:
        return ErrorDePersistencia("La base tardo demasiado en liberar un registro.")
    return ErrorDePersistencia(f"Error de base de datos: {mensaje}")


class MySQLRepository:
    def __init__(self, cx):
        self.cx = cx

    # --- helpers de lectura -------------------------------------------------

    def _uno(self, sql: str, params: tuple = ()) -> dict | None:
        try:
            with self.cx.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
        except pymysql.err.MySQLError as e:
            raise traducir_error(e) from e

    def _todos(self, sql: str, params: tuple = ()) -> list[dict]:
        try:
            with self.cx.cursor() as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
        except pymysql.err.MySQLError as e:
            raise traducir_error(e) from e

    def _escalar(self, sql: str, params: tuple = (), default=None):
        fila = self._uno(sql, params)
        if not fila:
            return default
        return next(iter(fila.values()))

    # --- helpers de escritura -----------------------------------------------

    def _insertar(self, sql: str, params: tuple = ()) -> int:
        """
        INSERT que devuelve el id generado.

        cursor.lastrowid en lugar del SELECT last_insert_rowid() de SQLite:
        una consulta menos y sin riesgo de leer el id de otra sentencia.
        """
        try:
            with self.cx.cursor() as cur:
                cur.execute(sql, params)
                return cur.lastrowid
        except pymysql.err.MySQLError as e:
            raise traducir_error(e) from e

    def _ejecutar(self, sql: str, params: tuple = ()) -> int:
        """
        UPDATE/DELETE dentro de la transaccion del request. Devuelve cuantas
        filas cambiaron, que es lo que hace posible el bloqueo optimista: cero
        filas en un UPDATE que lleva `AND version = %s` significa que alguien
        escribio primero, y hay que releer y reintentar.
        """
        try:
            with self.cx.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount
        except pymysql.err.MySQLError as e:
            raise traducir_error(e) from e

    def _ejecutar_muchos(self, sql: str, filas: list[tuple]) -> int:
        if not filas:
            return 0
        try:
            with self.cx.cursor() as cur:
                cur.executemany(sql, filas)
                return cur.rowcount
        except pymysql.err.MySQLError as e:
            raise traducir_error(e) from e