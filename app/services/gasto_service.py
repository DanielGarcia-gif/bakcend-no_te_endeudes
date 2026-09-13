"""
Caso de uso: POST /gastos — "como voy".

Registra el gasto y responde con el MICRO-MOMENTO: cuanto movio el
componente afectado. No devuelve el score global redondeado porque un gasto
chico mueve menos de un punto entero y el usuario veria "80 -> 80".

Dos tipos de gasto, dos destinos distintos:

  espontaneo -> tabla `movimientos`, mueve saldo. Alimenta el promedio de
                gasto variable de los ultimos 90 dias.
  recurrente -> tabla `recurrentes`. Es un compromiso conocido: alimenta
                gastos.fijos y la proyeccion de flujo a 30 dias.
"""

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.reglas import a_id_interno
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.schemas.consultas import MovimientoResumen
from app.schemas.gastos import GastoRequest, GastoResponse
from app.services.motor_service import MotorService

# Que componente del score mueve cada medio de pago. El micro-momento muestra
# este componente, no el score global.
COMPONENTE_POR_MEDIO = {
    "debito": "liquidez",
    "credito": "utilizacion",
}

# Un recurrente siempre golpea la liquidez: sube el gasto mensual total y con
# el se encoge el colchon. El medio de pago da igual, porque la tabla
# `recurrentes` no guarda tarjeta: es un compromiso, no un cargo.
COMPONENTE_RECURRENTE = "liquidez"


class GastoService:

    def __init__(
        self,
        movimiento_repository: MovimientoRepository,
        recurrente_repository: RecurrenteRepository,
        motor_service: MotorService,
    ):
        self.movimientos = movimiento_repository
        self.recurrentes = recurrente_repository
        self.motor = motor_service

    def listar_movimientos(
        self, usuario_id: int, limite: int = 50
    ) -> list[MovimientoResumen]:
        """
        Historial: gastos, pagos e ingresos, del mas reciente al mas viejo.

        Es historial y nada mas: la fuente de verdad del saldo son las
        columnas, no esta lista.
        """
        return [
            MovimientoResumen(
                id=str(m.id),
                tipo=m.tipo,
                monto=m.monto,
                categoria=m.categoria,
                descripcion=m.descripcion,
                fecha=m.fecha,
                tarjeta_id=str(m.tarjeta_id) if m.tarjeta_id else None,
            )
            for m in self.movimientos.listar(usuario_id, limite)
        ]

    def registrar(self, usuario_id: int, req: GastoRequest) -> GastoResponse:
        estado = self.motor.estado_de(usuario_id)
        self._validar(estado, req)

        # Impacto ANTES de escribir: el motor trabaja sobre una copia, asi
        # que esto no altera nada.
        impacto = self.motor.evaluar_accion(estado, self._accion(req))

        if req.tipo == "recurrente":
            nuevo_id = self._registrar_recurrente(usuario_id, req)
            componente = COMPONENTE_RECURRENTE
        else:
            nuevo_id = self._registrar_espontaneo(usuario_id, req)
            componente = COMPONENTE_POR_MEDIO[req.medio]

        return GastoResponse(
            id=nuevo_id,
            score_antes=impacto["score_antes_exacto"],
            score_despues=impacto["score_despues_exacto"],
            componente_afectado=componente,
            componente_antes=impacto["desglose_antes"][componente],
            componente_despues=impacto["desglose"][componente],
        )

    # --- accion para el motor -----------------------------------------------

    def _accion(self, req: GastoRequest) -> dict:
        """
        Traduce la peticion a la accion que entiende el motor.

        Son DOS acciones distintas, no una: un espontaneo mueve saldo hoy, un
        recurrente sube el gasto fijo mensual y no toca nada hoy. Tratarlos
        igual devolveria un micro-momento que no corresponde con lo guardado.
        """
        if req.tipo == "recurrente":
            return {
                "tipo": "recurrente",
                "monto": req.monto,
                "dia": req.dia_del_mes,
                "concepto": req.categoria,
            }
        return {
            "tipo": "gasto",
            "monto": req.monto,
            "medio": req.medio,
            "tarjeta_id": req.tarjeta_id,
        }

    # --- escritura ----------------------------------------------------------

    def _registrar_espontaneo(self, usuario_id: int, req: GastoRequest) -> int:
        """Saldo y movimiento en la misma transaccion. Lo garantiza el repo."""
        return self.movimientos.registrar_gasto(
            usuario_id=usuario_id,
            monto=req.monto,
            categoria=req.categoria,
            fecha=req.fecha,
            tarjeta_id=a_id_interno(req.tarjeta_id),
        )

    def _registrar_recurrente(self, usuario_id: int, req: GastoRequest) -> int:
        """
        Un recurrente no mueve saldo hoy: describe un compromiso que se
        repite. Entra a `recurrentes` y aparece en la proyeccion de flujo.
        """
        return self.recurrentes.crear(
            usuario_id=usuario_id,
            concepto=req.categoria,
            monto=req.monto,
            dia_del_mes=req.dia_del_mes,
            categoria=req.categoria,
        )

    # --- validacion ---------------------------------------------------------

    def _validar(self, estado: dict, req: GastoRequest) -> None:
        error = reglas.validar_fecha(req.fecha)
        if error:
            raise ReglaDeNegocioViolada(error)

        if req.tipo == "recurrente":
            if req.dia_del_mes is None:
                raise ReglaDeNegocioViolada(
                    "Un gasto recurrente necesita el dia del mes en que cae"
                )
            # Y NADA MAS. Un recurrente no se valida contra la liquidez ni
            # contra la linea de credito: no cobra nada hoy, declara un
            # compromiso que se repite. Rechazar "renta $4,000" por no tener
            # $4,000 en la cuenta hoy no tendria ningun sentido.
            return

        if req.medio == "credito":
            if not req.tarjeta_id:
                raise ReglaDeNegocioViolada("Un gasto a credito necesita una tarjeta")
            # 404 si el id no existe, antes de mirar si cabe en la linea.
            reglas.tarjeta_o_404(estado, req.tarjeta_id)

        error = reglas.validar_gasto(estado, req)
        if error:
            raise ReglaDeNegocioViolada(error)