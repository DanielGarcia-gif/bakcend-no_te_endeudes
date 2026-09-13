"""
Caso de uso: POST /ingresos.

Registrar una fuente de ingreso y devolver como queda el score. El monto
mensual normalizado se DERIVA: no se guarda, para que cambiar la frecuencia
no deje datos rancios.
"""

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.tipos import FACTOR_MENSUAL
from app.repositories.ingreso_repository import IngresoRepository
from app.schemas.consultas import IngresoResumen
from app.schemas.ingresos import IngresoCreate, IngresoCreateResponse
from app.services.motor_service import MotorService


class IngresoService:

    def __init__(
        self,
        ingreso_repository: IngresoRepository,
        motor_service: MotorService,
    ):
        self.ingresos = ingreso_repository
        self.motor = motor_service

    def listar(self, usuario_id: int) -> list[IngresoResumen]:
        """
        Las fuentes de ingreso capturadas, con su equivalente mensual ya
        normalizado. GET /estado solo devuelve la suma; esta es la vista de
        gestion, donde el usuario ve de donde sale cada peso.
        """
        return [
            IngresoResumen(
                id=str(i.id),
                concepto=i.concepto,
                monto=i.monto,
                frecuencia=i.frecuencia,
                dia_pago=i.dia_pago,
                dia_pago_2=i.dia_pago_2,
                monto_mensual=round(i.monto_mensual, 2),
            )
            for i in self.ingresos.listar(usuario_id)
        ]

    def crear(self, usuario_id: int, datos: IngresoCreate) -> IngresoCreateResponse:
        error = reglas.validar_dias_de_pago(
            datos.frecuencia, datos.dia_pago, datos.dia_pago_2
        )
        if error:
            raise ReglaDeNegocioViolada(error)

        nuevo_id = self.ingresos.crear(
            usuario_id=usuario_id,
            concepto=datos.concepto,
            monto=datos.monto,
            frecuencia=datos.frecuencia,
            dia_pago=datos.dia_pago,
            dia_pago_2=datos.dia_pago_2,
        )

        return IngresoCreateResponse(
            id=nuevo_id,
            monto_mensual_normalizado=round(
                datos.monto * FACTOR_MENSUAL[datos.frecuencia], 2
            ),
            # Se recalcula despues de escribir: el ingreso mueve el componente
            # de deuda y, por la via de los ingresos programados, el de flujo.
            score_actualizado=self.motor.score_simple(usuario_id),
        )