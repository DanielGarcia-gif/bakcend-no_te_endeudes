"""
CONTRATO DE TIPOS — CONGELADO
==============================

Esta es la forma canonica de los datos que cruzan entre capas.
Se congela en la hora 2 y NO se modifica despues sin avisar a todo el equipo.

Espejo exacto de tipos.ts. Si cambian uno, cambian los dos.

Referencia de valores reales: contexto/estado_mock.json y
contexto/endpoints_ejemplo.json

Portado de contexto/tipos.py. Unico cambio: validar_gasto() se movio a
app/domain/reglas.py, junto al resto de validaciones de negocio. Este modulo
solo declara formas; no valida reglas ni tiene comportamiento.

app/schemas/ REEXPORTA desde aqui en lugar de redefinir estos modelos: una
segunda definicion romperia el espejo con tipos.ts sin que nadie lo note.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field, field_validator


# =====================================================================
# ENUMS
# =====================================================================

Frecuencia = Literal["semanal", "catorcenal", "quincenal", "mensual"]
TipoTarjeta = Literal["credito", "debito"]
# Tres, no dos. Antes efectivo y debito colapsaban en el mismo caso porque
# el medio se infería de `tarjeta_id IS NULL`; ahora `movimientos.medio` es
# una columna y son distinguibles.
MedioPago = Literal["efectivo", "debito", "credito"]
TipoGasto = Literal["recurrente", "espontaneo"]
Modalidad = Literal["contado", "credito", "3_msi", "6_msi", "9_msi",
                    "12_msi", "15_msi", "18_msi"]
PLAZOS_COMUNES = [3, 6, 9, 12, 15, 18]   # opciones del selector del simulador
Componente = Literal["liquidez", "deuda", "utilizacion", "flujo"]
Confianza = Literal["alta", "media", "baja"]
# Lo emite el MOTOR, no el modelo de lenguaje. Gemini lo redacta; la decision
# de si la compra es sana sale de umbrales.py, que es auditable.
Veredicto = Literal["conviene", "conviene_con_cuidado", "no_conviene"]

# CATEGORIAS ya no vive aqui. Era una lista que NADIE validaba: los schemas
# declaraban `categoria: str` libre, asi que cualquier cadena entraba y las
# dos tablas que la usaban ya habian divergido. Ahora es la tabla
# `categorias` y se resuelve por clave contra ella (GET /categorias).

# Unica definicion del proyecto. db.py la tenia duplicada; los repositorios
# la importan de aqui para que las dos copias no puedan divergir.
FACTOR_MENSUAL = {
    "semanal": 52 / 12,      # 4.333 — NO es 4
    "catorcenal": 26 / 12,   # 2.167
    "quincenal": 2.0,
    "mensual": 1.0,
}


# =====================================================================
# EL OBJETO `estado` — lo que consume el motor
# =====================================================================

class MSIVigente(BaseModel):
    monto_mensual: float
    meses_restantes: int
    descripcion: Optional[str] = None


class TarjetaEstado(BaseModel):
    """Tal como la recibe el motor. Las de debito NO entran aqui."""
    id: str
    nombre: str
    limite: float
    saldo: float
    tasa: float                      # fraccion decimal: 38% -> 0.38
    pago_minimo: float
    corte: int = Field(ge=1, le=31)          # dia del mes
    limite_pago: int = Field(ge=1, le=31)    # dia del mes
    monto_minimo_msi: float = 0              # este SI es del banco
    msi: list[MSIVigente] = []

    # OJO: los plazos MSI NO viven aqui. Dependen del COMERCIO, no de la
    # tarjeta: Liverpool da 18 meses con la misma tarjeta con la que la
    # tienda de la esquina no da ninguno. El usuario los captura al simular.

    @computed_field  # type: ignore[prop-decorator]
    @property
    def disponible(self) -> float:
        """
        Derivado. NUNCA se guarda en la base de datos.

        computed_field para que SI salga serializado: estado_mock.json lo trae
        en cada tarjeta y el frontend lo consume. Con un @property pelado,
        Pydantic lo omitia del JSON y la respuesta no cuadraba con el mock.
        """
        return self.limite - self.saldo


class Ingreso(BaseModel):
    mensual: float                   # ya normalizado


class IngresoProgramado(BaseModel):
    dia: int = Field(ge=1, le=31)
    monto: float
    concepto: str


class Gastos(BaseModel):
    fijos: float
    variables_prom: float


class Compromiso(BaseModel):
    dia: int = Field(ge=1, le=31)
    monto: float
    concepto: str


class Estado(BaseModel):
    """
    LA estructura central. armar_estado() la produce, el motor la consume.
    Cambiar esto rompe backend y frontend a la vez.
    """
    liquidez: float
    ingreso: Ingreso
    ingresos_programados: list[IngresoProgramado]
    gastos: Gastos
    compromisos: list[Compromiso]
    tarjetas: list[TarjetaEstado]


# =====================================================================
# SCORE
# =====================================================================

class Flujo30d(BaseModel):
    serie: list[float]               # 30 valores, uno por dia
    minimo: float
    dia_minimo: int


class ScoreResponse(BaseModel):
    score: int                       # 0-100 redondeado
    score_exacto: float              # un decimal, para el micro-momento
    banda: str                       # Saludable | Estable | En riesgo | Critico
    color: str                       # verde | amarillo | naranja | rojo
    componentes: dict[str, int]      # las 4 llaves de Componente
    pesos: dict[str, int]            # 30 / 30 / 20 / 20
    gasto_mensual_total: float
    obligaciones_mensuales: float
    intereses_mensuales: float
    flujo_30d: Flujo30d


# =====================================================================
# SIMULADOR
# =====================================================================

def _solo_plazos_conocidos(plazos: list[int]) -> list[int]:
    """
    422 en vez de 500. `Modalidad` solo tiene 3/6/9/12/15/18, asi que un plazo
    de 24 producia un "24_msi" que reventaba al validar la RESPUESTA: un error
    del servidor causado por un dato del cliente.

    De paso ordena y quita repetidos, para que dos peticiones equivalentes
    produzcan la misma lista.
    """
    invalidos = sorted({p for p in plazos if p not in PLAZOS_COMUNES})
    if invalidos:
        opciones = ", ".join(str(p) for p in PLAZOS_COMUNES)
        raise ValueError(
            f"Plazos no soportados: {invalidos}. Los validos son {opciones}"
        )
    return sorted(set(plazos))


class OpcionTarjeta(BaseModel):
    """
    Una tarjeta puesta sobre la mesa, con los plazos que ofrece la tienda CON
    ESA tarjeta.

    Existe porque el mundo real no es uniforme: la misma tienda da 18 meses con
    una tarjeta, 6 con otra y ninguno con la tercera. Un `plazos` global obligaba
    a fingir que todas reciben la misma oferta.
    """
    tarjeta_id: str
    plazos: list[int] = []           # vacio = con esa tarjeta solo revolvente

    @field_validator("plazos")
    @classmethod
    def _plazos_validos(cls, v: list[int]) -> list[int]:
        return _solo_plazos_conocidos(v)


class SimulacionRequest(BaseModel):
    monto: float = Field(gt=0)
    descripcion: Optional[str] = None
    plazos: list[int] = []           # los que ofrece EL COMERCIO, no la tarjeta
                                     # vacio = solo contado y revolvente
                                     # LEGADO: aplica a TODAS las tarjetas.
    # Cuando viene, MANDA sobre `plazos` y ademas define el universo: solo se
    # evaluan las tarjetas listadas aqui. `plazos` se conserva para que las
    # llamadas viejas sigan valiendo tal cual.
    tarjetas: Optional[list[OpcionTarjeta]] = None
    # El contado se puede sacar de la comparacion: "esto no lo voy a pagar en
    # efectivo aunque pudiera". Con `tarjetas` en None se ignora.
    incluir_contado: bool = True

    @field_validator("plazos")
    @classmethod
    def _plazos_validos(cls, v: list[int]) -> list[int]:
        return _solo_plazos_conocidos(v)


class Escenario(BaseModel):
    """
    Un escenario NO viable trae modalidad/score/delta en null y un motivo.
    El frontend lo pinta deshabilitado CON la razon visible. No lo esconde.
    """
    modalidad: Optional[Modalidad]
    tarjeta: Optional[str]           # null cuando es contado
    tarjeta_id: Optional[str]
    disponible: float                # derivado: limite - saldo
    holgura_despues: Optional[float]  # linea libre despues de la compra
    pago_mensual: float
    viable: bool
    motivo: Optional[str] = None
    score_despues: Optional[int]
    delta: Optional[int]
    # Lo que sale del bolsillo en total. Contado y MSI: el monto pelado. En
    # revolvente: monto + intereses de los 12 meses que amortiza el motor. Sin
    # esta cifra, comparar 18 MSI contra revolver en una frase es imposible.
    costo_total: Optional[float] = None
    # El mejor escenario DENTRO de su tarjeta. Lo marca el motor porque es el
    # que viaja al analisis profundo: una tarjeta compite con su mejor carta,
    # no con las seis.
    mejor_de_tarjeta: bool = False


class MetricasCompra(BaseModel):
    """
    El tamano de la compra medido contra la vida del usuario, no en abstracto.

    Las calcula el MOTOR. Existen para que el veredicto sea auditable y para que
    el analisis profundo tenga cifras que citar sin inventar ninguna: son
    exactamente los numeros que Gemini puede repetir.
    """
    monto_vs_liquidez_pct: float      # 60.0 = la compra se lleva el 60% del efectivo
    monto_vs_ingreso_mensual_pct: float
    colchon_meses_antes: float        # meses de gasto cubiertos por la liquidez
    colchon_meses_despues: float
    utilizacion_antes: float          # PORCENTAJE, como DeudaRanking
    utilizacion_despues: float


class SimulacionResponse(BaseModel):
    monto: float
    plazos_ofrecidos: list[int]      # union de todos los plazos puestos sobre
                                     # la mesa, para que la respuesta se lea sola
    score_actual: int
    recomendado: Optional[Escenario]
    escenarios: list[Escenario]      # viables primero, mejor score arriba,
                                     # desempate por preferencia y holgura
    # El veredicto viaja en la simulacion, NO en el analisis de IA: la
    # advertencia de "esto te deja sin colchon" tiene que aparecer aunque Gemini
    # este caido. La IA solo lo redacta.
    veredicto: Veredicto = "conviene"
    razones_veredicto: list[str] = []
    metricas: Optional[MetricasCompra] = None


# =====================================================================
# DEUDA
# =====================================================================

class DeudaRanking(BaseModel):
    # El id, no solo el nombre: sin el, el frontend tenia que cruzar el
    # ranking contra GET /estado por nombre para saber a que tarjeta pagar,
    # y dos tarjetas del mismo banco rompian ese cruce.
    tarjeta_id: str
    tarjeta: str
    saldo: float
    utilizacion: float               # porcentaje, ej 85.0
    tasa: float
    costo_intereses_mes: float
    prioridad: float
    razones: list[str]               # ya redactadas por el motor


class DeudaResponse(BaseModel):
    ranking: list[DeudaRanking]
    intereses_totales_mes: float


class PagoResponse(BaseModel):
    ok: bool
    score_antes: int
    score_despues: int
    ahorro_intereses_mensual: float  # el beneficio grande, mostrarlo siempre
    nuevo_saldo_tarjeta: float


# =====================================================================
# GASTOS
# =====================================================================

class GastoRequest(BaseModel):
    tipo: TipoGasto
    monto: float = Field(gt=0)
    categoria: str
    fecha: str                       # YYYY-MM-DD
    medio: MedioPago
    tarjeta_id: Optional[str] = None
    dia_del_mes: Optional[int] = None   # solo para recurrentes


class GastoResponse(BaseModel):
    """
    El micro-momento muestra el COMPONENTE, no el score global:
    un gasto chico mueve menos de un punto entero.
    """
    id: int
    score_antes: float
    score_despues: float
    componente_afectado: Componente
    componente_antes: int
    componente_despues: int


# =====================================================================
# TARJETAS
# =====================================================================

# Aqui vivia `ExtraccionResponse`: la forma CRUDA de lo que contestaba Gemini,
# que producia el frontend y que ningun endpoint devolvia. Se borro cuando la
# llamada a Gemini se mudo al backend. Ahora hay dos formas y ninguna es esta:
#
#   - el esquema crudo que se le PIDE al modelo vive en el prompt, en
#     app/domain/extraccion.py
#   - la respuesta ya normalizada que devuelve la API es
#     app/schemas/ia.ExtraccionResponse
#
# Mantener aqui una tercera con el mismo nombre solo servia para que alguien
# importara la equivocada.


class MSIExtraido(BaseModel):
    descripcion: str
    monto_mensual: float
    meses_restantes: int

class TerminosRequest(BaseModel):
    limite: float = Field(gt=0)
    saldo: float = Field(ge=0)
    tasa_anual: float = Field(ge=0, le=2)
    pago_minimo: float = Field(ge=0)
    dia_corte: int = Field(ge=1, le=31)
    dia_limite_pago: int = Field(ge=1, le=31)
    monto_minimo_msi: float = 0
    msi_vigentes: list[MSIExtraido] = []