"""
Caso de uso: GET /score.

El Financial Health Score es la pieza que une todo el producto: es la moneda
con la que se comparan las decisiones. Los cuatro componentes y sus pesos
salen del motor; este servicio solo los envuelve en el DTO.
"""

from app.schemas.score import ScoreResponse
from app.services.motor_service import MotorService


class ScoreService:

    def __init__(self, motor_service: MotorService):
        self.motor = motor_service

    def obtener(self, usuario_id: int) -> ScoreResponse:
        """
        OJO: EL SCORE DEL USUARIO VACIO MIENTE.

        Un usuario recien registrado que todavia no paso por POST /onboarding
        no tiene ingresos, tarjetas ni gastos. El motor entonces devuelve:

            liquidez     gasto_mensual = 0  -> 100 pts
            deuda        ingreso = 0        ->   0 pts
            utilizacion  limite total = 0   -> 100 pts
            flujo        gasto_mensual = 0  -> 100 pts
            total = 100(.30) + 0(.30) + 100(.20) + 100(.20) = 70  -> "Estable"

        O sea: alguien sin absolutamente nada ve un 70 en amarillo. No es que
        el score salga bajo, es que sale falsamente tranquilizador.

        RESUELTO SIN TOCAR EL CONTRATO: la señal vive en GET /auth/me, en el
        campo `onboarding_completo`. Con false, el frontend pinta el wizard en
        lugar del score. Se hizo asi y no agregando un campo a ScoreResponse
        porque ese schema vive en el contrato CONGELADO (domain/tipos.py,
        espejo de tipos.ts) y tocarlo obliga a espejarlo en el frontend.

        Queda un caso parecido que NO se puede resolver con una bandera: un
        usuario que SI completo el onboarding pero todavia no registra gastos
        saca un score muy alto, porque `variables_prom` sale de los ultimos 90
        dias de movimientos y arranca en cero. El score se vuelve realista
        conforme el usuario usa la app. Es el motor funcionando bien sobre los
        datos que tiene, no un error de calculo.
        """
        return ScoreResponse.model_validate(self.motor.score_de(usuario_id))