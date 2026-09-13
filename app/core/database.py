"""
Conexion a MySQL.

Responsabilidad unica: entregar conexiones bien configuradas. No contiene
consultas de negocio (eso vive en app/repositories/) ni DDL (eso vive en
Esquema.sql y lo aplica scripts/aplicar_esquema.py).

    Antes: sqlite3.connect(archivo)  -> gratis, serializado, autocommit legacy
    Ahora: MySQL por TCP             -> handshake por conexion, bloqueo por fila

Los tres puntos que cambian de verdad al migrar, y por que:

1. autocommit=False EXPLICITO.
   MySQL abre las conexiones con autocommit=1. Con ese default, el commit() y
   el rollback() de get_conexion() se vuelven decorativos y la atomicidad de
   todo el diseno se evapora SIN LANZAR UN SOLO ERROR: un POST /onboarding que
   falla en la tercera tarjeta deja las dos primeras escritas, y un gasto que
   falla despues de mover el saldo deja el saldo movido sin su movimiento.
   Es el fallo mas silencioso de la migracion y se corrige con este parametro.

2. DictCursor.
   Sustituye a sqlite3.Row. Las filas siguen accediendose por nombre
   (f["saldo"]), que es como ya las leen los modelos.

3. Pool.
   sqlite3.connect() sobre un archivo es practicamente gratis, asi que abrir y
   cerrar una conexion por request no costaba nada. Contra MySQL cada request
   pagaria un handshake TCP + autenticacion. El pool las recicla.

InnoDB bloquea por fila, no la base completa como SQLite: dos requests del
mismo usuario ahora si corren en paralelo y todo bug de concurrencia latente
se manifiesta. Por eso innodb_lock_wait_timeout baja a 10s (el default de 50
es una eternidad para una API) y la aritmetica de saldos la hace el motor.
"""

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

from app.core.config import settings

# Version minima real, no aspiracional: antes de 8.0.16 MySQL ACEPTA los CHECK
# y los IGNORA en silencio. El esquema apoya casi toda su integridad en CHECKs.
MYSQL_MINIMO = (8, 0, 16)

# Una sola sentencia SET: PyMySQL manda init_command como un unico COM_QUERY y
# sin CLIENT_MULTI_STATEMENTS no acepta varias separadas por ';'.
_INIT_COMMAND = (
    "SET SESSION time_zone = '+00:00',"                       # se guarda UTC
    " SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,"
    "ERROR_FOR_DIVISION_BY_ZERO',"
    " SESSION innodb_lock_wait_timeout = 10"
)

_pool: PooledDB | None = None


def _crear_pool() -> PooledDB:
    return PooledDB(
        creator=pymysql,
        maxconnections=settings.db_pool_size,
        mincached=1,
        blocking=True,          # esperar a que se libere una, no reventar
        ping=1,                 # verificar la conexion al sacarla del pool
        reset=True,             # ROLLBACK al devolverla: nada a medias se hereda
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,       # <-- ver punto 1 del docstring
        init_command=_INIT_COMMAND,
    )


def conectar():
    """
    Devuelve una conexion del pool. El .close() del consumidor no cierra el
    socket: la regresa al pool (con ROLLBACK, por reset=True).
    """
    global _pool
    if _pool is None:
        _pool = _crear_pool()
    return _pool.connection()


def conectar_directo(database: str | None = None):
    """
    Conexion fuera del pool, para scripts (aplicar esquema, seed, tests).

    database=None conecta al servidor sin seleccionar base: es lo que necesita
    CREATE DATABASE la primera vez.
    """
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        init_command=_INIT_COMMAND,
    )


def version_servidor(cx) -> tuple[int, ...]:
    with cx.cursor() as cur:
        cur.execute("SELECT VERSION() AS v")
        crudo = cur.fetchone()["v"]
    numeros = crudo.split("-")[0].split(".")
    return tuple(int(n) for n in numeros[:3])


def verificar_conexion() -> dict:
    """
    Se invoca una vez desde el lifespan de main.py. NO crea tablas ni siembra
    datos: comprueba que la base contra la que vamos a hablar es la correcta y
    esta migrada, y falla ruidosamente si no.

    Es el reemplazo de init_db(): con SQLite el arranque creaba el esquema, con
    MySQL el esquema es un artefacto de despliegue.
    """
    cx = conectar()
    try:
        version = version_servidor(cx)
        if version < MYSQL_MINIMO:
            raise RuntimeError(
                f"MySQL {'.'.join(map(str, version))} es insuficiente: se requiere "
                f"{'.'.join(map(str, MYSQL_MINIMO))}+. Antes de esa version los CHECK "
                "se ignoran en silencio y el esquema no valida nada."
            )
        with cx.cursor() as cur:
            cur.execute(
                "SELECT version, nombre FROM schema_migrations"
                " ORDER BY version DESC LIMIT 1"
            )
            migracion = cur.fetchone()
        if migracion is None:
            raise RuntimeError(
                f"La base '{settings.db_name}' no tiene migraciones aplicadas. "
                "Ejecutar: python -m scripts.aplicar_esquema"
            )
        return {
            "mysql": ".".join(map(str, version)),
            "base": settings.db_name,
            "migracion": migracion["version"],
        }
    except pymysql.err.OperationalError as e:
        raise RuntimeError(
            f"No se pudo conectar a MySQL en {settings.db_host}:{settings.db_port}"
            f"/{settings.db_name}: {e}"
        ) from e
    finally:
        cx.close()