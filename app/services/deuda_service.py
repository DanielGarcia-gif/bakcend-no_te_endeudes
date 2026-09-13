"""
Caso de uso: GET /deuda/prioridad y POST /deuda/pagos — "que deuda pago
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
from app.repositories.periodo_repository import PeriodoRepository
from app.schemas.deuda import DeudaResponse, PagoRequest, PagoResponse
from app.services.motor_service import MotorService


class DeudaService:

    def __init__(
        self,
        movimiento_repository: MovimientoRepository,
        periodo_repository: PeriodoRepository,
        motor_service: MotorService,
    ):
        self.movimientos = movimiento_repository
        self.periodos = periodo_repository
        self.motor = motor_service

    def prioridad(self, usuario_id: int) -> DeudaResponse:
        return DeudaResponse.model_validate(self.motor.priorizar(usuario_id))

    def pagar(self, usuario_id: int, req: PagoRequest,
              idempotency_key: str | None = None) -> PagoResponse:
        # Idempotencia ANTES de nada, como en POST /movimientos: un reintento
        # del mismo gesto no vuelve a mover el saldo ni a abonar al corte.
        if idempotency_key:
            previo = self.movimientos.buscar_por_idempotencia(usuario_id,
                                                              idempotency_key)
            if previo is not None:
                return self._pago_repetido(usuario_id, str(previo.tarjeta_id))

        estado = self.motor.estado_de(usuario_id)

        # Primero el 404, luego las reglas: un id inexistente no es lo mismo
        # que un pago que no cabe en el saldo.
        reglas.tarjeta_o_404(estado, req.tarjeta_id)

        fecha = req.fecha or date.today().isoformat()
        error = reglas.validar_fecha(fecha) or reglas.validar_pago(
            estado, req.tarjeta_id, req.monto
        )
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

        # El mismo movimiento tipo='pago' que escribe POST /movimientos: no es
        # un camino alterno de escritura. El repositorio mueve los saldos.
        tarjeta_id = a_id_interno(req.tarjeta_id)
        self.movimientos.registrar(
            usuario_id=usuario_id,
            tipo="pago",
            medio=req.medio,
            monto=req.monto,
            fecha=fecha,
            tarjeta_id=tarjeta_id,
            idempotency_key=idempotency_key,
        )
        self._abonar_al_corte(usuario_id, tarjeta_id, req.monto)

        tarjeta = reglas.tarjeta_o_404(impacto["estado_resultante"], req.tarjeta_id)
        return PagoResponse(
            ok=True,
            score_antes=impacto["score_antes"],
            score_despues=impacto["score_despues"],
            ahorro_intereses_mensual=round(ahorro, 2),
            nuevo_saldo_tarjeta=tarjeta["saldo"],
        )

    def _abonar_al_corte(self, usuario_id: int, tarjeta_id: int, monto: float) -> None:
        """
        Para que GET /pagos-pendientes no siga pidiendo lo que ya se pago.

        Va al corte pendiente mas proximo a vencer de esa tarjeta (la vista ya
        los ordena por fecha limite); si no hay ninguno, al periodo abierto. Sin
        periodos capturados no hay a donde abonar y el pago vale igual.
        """
        cortes = {
            f["fecha_corte"].isoformat()
            for f in self.periodos.pagos_pendientes(usuario_id)
            if f["tarjeta_id"] == tarjeta_id
        }
        # La vista no expone el id del periodo: se ubica por su fecha de corte.
        # listar() los trae del mas reciente al mas viejo, asi que se toma el
        # ultimo que coincida, que es el que vence primero.
        pendientes = [p for p in self.periodos.listar(tarjeta_id, usuario_id)
                      if p.fecha_corte in cortes]
        periodo = pendientes[-1] if pendientes else self.periodos.abierto_de(
            tarjeta_id, usuario_id
        )
        if periodo is not None:
            self.periodos.registrar_pago(periodo.id, usuario_id, monto)

    def _pago_repetido(self, usuario_id: int, tarjeta_id: str) -> PagoResponse:
        """
        Respuesta a un reintento. Sin cambio que reportar: el efecto del pago
        original ya esta en el saldo, y repetir su ahorro seria mentir.
        """
        estado = self.motor.estado_de(usuario_id)
        score = self.motor.score_simple(usuario_id, estado)
        tarjeta = reglas.tarjeta_o_404(estado, tarjeta_id)
        return PagoResponse(
            ok=True,
            score_antes=score,
            score_despues=score,
            ahorro_intereses_mensual=0.0,
            nuevo_saldo_tarjeta=tarjeta["saldo"],
        )
