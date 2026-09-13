"""
Aplica Esquema.sql contra MySQL.

    python -m scripts.aplicar_esquema                  # base de config (.env)
    python -m scripts.aplicar_esquema --base X_test    # otra base (tests)
    python -m scripts.aplicar_esquema --recrear        # DROP DATABASE primero

Existe porque el DDL dejo de vivir en Python. Antes el esquema era una
constante en app/models/esquema.py que se ejecutaba con cx.executescript() al
arrancar la app; ahora la fuente de verdad es Esquema.sql y aplicarlo es un
paso de despliegue, no un efecto secundario del import.

Dos cosas que la DB-API no da y hay que resolver aqui:

  1. No existe executescript(). Hay que partir el archivo en sentencias.
  2. DELIMITER no es SQL: es una directiva del cliente `mysql`. El bloque que
     verifica la version del servidor la usa, asi que el separador de abajo la
     interpreta en vez de tropezarse con ella.

MySQL no tiene DDL transaccional: cada CREATE TABLE hace COMMIT implicito. Si
esto falla a la mitad, el arreglo es --recrear, no un rollback.
"""

import argparse
import sys
from pathlib import Path

import pymysql

from app.core.config import settings
from app.core.database import MYSQL_MINIMO, conectar_directo, version_servidor

ESQUEMA_SQL = Path(__file__).resolve().parent.parent / "Esquema.sql"


def dividir_sentencias(texto: str) -> list[str]:
    """
    Parte un script SQL en sentencias ejecutables.

    Respeta cadenas entre comillas (para no cortar en un ';' que sea dato),
    ignora los comentarios '--' y obedece las directivas DELIMITER, que es lo
    que permite que el CREATE PROCEDURE del guardia de version pase entero en
    una sola sentencia en vez de partirse en sus ';' internos.
    """
    delimitador = ";"
    actual: list[str] = []
    sentencias: list[str] = []
    comilla: str | None = None

    for linea in texto.splitlines():
        desnuda = linea.strip()
        if comilla is None:
            if desnuda.upper().startswith("DELIMITER "):
                pendiente = "".join(actual).strip()
                if pendiente:
                    sentencias.append(pendiente)
                actual = []
                delimitador = desnuda.split(None, 1)[1].strip()
                continue
            if not desnuda or desnuda.startswith("--"):
                continue

        i = 0
        while i < len(linea):
            car = linea[i]
            if comilla is not None:
                actual.append(car)
                if car == "\\" and comilla in ("'", '"') and i + 1 < len(linea):
                    actual.append(linea[i + 1])
                    i += 2
                    continue
                if car == comilla:
                    comilla = None
                i += 1
                continue
            if car in ("'", '"', "`"):
                comilla = car
                actual.append(car)
                i += 1
                continue
            # '--' solo abre comentario si va seguido de espacio o fin de linea
            if linea.startswith("--", i) and (
                i + 2 >= len(linea) or linea[i + 2] in " \t"
            ):
                break
            if linea.startswith(delimitador, i):
                sentencia = "".join(actual).strip()
                if sentencia:
                    sentencias.append(sentencia)
                actual = []
                i += len(delimitador)
                continue
            actual.append(car)
            i += 1
        actual.append("\n")

    resto = "".join(actual).strip()
    if resto:
        sentencias.append(resto)
    return sentencias


def aplicar(base: str, recrear: bool = False) -> None:
    if not ESQUEMA_SQL.exists():
        raise SystemExit(f"No se encontro {ESQUEMA_SQL}")

    sql = ESQUEMA_SQL.read_text(encoding="utf-8")

    # Esquema.sql fija el nombre 'no_te_endudes'. Para aplicarlo a otra base
    # (la de tests) se reescriben las dos sentencias que lo nombran.
    if base != "no_te_endudes":
        sql = sql.replace(
            "CREATE DATABASE IF NOT EXISTS no_te_endudes",
            f"CREATE DATABASE IF NOT EXISTS `{base}`",
        ).replace("USE no_te_endudes;", f"USE `{base}`;")

    cx = conectar_directo(database=None)
    try:
        version = version_servidor(cx)
        if version < MYSQL_MINIMO:
            raise SystemExit(
                f"MySQL {'.'.join(map(str, version))}: se requiere "
                f"{'.'.join(map(str, MYSQL_MINIMO))}+. Antes de esa version los CHECK "
                "se aceptan y se IGNORAN en silencio, y este esquema apoya casi "
                "toda su integridad en CHECKs."
            )

        with cx.cursor() as cur:
            if recrear:
                cur.execute(f"DROP DATABASE IF EXISTS `{base}`")
                print(f"  base '{base}' eliminada")

            sentencias = dividir_sentencias(sql)
            for n, sentencia in enumerate(sentencias, 1):
                try:
                    cur.execute(sentencia)
                    cur.fetchall() if cur.description else None
                except pymysql.err.MySQLError as e:
                    cabeza = " ".join(sentencia.split())[:90]
                    raise SystemExit(
                        f"\nFallo la sentencia {n}/{len(sentencias)}:\n"
                        f"  {cabeza}...\n  -> {e}\n\n"
                        "MySQL no tiene DDL transaccional: lo ya aplicado sigue ahi. "
                        "Reintentar con --recrear."
                    ) from e
        cx.commit()
        print(f"Esquema aplicado sobre '{base}' ({len(sentencias)} sentencias).")
    finally:
        cx.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Aplica Esquema.sql contra MySQL.")
    p.add_argument("--base", default=settings.db_name,
                   help=f"nombre de la base (default: {settings.db_name})")
    p.add_argument("--recrear", action="store_true",
                   help="DROP DATABASE antes de aplicar. Destruye los datos.")
    args = p.parse_args()

    if args.recrear:
        respuesta = input(f"Esto BORRA la base '{args.base}'. Escribir 'si': ")
        if respuesta.strip().lower() != "si":
            sys.exit("Cancelado.")

    aplicar(args.base, args.recrear)


if __name__ == "__main__":
    main()