"""
Caso de uso: POST /onboarding — la captura inicial completa.

Por que existe: `usuarios.saldo_disponible` (la liquidez) no tiene ningun otro
endpoint. Se crea en 0 y solo baja: gastar la baja, pagar una tarjeta la baja,
nada la sube. Y como no hay API bancaria, ese numero solo puede llegar
tecleado por el usuario. Sin este endpoint, quien se registra de verdad se
queda en cero para siempre y su score no significa nada.

Coordina cuatro repositorios en UNA sola transaccion, la del request: si la
tercera tarjeta esta mal, no queda ni la liquidez ni los ingresos anteriores.
Ver app/dependencies/database.py.

Se corre UNA vez. Despues se usan los endpoints granulares (POST /ingresos,
POST /tarjetas), que es donde vive la edicion.
"""

from app.core.exceptions import ConflictoDeEstado, ReglaDeNegocioViolada
from app.domain import reglas
from app.repositories.categoria_repository import CategoriaRepository
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.onboarding import (
    OnboardingRequest,
    OnboardingResponse,
    TarjetaOnboarding,
)
from app.services.motor_service import MotorService


def tiene_datos_capturados(
    ingresos: IngresoRepository,
    tarjetas: TarjetaRepository,
    usuario_id: int,
    recurrentes: RecurrenteRepository | None = None,
) -> bool:
    """
    Si el usuario ya paso por la captura inicial.

    Funcion de modulo y no metodo porque la usan dos servicios: este, para
    no dejar correr el onboarding dos veces, y AuthService, para decirle al
    frontend si tiene que pintar el wizard. Una sola definicion de "ya
    capturo algo" para que las dos respuestas no puedan contradecirse.
    """
    return bool(
        ingresos.listar(usuario_id)
        or tarjetas.listar(usuario_id)
        or (recurrentes is not None and recurrentes.listar(usuario_id))
    )


class OnboardingService:

    def __init__(
        self,
        usuario_repository: UsuarioRepository,
        ingreso_repository: IngresoRepository,
        tarjeta_repository: TarjetaRepository,
        recurrente_repository: RecurrenteRepository,
        categoria_repository: CategoriaRepository,
        motor_service: MotorService,
    ):
        self.usuarios = usuario_repository
        self.ingresos = ingreso_repository
        self.tarjetas = tarjeta_repository
        self.recurrentes = recurrente_repository
        self.categorias = categoria_repository
        self.motor = motor_service

    def ejecutar(self, usuario_id: int, datos: OnboardingRequest) -> OnboardingResponse:
        self._verificar_que_no_se_corrio_ya(usuario_id)
        self._validar(datos)
        # Las claves de categoria tambien se resuelven antes de escribir: una
        # clave invalida en el ultimo gasto fijo no debe llegar a mitad de las
        # escrituras (aunque get_conexion lo revertiria igual).
        categorias = [self.categorias.resolver(g.categoria) for g in datos.gastos_fijos]

        # A partir de aqui solo escrituras: todo lo que puede fallar por regla
        # de negocio ya se comprobo. Y si aun asi revienta algo, get_conexion
        # revierte el request completo.
        self.usuarios.fijar_liquidez(usuario_id, datos.liquidez)

        for ingreso in datos.ingresos:
            self.ingresos.crear(
                usuario_id=usuario_id,
                concepto=ingreso.concepto,
                monto=ingreso.monto,
                frecuencia=ingreso.frecuencia,
                dia_pago=ingreso.dia_pago,
                dia_pago_2=ingreso.dia_pago_2,
                fecha_ancla=ingreso.fecha_ancla,
                ajuste_mes_corto=ingreso.ajuste_mes_corto,
            )

        for tarjeta in datos.tarjetas:
            self._crear_tarjeta(usuario_id, tarjeta)

        for gasto, categoria_id in zip(datos.gastos_fijos, categorias):
            self.recurrentes.crear(
                usuario_id=usuario_id,
                concepto=gasto.concepto,
                monto=gasto.monto,
                dia_del_mes=gasto.dia_del_mes,
                categoria_id=categoria_id,
                fecha_inicio=gasto.fecha_inicio,
                es_variable=gasto.es_variable,
                frecuencia_meses=gasto.frecuencia_meses,
                ajuste_mes_corto=gasto.ajuste_mes_corto,
                fecha_fin=gasto.fecha_fin,
            )

        return OnboardingResponse(
            ok=True,
            liquidez=datos.liquidez,
            ingresos_creados=len(datos.ingresos),
            tarjetas_creadas=len(datos.tarjetas),
            gastos_fijos_creados=len(datos.gastos_fijos),
            # Lee dentro de la misma transaccion, asi que ve todo lo que se
            # acaba de escribir aunque todavia no haya commit.
            score_actualizado=self.motor.score_simple(usuario_id),
        )

    # --- escritura ----------------------------------------------------------

    def _crear_tarjeta(self, usuario_id: int, tarjeta: TarjetaOnboarding) -> None:
        """
        Alta y terminos de un tiro. Una tarjeta de credito sin terminos no
        entrara al motor (EstadoRepository la filtra), por eso el onboarding
        los exige en vez de dejarla a medias.
        """
        tarjeta_id = self.tarjetas.crear(
            usuario_id=usuario_id,
            banco=tarjeta.banco,
            nombre=tarjeta.nombre,
            tipo=tarjeta.tipo,
        )
        if tarjeta.terminos is None:
            return

        # Los terminos van por el mismo PATCH parcial que POST /tarjetas usa
        # despues del alta; los MSI ya no viajan aqui (tienen POST /msi).
        self.tarjetas.actualizar(tarjeta_id, usuario_id, tarjeta.terminos.model_dump())

    # --- validacion ---------------------------------------------------------

    def _verificar_que_no_se_corrio_ya(self, usuario_id: int) -> None:
        """
        El onboarding no es idempotente: volver a llamarlo duplicaria ingresos
        y tarjetas. Un doble submit del formulario no deberia dejar al usuario
        con dos nominas.
        """
        if tiene_datos_capturados(self.ingresos, self.tarjetas, usuario_id,
                                  self.recurrentes):
            raise ConflictoDeEstado(
                "Este usuario ya tiene datos capturados. Usa POST /ingresos o "
                "POST /tarjetas para agregar mas."
            )

    def _validar(self, datos: OnboardingRequest) -> None:
        """Todo se valida ANTES de escribir la primera fila."""
        for ingreso in datos.ingresos:
            error = reglas.validar_dias_de_pago(
                ingreso.frecuencia, ingreso.dia_pago, ingreso.dia_pago_2
            )
            if error:
                raise ReglaDeNegocioViolada(f"{ingreso.concepto}: {error}")

        for tarjeta in datos.tarjetas:
            self._validar_tarjeta(tarjeta)

    def _validar_tarjeta(self, tarjeta: TarjetaOnboarding) -> None:
        if tarjeta.tipo == "debito":
            # La debito es una etiqueta que apunta al saldo_disponible: no
            # tiene limite, tasa ni fechas de corte, y no entra al score.
            if tarjeta.terminos is not None:
                raise ReglaDeNegocioViolada(
                    f"{tarjeta.nombre}: una tarjeta de debito no lleva terminos"
                )
            return

        if tarjeta.terminos is None:
            raise ReglaDeNegocioViolada(
                f"{tarjeta.nombre}: una tarjeta de credito necesita sus terminos "
                "(limite, saldo, tasa, pago minimo y fechas)"
            )

        t = tarjeta.terminos
        error = reglas.validar_terminos_tarjeta(
            t.dia_corte, t.dia_limite_pago, t.limite, t.saldo
        )
        if error:
            raise ReglaDeNegocioViolada(f"{tarjeta.nombre}: {error}")