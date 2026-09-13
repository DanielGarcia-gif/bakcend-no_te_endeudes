"""
DTOs de POST /onboarding.

La captura inicial completa en una sola llamada: liquidez, ingresos, tarjetas y
gastos fijos. Sin esto, un usuario recien registrado no tiene forma de declarar
su liquidez y su score no significa nada.

Reutiliza los schemas de alta individual en vez de redefinir los mismos campos:
el formulario del onboarding y el de alta suelta capturan exactamente lo mismo y
deben validar igual. Un IngresoCreate que se acepta aqui y se rechaza en
POST /ingresos es un bug esperando.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.tipos import TipoTarjeta
from app.schemas.declarativas import IngresoCreate, RecurrenteCreate


class TerminosOnboarding(BaseModel):
    """
    Los terminos de una tarjeta de credito, capturados junto con el alta.

    Ya NO lleva `msi_vigentes`: los planes a meses tienen su propio recurso
    (POST /msi), porque uno puede estar ligado a la compra que lo origino y
    guardarlo aqui implicaba borrar y reinsertar la lista entera.
    """
    limite: float = Field(gt=0)
    saldo: float = Field(ge=0)
    tasa_anual: float = Field(ge=0, le=2, description="Fraccion: 38% se manda como 0.38.")
    pago_minimo: float = Field(ge=0)
    dia_corte: int = Field(ge=1, le=31)
    dia_limite_pago: int = Field(ge=1, le=31)
    monto_minimo_msi: float = Field(default=0, ge=0)


class TarjetaOnboarding(BaseModel):
    """
    Alta y terminos juntos: durante el onboarding no tiene sentido el flujo de
    dos pasos de POST /tarjetas + PATCH /tarjetas/{id}.

    `terminos` es obligatorio en las de credito y tiene que ir ausente en las de
    debito, que no tienen limite ni tasa. Lo valida OnboardingService antes de
    escribir nada, y ck_tarjetas_debito lo vuelve a imponer en la base.
    """
    banco: str = Field(min_length=1, max_length=80)
    nombre: str = Field(min_length=1, max_length=80)
    tipo: TipoTarjeta
    terminos: Optional[TerminosOnboarding] = None


class OnboardingRequest(BaseModel):
    """
    Todas las listas son opcionales salvo la liquidez, que es el unico dato que
    ningun otro endpoint capturaba.

    `gastos_fijos` usa RecurrenteCreate completo, con `fecha_inicio`,
    `frecuencia_meses` y `es_variable`. La version anterior pedia solo concepto,
    monto, dia y una categoria de texto libre, y daba por sentado que todo era
    mensual: la luz bimestral y el predial anual no eran capturables.
    """
    liquidez: float = Field(ge=0)
    ingresos: list[IngresoCreate] = []
    tarjetas: list[TarjetaOnboarding] = []
    gastos_fijos: list[RecurrenteCreate] = []


class OnboardingResponse(BaseModel):
    ok: bool
    liquidez: float
    ingresos_creados: int
    tarjetas_creadas: int
    gastos_fijos_creados: int
    # El score entero, para que el frontend pinte el resultado del onboarding
    # sin encadenar un GET /score detras.
    score_actualizado: int