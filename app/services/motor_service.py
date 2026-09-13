"""
MotorService — la unica puerta de entrada al motor desde la aplicacion.

El motor (app/domain/motor/) es puro y nunca toca la base. Este servicio es
quien le trae el `estado` desde el repositorio y le pide el calculo:

    Router -> Service -> MotorService -> [motor puro]
                              |
                              +-------> EstadoRepository -> SQLite

Nadie mas importa app.domain.motor. Si algun servicio necesita un calculo
nuevo, se agrega un metodo aqui: asi el motor sigue siendo sustituible y
testeable sin base de datos.

Devuelve dicts crudos del motor a proposito. La conversion a DTOs Pydantic la
hace cada servicio de caso de uso, que es quien conoce la forma de SU response.
"""

from app.domain import motor
from app.repositories.estado_repository import EstadoRepository


class MotorService:

    def __init__(self, estado_repository: EstadoRepository):
        self.estados = estado_repository

    # --- estado -------------------------------------------------------------

    def estado_de(self, usuario_id: int) -> dict:
        """El `estado` crudo, tal como lo consume el motor."""
        return self.estados.armar(usuario_id)

    # --- score --------------------------------------------------------------

    def score_de(self, usuario_id: int, estado: dict | None = None) -> dict:
        """
        Score completo listo para GET /score.

        `estado` opcional para no volver a leer la base cuando quien llama ya
        lo tiene en la mano (por ejemplo despues de escribir un movimiento).
        """
        estado = estado if estado is not None else self.estado_de(usuario_id)
        return self.score_de_estado(estado)

    def score_de_estado(self, estado: dict) -> dict:
        """
        Igual que score_de() pero sobre un estado ya armado. Aqui se completa
        lo que calcular_score() no devuelve: la banda, la serie de 30 dias y
        los dos agregados que el frontend muestra junto al score.
        """
        resultado = motor.calcular_score(estado)
        nombre_banda, color = motor.banda(resultado["score"])
        serie, minimo, dia_minimo = motor.proyectar_flujo(estado)

        return {
            "score": resultado["score"],
            "score_exacto": resultado["score_exacto"],
            "banda": nombre_banda,
            "color": color,
            "componentes": resultado["componentes"],
            "pesos": {k: round(v * 100) for k, v in motor.PESOS.items()},
            "gasto_mensual_total": resultado["gasto_mensual_total"],
            "obligaciones_mensuales": round(motor.obligaciones_mensuales(estado), 2),
            "intereses_mensuales": round(motor.intereses_mensuales(estado), 2),
            "flujo_30d": {
                "serie": serie,
                "minimo": round(minimo, 2),
                "dia_minimo": dia_minimo,
            },
        }

    def score_simple(self, usuario_id: int, estado: dict | None = None) -> int:
        """Solo el entero, para los endpoints que devuelven score_actualizado."""
        estado = estado if estado is not None else self.estado_de(usuario_id)
        return motor.calcular_score(estado)["score"]

    # --- evaluacion de acciones hipoteticas ---------------------------------

    def evaluar_accion(self, estado: dict, accion: dict) -> dict:
        """
        Antes/despues de una accion, SIN escribir nada.

        Se usa para el micro-momento del gasto y para el impacto de un pago.
        Recibe el estado en vez del usuario_id porque quien llama suele
        necesitar el mismo estado para validar reglas antes de escribir.
        """
        return motor.evaluar(estado, accion)

    # --- simulador (solo lectura) -------------------------------------------

    def simular(self, usuario_id: int, monto: float, plazos: list[int]) -> dict:
        """
        La pantalla estrella. `plazos` son los meses sin intereses que ofrece
        EL COMERCIO, no la tarjeta: por eso llegan en el request y no de la base.
        """
        estado = self.estado_de(usuario_id)
        escenarios = motor.simular_compra(estado, monto, plazos)
        viables = [e for e in escenarios if e["viable"]]
        return {
            "monto": monto,
            "plazos_ofrecidos": plazos,
            "score_actual": motor.calcular_score(estado)["score"],
            # simular_compra ya ordena: viables primero, mejor score arriba,
            # desempate por holgura restante. El primero es la recomendacion.
            "recomendado": viables[0] if viables else None,
            "escenarios": escenarios,
        }

    # --- priorizacion de deuda ----------------------------------------------

    def priorizar(self, usuario_id: int, estado: dict | None = None) -> dict:
        estado = estado if estado is not None else self.estado_de(usuario_id)
        return {
            "ranking": motor.priorizar_deudas(estado),
            "intereses_totales_mes": round(motor.intereses_mensuales(estado), 2),
        }

    def intereses_de(self, estado: dict) -> float:
        """Intereses mensuales de un estado. Sirve para medir el ahorro de un pago."""
        return motor.intereses_mensuales(estado)