"""
Caso de uso: POST /simular/compra — "me conviene comprar esto".

La pantalla estrella y el unico endpoint de SOLO LECTURA por construccion:
este servicio no recibe ningun repositorio de escritura, asi que no puede
persistir nada aunque alguien lo intente.

Los escenarios no viables se devuelven marcados con su motivo, no se filtran:
el frontend los pinta deshabilitados CON la razon visible.
"""

from app.schemas.simulacion import SimulacionRequest, SimulacionResponse
from app.services.motor_service import MotorService


class SimulacionService:

    def __init__(self, motor_service: MotorService):
        self.motor = motor_service

    def simular(self, usuario_id: int, req: SimulacionRequest) -> SimulacionResponse:
        """
        `req.plazos` son los meses sin intereses que ofrece EL COMERCIO. No
        viven en la base porque dependen del punto de venta, no de la tarjeta:
        Liverpool da 18 meses con la misma tarjeta con la que la tienda de la
        esquina no da ninguno. Lista vacia = solo contado y revolvente.
        """
        resultado = self.motor.simular(usuario_id, req.monto, req.plazos)
        return SimulacionResponse.model_validate(resultado)