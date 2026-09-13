"""
Dependencia de sesion de base de datos.

Una conexion por request, con UNA transaccion por request: si el endpoint
termina bien se hace commit, y si algo revienta se revierte TODO lo que ese
request habia escrito.

Por eso los repositorios no commitean: solo ejecutan. El commit es de quien
sabe si el caso de uso completo salio bien, y ese es el request, no una
escritura suelta. Sin esto, un POST /onboarding que falla en la tercera
tarjeta dejaria al usuario a medio crear.

    con exito  ->  commit
    con error  ->  rollback  ->  la excepcion sigue hacia los handlers

El codigo es el mismo que con SQLite, pero el significado cambio: con MySQL
esto SOLO funciona porque la conexion se abre con autocommit=False. Con el
default del servidor (autocommit=1) cada escritura se confirma sola, estas
lineas no hacen nada, y el fallo no se nota hasta que alguien encuentra medio
onboarding guardado en produccion. La bandera vive en app/core/database.py.

El close() no cierra el socket: devuelve la conexion al pool, que hace ROLLBACK
al recibirla (reset=True). Es la segunda red: nada a medio escribir se hereda
al siguiente request que reutilice esa conexion.

En los tests se sobreescribe con app.dependency_overrides[get_conexion] para
apuntar a una transaccion que siempre termina en rollback, sin tocar ningun
servicio.
"""

from typing import Iterator

from app.core.database import conectar


def get_conexion() -> Iterator:
    cx = conectar()
    try:
        yield cx
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    finally:
        cx.close()