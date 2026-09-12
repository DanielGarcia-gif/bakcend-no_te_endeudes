"""
Capa de acceso a datos.

Todo el SQL del proyecto vive aqui y en ningun otro sitio. Los servicios piden
datos a los repositorios; no conocen PyMySQL ni nombres de columna.

Tres reglas que valen para los diez repositorios, sin excepcion:

  1. Toda lectura filtra `WHERE eliminado_en IS NULL`. El borrado es logico, y
     una consulta que se olvide del filtro devuelve datos que el usuario cree
     haber borrado. El indice ix_mov_vivos existe para eso.

  2. Todo UPDATE/DELETE sobre una tabla con `usuario_id` lo lleva en el WHERE.
     El esquema ya lo cierra con FK compuestas (id, usuario_id), pero la
     defensa buena es la que no depende de que la otra funcione.

  3. Ninguno hace commit. La transaccion es del request (get_conexion), porque
     el commit es de quien sabe si el caso de uso completo salio bien.
"""

from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.base import MySQLRepository
from app.repositories.categoria_repository import CategoriaRepository
from app.repositories.estado_repository import EstadoRepository
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.msi_repository import MSIRepository
from app.repositories.periodo_repository import PeriodoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.repositories.usuario_repository import UsuarioRepository

__all__ = [
    "MySQLRepository",
    "UsuarioRepository",
    "CategoriaRepository",
    "IngresoRepository",
    "TarjetaRepository",
    "MSIRepository",
    "PeriodoRepository",
    "RecurrenteRepository",
    "MovimientoRepository",
    "AuditoriaRepository",
    "EstadoRepository",
]