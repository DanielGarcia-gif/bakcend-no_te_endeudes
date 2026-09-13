"""
DTOs de `tarjetas`, `msi_vigentes` y `periodos_tarjeta`.

TRES CAMBIOS RESPECTO AL CONTRATO VIEJO

1. `PUT /tarjetas/{id}/terminos` desaparece; lo cubre `PATCH /tarjetas/{id}`.
   El PUT obligaba a mandar los siete campos completos aunque solo cambiara el
   saldo, y ahi es donde se pierden datos cuando el formulario no traia alguno.

2. Los MSI salen del cuerpo de los terminos. Antes `terminos` llevaba
   `msi_vigentes: []` y guardarlos BORRABA la lista entera para reinsertarla.
   Eso deja de ser posible: un MSI puede estar ligado a la compra que lo
   origino, y borrarlo destruiria ese vinculo. Ahora tienen su propio recurso.

3. `version` en el PATCH. Los terminos son lo mas releido y reescrito de la app
   —el usuario abre la pantalla, va por su estado de cuenta y vuelve diez
   minutos despues—, y mientras tanto un gasto pudo mover el saldo. Sin
   `version`, guardar el formulario lo pisa en silencio.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.domain.tipos import TipoTarjeta


# =====================================================================
# TARJETAS
# =====================================================================

class TarjetaCreate(BaseModel):
    """
    Alta minima: el usuario suele tener la tarjeta a mano antes que su estado
    de cuenta. Los terminos se capturan despues con PATCH.

    No se piden numeros de tarjeta. Nunca. Es decision de privacidad.
    """
    banco: str = Field(min_length=1, max_length=80)
    nombre: str = Field(min_length=1, max_length=80)
    tipo: TipoTarjeta


class TarjetaUpdate(BaseModel):
    """
    PATCH parcial. Todo opcional; `version` habilita el bloqueo optimista.

    Una tarjeta de debito no admite ninguno de los campos de credito:
    ck_tarjetas_debito lo rechaza en la base con un 422 explicando la regla.
    """
    banco: Optional[str] = Field(default=None, min_length=1, max_length=80)
    nombre: Optional[str] = Field(default=None, min_length=1, max_length=80)
    limite: Optional[float] = Field(default=None, gt=0)
    saldo: Optional[float] = Field(default=None, ge=0)
    tasa_anual: Optional[float] = Field(
        default=None, ge=0, le=2,
        description="Fraccion, no porcentaje: 38% se manda como 0.38.",
    )
    pago_minimo: Optional[float] = Field(default=None, ge=0)
    dia_corte: Optional[int] = Field(default=None, ge=1, le=31)
    dia_limite_pago: Optional[int] = Field(default=None, ge=1, le=31)
    monto_minimo_msi: Optional[float] = Field(default=None, ge=0)
    activa: Optional[bool] = None
    version: Optional[int] = Field(
        default=None,
        description="La version que traia la tarjeta al leerla. Si cambio, devuelve 409.",
    )


class MSIResumen(BaseModel):
    id: str
    tarjeta_id: str
    descripcion: Optional[str] = None
    monto_total: Optional[float] = None
    monto_mensual: float
    meses_totales: int
    # Derivado de la fecha, no el contador guardado: un contador mutable que
    # nadie decrementa es una deuda que parece pagarse sola.
    meses_restantes: int
    saldo_pendiente: float
    fecha_inicio: str
    # NULL cuando el plan se capturo de un estado de cuenta y no de una compra
    # registrada en la app.
    movimiento_id: Optional[str] = None


class TarjetaResumen(BaseModel):
    id: str
    banco: str
    nombre: str
    tipo: str
    activa: bool
    limite: Optional[float] = None
    saldo: Optional[float] = None
    disponible: Optional[float] = None   # derivado: limite - saldo. Nunca se guarda.
    tasa_anual: Optional[float] = None
    pago_minimo: Optional[float] = None
    dia_corte: Optional[int] = None
    dia_limite_pago: Optional[int] = None
    monto_minimo_msi: Optional[float] = None
    msi: list[MSIResumen] = []
    # Una tarjeta de credito sin terminos no entra al score ni al simulador:
    # le faltan los numeros con los que se calculan.
    requiere_terminos: bool
    version: int


# =====================================================================
# MSI
# =====================================================================

class MSICreate(BaseModel):
    """
    Un plan a meses capturado de un estado de cuenta, sin compra en la app.

    Queda con `movimiento_id` NULL a proposito: esa compra ocurrio antes de que
    el usuario usara la app, y no se va a inventar un movimiento para ella —
    seria un hecho falso en la bitacora.

    Para una compra NUEVA a meses no se usa esto: se manda el bloque `msi`
    dentro de POST /movimientos, y asi la compra y su plan nacen juntos en una
    sola transaccion.
    """
    tarjeta_id: str
    monto_mensual: float = Field(gt=0)
    meses_totales: int = Field(ge=1, le=60)
    meses_restantes: int = Field(ge=0, le=60)
    fecha_inicio: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    descripcion: Optional[str] = Field(default=None, max_length=160)
    monto_total: Optional[float] = Field(default=None, gt=0)


# =====================================================================
# PERIODOS DE CORTE
# =====================================================================

class PeriodoCreate(BaseModel):
    """
    Abre un corte. Las tres fechas son explicitas en vez de derivarse de
    `dia_corte`, porque los bancos recorren el corte por fines de semana y
    festivos, y el usuario tiene la fecha real en su estado de cuenta.
    """
    fecha_inicio: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_corte: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_limite_pago: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PeriodoResumen(BaseModel):
    """
    TRES CIFRAS QUE LA GENTE CONFUNDE y que aqui quedan separadas:

      saldo_al_corte     lo que debias el dia del corte.
      pago_minimo        lo que el banco exige para no caer en mora.
      pago_no_intereses  saldo al corte menos lo que esta en promocion a meses.
                         Es el numero que de verdad importa: pagando esto la
                         tasa no corre.
    """
    id: str
    tarjeta_id: str
    fecha_inicio: str
    fecha_corte: str
    fecha_limite_pago: str
    saldo_al_corte: float
    pago_minimo: float
    pago_no_intereses: float
    msi_del_periodo: float
    pagado: float
    intereses_generados: float
    cerrado: bool
    falta_para_no_intereses: float
    falta_para_no_mora: float


class PagoPendiente(BaseModel):
    """
    El consejo accionable: paga `falta_para_no_intereses` antes de
    `fecha_limite_pago` y la tasa no corre.
    """
    tarjeta_id: str
    banco: str
    tarjeta: str
    fecha_corte: str
    fecha_limite_pago: str
    dias_restantes: int
    saldo_al_corte: float
    pago_minimo: float
    pago_no_intereses: float
    pagado: float
    falta_para_no_intereses: float
    falta_para_no_mora: float