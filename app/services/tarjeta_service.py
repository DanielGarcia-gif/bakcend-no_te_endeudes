"""
Caso de uso: alta de tarjeta y captura de terminos.

El flujo real es en dos pasos, y por eso son dos endpoints: el usuario da de
alta la tarjeta (banco, nombre, tipo) y despues captura los terminos.

Los terminos pueden llegar tecleados o prellenados por el frontend con lo que
Gemini haya leido del estado de cuenta. Al backend le da igual: recibe numeros
ya confirmados por el usuario y no habla con ningun servicio externo.

NUNCA se piden numeros de tarjeta. Decision de privacidad, va en el pitch.
"""

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.reglas import a_id_interno
from app.models.tarjeta import Tarjeta
from app.repositories.tarjeta_repository import TarjetaRepository
from app.schemas.consultas import TarjetaResumen
from app.schemas.tarjetas import (
    TarjetaCreate,
    TarjetaCreateResponse,
    TerminosRequest,
    TerminosResponse,
)
from app.services.motor_service import MotorService


class TarjetaService:

    def __init__(
        self,
        tarjeta_repository: TarjetaRepository,
        motor_service: MotorService,
    ):
        self.tarjetas = tarjeta_repository
        self.motor = motor_service

    def listar(self, usuario_id: int) -> list[TarjetaResumen]:
        """
        TODAS las tarjetas: credito y debito, con terminos y sin ellos.

        GET /estado solo devuelve las de credito completas, que son las que
        entran al motor. Esta es la vista de gestion, y es la unica forma de
        encontrar una tarjeta dada de alta a la que nunca se le pusieron
        terminos: sin este endpoint quedaba invisible para siempre.
        """
        return [self._a_resumen(t) for t in self.tarjetas.listar_todas(usuario_id)]

    def _a_resumen(self, t: Tarjeta) -> TarjetaResumen:
        return TarjetaResumen(
            id=str(t.id),
            banco=t.banco,
            nombre=t.nombre,
            tipo=t.tipo,
            activa=t.activa,
            limite=t.limite,
            saldo=t.saldo,
            disponible=t.disponible,
            tasa_anual=t.tasa_anual,
            pago_minimo=t.pago_minimo,
            dia_corte=t.dia_corte,
            dia_limite_pago=t.dia_limite_pago,
            monto_minimo_msi=t.monto_minimo_msi,
            msi=[
                {"monto_mensual": m.monto_mensual,
                 "meses_restantes": m.meses_restantes,
                 "descripcion": m.descripcion}
                for m in t.msi
            ],
            requiere_terminos=t.es_credito and not t.terminos_completos,
        )

    def crear(self, usuario_id: int, datos: TarjetaCreate) -> TarjetaCreateResponse:
        """
        Alta minima. Una tarjeta de credito nace sin terminos y no entra al
        motor hasta tenerlos (EstadoRepository la filtra), asi que el score no
        se mueve todavia.

        Para dar de alta varias tarjetas de un tiro al empezar, ver
        POST /onboarding.

        Las de debito no entran al score nunca: son una etiqueta que apunta al
        saldo_disponible del usuario.
        TODO: el briefing no dice si el frontend deberia pedir algo al dar de
        alta una debito. Por ahora requiere_terminos=False y no pide nada mas.
        """
        nuevo_id = self.tarjetas.crear(
            usuario_id=usuario_id,
            banco=datos.banco,
            nombre=datos.nombre,
            tipo=datos.tipo,
        )
        return TarjetaCreateResponse(
            id=str(nuevo_id),
            requiere_terminos=datos.tipo == "credito",
        )

    def actualizar_terminos(
        self,
        usuario_id: int,
        tarjeta_id: str,
        datos: TerminosRequest,
    ) -> TerminosResponse:
        # Lanza RecursoNoEncontrado si la tarjeta no es de este usuario.
        tarjeta = self.tarjetas.obtener(usuario_id, a_id_interno(tarjeta_id))
        if not tarjeta.es_credito:
            raise ReglaDeNegocioViolada(
                "Una tarjeta de debito no tiene limite, tasa ni fechas de corte"
            )

        error = reglas.validar_terminos_tarjeta(
            datos.dia_corte, datos.dia_limite_pago, datos.limite, datos.saldo
        )
        if error:
            raise ReglaDeNegocioViolada(error)

        self.tarjetas.actualizar_terminos(
            usuario_id=usuario_id,
            tarjeta_id=tarjeta.id,
            limite=datos.limite,
            saldo=datos.saldo,
            tasa_anual=datos.tasa_anual,
            pago_minimo=datos.pago_minimo,
            dia_corte=datos.dia_corte,
            dia_limite_pago=datos.dia_limite_pago,
            monto_minimo_msi=datos.monto_minimo_msi,
            msi=[m.model_dump() for m in datos.msi_vigentes],
        )

        # Con terminos completos la tarjeta ya entra al motor: el score cambia.
        return TerminosResponse(
            ok=True,
            score_actualizado=self.motor.score_simple(usuario_id),
        )