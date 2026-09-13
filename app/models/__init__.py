"""
Capa de persistencia: la forma de las filas.

Sin ORM. Estas dataclasses son el espejo tipado de las tablas; no tienen
logica de negocio ni conocen FastAPI. No confundir con app/schemas/, que son
los DTOs de entrada y salida HTTP.

El DDL ya no vive aqui. Antes este paquete exportaba una constante ESQUEMA que
core/database.py ejecutaba al arrancar con executescript(); ahora la fuente de
verdad es Esquema.sql y se aplica con `python -m app.scripts.aplicar_esquema`. Un
esquema que se crea como efecto secundario del import esta bien para SQLite en
un archivo local, y esta mal para una base de servidor.

Ademas, cada desde_fila() es la frontera de tipos con MySQL: convierte DECIMAL
a float y DATE/DATETIME a str ISO. Ver app/core/conversion.py. si
"""

from app.models.categoria import Categoria
from app.models.ingreso import Ingreso
from app.models.movimiento import MedioMovimiento, Movimiento, TipoMovimiento
from app.models.periodo import PeriodoTarjeta
from app.models.recurrente import Recurrente
from app.models.tarjeta import MSIVigente, Tarjeta
from app.models.usuario import Usuario



__all__ = [
    "Usuario",
    "Categoria",
    "Ingreso",
    "Tarjeta",
    "MSIVigente",
    "PeriodoTarjeta",
    "Recurrente",
    "Movimiento",
    "TipoMovimiento",
    "MedioMovimiento",
]