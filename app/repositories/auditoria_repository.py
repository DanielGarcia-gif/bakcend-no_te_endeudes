"""
SQL de la tabla `auditoria`.

Repositorio nuevo. El borrado logico resuelve la mitad del problema (el dato no
desaparece), pero no la otra: QUE cambio, QUIEN lo cambio y COMO estaba antes.

Se escribe desde el repositorio y NO con triggers, a proposito. Un trigger
esconde el efecto (nada en el codigo dice que esa escritura ocurre), es dificil
de probar, y sobre todo no sabe quien es el usuario de la sesion ni desde que
endpoint se llamo. El `origen` ('api:POST /movimientos') es justo el dato que
un trigger no puede conocer y el que convierte la tabla en algo consultable.

Regla practica: una fila aqui en todo UPDATE o borrado logico que toque dinero
—montos, saldos, limites, fechas de corte—. No en las lecturas, y no en cada
INSERT trivial: una auditoria que registra todo no se lee nunca.

Sin FK a usuarios, tambien a proposito: la auditoria debe sobrevivir al borrado
del usuario, que es justo cuando mas se necesita.
"""

import json
from datetime import date, datetime
from decimal import Decimal

from app.repositories.base import MySQLRepository

CREADO = "creado"
ACTUALIZADO = "actualizado"
ELIMINADO = "eliminado"
RESTAURADO = "restaurado"


def _serializable(valor):
    """
    Prepara un dict para la columna JSON.

    Decimal y date no son serializables por json.dumps, y son exactamente los
    tipos que devuelve MySQL para las columnas que mas importa auditar.
    """
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def _a_json(datos: dict | None) -> str | None:
    if datos is None:
        return None
    return json.dumps(
        {k: _serializable(v) for k, v in datos.items()},
        ensure_ascii=False,
    )


class AuditoriaRepository(MySQLRepository):

    def registrar(
        self,
        tabla: str,
        registro_id: int,
        accion: str,
        usuario_id: int | None = None,
        datos_antes: dict | None = None,
        datos_despues: dict | None = None,
        origen: str | None = None,
    ) -> int:
        """
        Deja constancia de un cambio.

        Va en la MISMA transaccion que el cambio que describe: si el request
        revienta despues, la auditoria se revierte con el. Una auditoria que
        registra cambios que no ocurrieron es peor que no tenerla.
        """
        return self._insertar(
            "INSERT INTO auditoria"
            " (tabla, registro_id, accion, usuario_id, datos_antes, datos_despues, origen)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (tabla, registro_id, accion, usuario_id,
             _a_json(datos_antes), _a_json(datos_despues), origen),
        )

    def historial(self, tabla: str, registro_id: int, limite: int = 50) -> list[dict]:
        return self._todos(
            "SELECT id, tabla, registro_id, accion, usuario_id,"
            " datos_antes, datos_despues, origen, ocurrido_en"
            " FROM auditoria WHERE tabla = %s AND registro_id = %s"
            " ORDER BY ocurrido_en DESC, id DESC LIMIT %s",
            (tabla, registro_id, limite),
        )

    def de_usuario(self, usuario_id: int, limite: int = 50) -> list[dict]:
        return self._todos(
            "SELECT id, tabla, registro_id, accion, usuario_id,"
            " datos_antes, datos_despues, origen, ocurrido_en"
            " FROM auditoria WHERE usuario_id = %s"
            " ORDER BY ocurrido_en DESC, id DESC LIMIT %s",
            (usuario_id, limite),
        )