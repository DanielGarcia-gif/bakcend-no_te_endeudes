"""
Caso de uso: GET /estado.

El endpoint mas simple del sistema, y a proposito: es la frontera que el
frontend consume desde la hora 2. Toda la complejidad esta en armar_estado().
"""

from app.schemas.estado import EstadoResponse
from app.services.motor_service import MotorService


class EstadoService:

    def __init__(self, motor_service: MotorService):
        self.motor = motor_service

    def obtener(self, usuario_id: int) -> EstadoResponse:
        """
        El dict del motor se valida contra el contrato congelado al salir.
        Si armar_estado() empieza a devolver algo que no cuadra con Estado,
        se revienta aqui y no en el frontend.
        """
        return EstadoResponse.model_validate(self.motor.estado_de(usuario_id))