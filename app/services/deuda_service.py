"""
Caso de uso: GET /deuda/prioridad y POST /deuda/pagar — "que deuda pago
primero".

El ranking y sus razones los redacta el motor: los numeros salen de aritmetica
determinista que se puede auditar linea por linea. Si el frontend quiere
adornarlos con Gemini, adorna un texto que ya viene calculado.

Al pagar se devuelve el AHORRO EN INTERESES mensual, que es el beneficio
grande y hay que mostrarlo siempre: el score puede subir un solo punto, pero
dejar de pagar $142 al mes se entiende sin explicacion.
"""

from datetime import date

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.reglas import a_id_interno
from app.repositories.movimiento_repository import MovimientoRepository
from app.schemas.deuda import DeudaResponse, PagoRequest, PagoResponse
from app.services.motor_service import MotorService


class DeudaService:

    def __init__(
        self,
        movimiento_repository: MovimientoRepository,
        motor_service: MotorService,
    ):
        self.movimientos = movimiento_repository
        self.motor = motor_service

    def prioridad(self, usuario_id: int) -> DeudaResponse:
        return DeudaResponse.model_validate(self.motor.priorizar(usuario_id))

    def pagar(self, usuario_id: int, req: PagoRequest) -> PagoResponse:
        estado = self.motor.estado_de(usuario_id)

        # Primero el 404, luego las reglas: un id inexistente no es lo mismo
        # que un pago que no cabe en el saldo.
        reglas.tarjeta_o_404(estado, req.tarjeta_id)

        error = reglas.validar_pago(estado, req.tarjeta_id, req.monto)
        if error:
            raise ReglaDeNegocioViolada(error)

        # Se mide el impacto antes de escribir, sobre una copia del estado.
        impacto = self.motor.evaluar_accion(estado, {
            "tipo": "pago",
            "monto": req.monto,
            "tarjeta_id": req.tarjeta_id,
        })
        ahorro = (
            self.motor.intereses_de(estado)
            - self.motor.intereses_de(impacto["estado_resultante"])
        )

        self.movimientos.registrar_pago(
            usuario_id=usuario_id,
            tarjeta_id=a_id_interno(req.tarjeta_id),
            monto=req.monto,
            fecha=date.today().isoformat(),
        )

        tarjeta = next(
            t for t in impacto["estado_resultante"]["tarjetas"]
            if t["id"] == req.tarjeta_id
        )
        return PagoResponse(
            ok=True,
            score_antes=impacto["score_antes"],
            score_despues=impacto["score_despues"],
            ahorro_intereses_mensual=round(ahorro, 2),
            nuevo_saldo_tarjeta=tarjeta["saldo"],
        )