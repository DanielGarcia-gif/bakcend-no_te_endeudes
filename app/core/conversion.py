"""
Conversion de tipos entre MySQL y el resto de la aplicacion.

SQLite devolvia REAL -> float y TEXT -> str, y toda la app se escribio sobre
esa suposicion. MySQL devuelve DECIMAL -> decimal.Decimal, DATE -> datetime.date
y DATETIME -> datetime.datetime. Ese cambio de tipos, si se deja pasar, revienta
en el sitio menos util: dentro del motor, con un TypeError de
`Decimal * float` en mitad de un calculo de intereses.

LA REGLA, en una linea:

    Decimal vive entre el driver y el repositorio. Nunca sale de ahi.

    MySQL --Decimal--> repositorio --float--> servicio -> motor -> JSON
    JSON  ---float---> servicio -> repositorio --Decimal--> MySQL

Por que no Decimal en todas partes, que seria lo "correcto" para dinero:
`app/domain/motor/` esta portado tal cual desde motor.py y sus cifras estan
congeladas por tests (score 80, componentes 63/75/92/100, prioridad 80.9).
Opera con divisiones, potencias fraccionarias `(1+tasa/12)**-12` y round() de
presentacion. Migrarlo a Decimal cambiaria numeros del pitch a cambio de una
precision que a esta escala no se nota. Decimal se usa donde si importa: al
ESCRIBIR, para que lo que se guarda sea exactamente lo que MySQL espera en un
DECIMAL(14,2) y no un float con cola binaria.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")


def a_float(valor) -> float | None:
    """Decimal | int | float -> float. Frontera de SALIDA de la base."""
    if valor is None:
        return None
    return float(valor)


def a_entero(valor) -> int | None:
    """
    Decimal | int -> int. Frontera de SALIDA para lo que se CUENTA, no se suma.

    Hace falta porque MySQL promueve a DECIMAL en cuanto una expresion mezcla
    tipos, aunque el resultado sea conceptualmente un entero. El caso real que
    lo obligo:

        GREATEST(0, meses_totales - TIMESTAMPDIFF(MONTH, fecha_inicio, CURDATE()))

    son "meses restantes" —un conteo— y vuelve como Decimal('7'). Asignado tal
    cual, no falla al leerlo: falla tres capas mas adentro, en
    `monto_mensual * meses_restantes` dentro del calculo de intereses, con un
    TypeError de float por Decimal. Convertir aqui es lo que mantiene la regla
    de que el motor solo ve tipos nativos.
    """
    if valor is None:
        return None
    return int(valor)


def a_dinero(valor) -> Decimal | None:
    """
    float -> DECIMAL(14,2). Frontera de ENTRADA a la base.

    Se cuantiza a 2 decimales con redondeo comercial (HALF_UP). Sin esto, un
    float como 908.2500000000001 entra a un DECIMAL(14,2) y MySQL lo trunca o
    lo rechaza segun el sql_mode; con STRICT_ALL_TABLES activo, lo rechaza.

    Decimal(str(valor)) y no Decimal(valor): construir un Decimal desde un
    float arrastra su representacion binaria exacta (0.1 -> 0.1000000000000000055).
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def a_tasa(valor) -> Decimal | None:
    """float -> DECIMAL(5,4). `tarjetas.tasa_anual` guarda 0.3800, no 0.38."""
    if valor is None:
        return None
    return Decimal(str(valor)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def a_fecha_iso(valor) -> str | None:
    """date -> 'YYYY-MM-DD'. El contrato HTTP habla ISO, no objetos."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def a_instante_iso(valor) -> str | None:
    """
    datetime -> ISO-8601 con 'T' y sufijo 'Z'.

    La base guarda UTC (el esquema fija time_zone='+00:00' y la conversion a
    CDMX es de la app), pero MySQL devuelve datetimes ingenuos, sin tzinfo. Sin
    la 'Z' el frontend los interpreta como hora local y el historial se corre
    seis horas. Antes esto no se notaba porque SQLite devolvia el string ya
    formateado por datetime('now').
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(valor)


def a_bool(valor) -> bool:
    """TINYINT(1) -> bool."""
    return bool(valor)


def a_id(valor) -> str | None:
    """
    INT/BIGINT -> str. El contrato expone TODOS los ids como string.

    Dos razones: `movimientos.id` es BIGINT UNSIGNED y en JavaScript los
    enteros dejan de ser exactos pasados los 2^53; y hoy el contrato mezcla
    `str` en unas respuestas e `int` en otras para la misma clase de dato.
    """
    if valor is None:
        return None
    return str(valor)