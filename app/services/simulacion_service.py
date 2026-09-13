"""
Caso de uso: POST /simulaciones/compra — "me conviene comprar esto".

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

        `req.tarjetas`, cuando viene, manda sobre `plazos`: cada tarjeta con
        SUS plazos, y solo esas entran a la comparacion. Es la misma llamada
        que hace IAService.analizar_compra, para que las dos pantallas
        razonen sobre los mismos escenarios.
        """
        resultado = self.motor.simular(
            usuario_id, req.monto, req.plazos,
            opciones=[o.model_dump() for o in req.tarjetas]
            if req.tarjetas is not None else None,
            incluir_contado=req.incluir_contado,
        )
        return SimulacionResponse.model_validate(resultado)
