"""
DTOs de las tablas DECLARATIVAS: `ingresos`, `recurrentes` y sus confirmaciones.

Una declaracion es una foto del mundo del usuario ("gano 6,000 quincenales",
"la luz me llega cada dos meses"). No es historia y no mueve ningun saldo. El
dinero solo se mueve cuando el usuario CONFIRMA que un cobro ocurrio, y esa
confirmacion crea un movimiento con FK de vuelta a su declaracion.

    declaracion  ->  el usuario confirma  ->  movimiento
                                                 |
                           FK de vuelta a su declaracion

Nada "esperado" o "pendiente" se guarda como fila. Se deriva al vuelo
(GET /pendientes) y solo se materializa al confirmar.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.domain.tipos import Frecuencia

AjusteMesCorto = Literal["ultimo_dia", "mes_siguiente"]


# =====================================================================
# INGRESOS
# =====================================================================

class IngresoCreate(BaseModel):
    """
    DOS FAMILIAS DE FRECUENCIA, dos formas de definirse:

      semanal, catorcenal    -> `fecha_ancla` (el ciclo se cuenta en dias)
      quincenal, mensual     -> `dia_pago` (+ `dia_pago_2` solo en quincenal)

    El validador de abajo lo impone, y ck_ingresos_ancla lo vuelve a imponer en
    la base. La regla anterior EXIGIA dia_pago_2 en catorcenal, que es justo lo
    que el esquema prohibe: ningun ingreso catorcenal era registrable.
    """
    concepto: str = Field(min_length=1, max_length=120)
    monto: float = Field(gt=0)
    frecuencia: Frecuencia
    dia_pago: Optional[int] = Field(default=None, ge=1, le=31)
    dia_pago_2: Optional[int] = Field(default=None, ge=1, le=31)
    fecha_ancla: Optional[str] = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="Fecha de un cobro real. Obligatoria en semanal y catorcenal.",
    )
    ajuste_mes_corto: AjusteMesCorto = "ultimo_dia"

    @model_validator(mode="after")
    def _familia_correcta(self):
        if self.frecuencia in ("semanal", "catorcenal"):
            if self.fecha_ancla is None:
                raise ValueError(
                    f"Un ingreso {self.frecuencia} se define por su fecha de "
                    "referencia: indica cuando fue un pago real"
                )
            if self.dia_pago_2 is not None:
                raise ValueError(
                    f"Un ingreso {self.frecuencia} no lleva segundo dia de pago: "
                    "su ciclo se cuenta en dias, no en dias del mes"
                )
        else:
            if self.dia_pago is None:
                raise ValueError(f"Un ingreso {self.frecuencia} necesita su dia de pago")
            if self.frecuencia == "mensual" and self.dia_pago_2 is not None:
                raise ValueError("Un ingreso mensual solo tiene un dia de pago")
            if self.frecuencia == "quincenal":
                if self.dia_pago_2 is None:
                    raise ValueError("Un ingreso quincenal necesita sus dos dias de pago")
                if self.dia_pago == self.dia_pago_2:
                    raise ValueError("Los dos dias de pago no pueden ser el mismo")
        return self


class IngresoUpdate(BaseModel):
    """PATCH: solo lo que viene se escribe. Sin campos obligatorios."""
    concepto: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monto: Optional[float] = Field(default=None, gt=0)
    dia_pago: Optional[int] = Field(default=None, ge=1, le=31)
    dia_pago_2: Optional[int] = Field(default=None, ge=1, le=31)
    fecha_ancla: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    ajuste_mes_corto: Optional[AjusteMesCorto] = None
    activo: Optional[bool] = None


class IngresoResumen(BaseModel):
    id: str
    concepto: str
    monto: float
    frecuencia: str
    dia_pago: Optional[int] = None
    dia_pago_2: Optional[int] = None
    fecha_ancla: Optional[str] = None
    ajuste_mes_corto: str
    activo: bool
    # Los tres derivados. Ninguno se guarda: `monto_mensual` sale de la
    # frecuencia, y los otros dos de MAX(movimientos.fecha) mas el calendario.
    monto_mensual: float
    ultimo_cobro: Optional[str] = None
    proximo_cobro: Optional[str] = None


# =====================================================================
# RECURRENTES
# =====================================================================

class RecurrenteCreate(BaseModel):
    """
    `fecha_inicio` es obligatoria y no es un dato administrativo: define la FASE
    del ciclo. La luz bimestral de quien empezo en enero cae en meses nones y la
    de quien empezo en febrero en pares. Sin ella, `frecuencia_meses` diria cada
    cuanto pero no cuando, y todos los bimestrales caerian el mismo mes.
    """
    concepto: str = Field(min_length=1, max_length=120)
    monto: float = Field(gt=0, description="Exacto si es fijo; estimacion inicial si es variable.")
    categoria: str = Field(description="Clave del catalogo (GET /categorias).")
    dia_del_mes: int = Field(ge=1, le=31)
    fecha_inicio: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_fin: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    frecuencia_meses: int = Field(
        default=1, ge=1, le=12,
        description="1 mensual, 2 bimestral, 3 trimestral, 6 semestral, 12 anual.",
    )
    es_variable: bool = Field(
        default=False,
        description=(
            "Para luz, agua o gas. No guarda un rango: el rango real se deriva "
            "del historial. Lo que cambia es el comportamiento — en un variable "
            "la app pregunta de cuanto vino este mes."
        ),
    )
    ajuste_mes_corto: AjusteMesCorto = "ultimo_dia"


class RecurrenteUpdate(BaseModel):
    concepto: Optional[str] = Field(default=None, min_length=1, max_length=120)
    monto: Optional[float] = Field(default=None, gt=0)
    categoria: Optional[str] = None
    dia_del_mes: Optional[int] = Field(default=None, ge=1, le=31)
    fecha_inicio: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_fin: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    frecuencia_meses: Optional[int] = Field(default=None, ge=1, le=12)
    es_variable: Optional[bool] = None
    ajuste_mes_corto: Optional[AjusteMesCorto] = None
    activo: Optional[bool] = None


class RecurrenteResumen(BaseModel):
    id: str
    concepto: str
    monto: float
    categoria: str
    categoria_nombre: str
    dia_del_mes: int
    frecuencia_meses: int
    es_variable: bool
    ajuste_mes_corto: str
    fecha_inicio: str
    fecha_fin: Optional[str] = None
    activo: bool
    # Cuanto pesa al mes: una luz de $900 bimestral pesa $450. Es la cifra
    # correcta para "cuanto se me va en obligaciones" y la INCORRECTA para
    # "me alcanza este mes" — para eso esta GET /pendientes.
    peso_mensual: float


class RecurrenteHistorial(BaseModel):
    """
    El rango REAL de un gasto variable, con datos del usuario y no con su
    suposicion. Sale de los ultimos 6 pagos confirmados.

    `monto_para_proyectar` usa el MAXIMO reciente, no el promedio: en una app
    que previene deuda, equivocarse hacia abajo es el error caro. Decirle a
    alguien que debe $500 cuando debe $1,000 lo mete justo en el problema que la
    app promete evitar.
    """
    recurrente_id: str
    concepto: str
    es_variable: bool
    monto_declarado: float
    pagos_considerados: int
    monto_min: Optional[float] = None
    monto_max: Optional[float] = None
    monto_promedio: Optional[float] = None
    ultimo_pago: Optional[str] = None
    monto_para_proyectar: float


# =====================================================================
# CONFIRMACIONES
# =====================================================================

class ConfirmacionCreate(BaseModel):
    """
    Cuerpo de POST /{recurso}/{id}/confirmaciones.

    `monto` es opcional y ahi esta el matiz: en un recurrente FIJO se da por
    sentado (Netflix son $219 y punto), pero en uno VARIABLE es obligatorio,
    porque el monto de la luz no existe hasta que llega el recibo. Eso no es una
    decision de diseno: es la unica opcion.
    """
    fecha: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    monto: Optional[float] = Field(default=None, gt=0)
    descripcion: Optional[str] = Field(default=None, max_length=255)
    medio: Literal["efectivo", "debito"] = "debito"


class Pendiente(BaseModel):
    """
    Algo que toca y que aun no se ha confirmado. NO es una fila de ninguna
    tabla: se deriva cruzando las declaraciones contra los movimientos que ya
    existen. Materializarlo obligaria a un proceso que lo genere, a decidir que
    pasa con los que nadie confirma y a limpiar los que quedaron con datos
    viejos.
    """
    tipo: Literal["ingreso", "recurrente"]
    origen_id: str
    concepto: str
    fecha_esperada: str
    monto_esperado: float
    # En un variable el monto es una estimacion y la app debe preguntarlo.
    monto_incierto: bool = False
    categoria: Optional[str] = None
    dias_restantes: int


class PendientesResponse(BaseModel):
    ingresos: list[Pendiente]
    gastos: list[Pendiente]
    total_por_cobrar: float
    total_por_pagar: float