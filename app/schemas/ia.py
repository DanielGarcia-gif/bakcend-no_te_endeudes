"""
DTOs de los dos endpoints que hablan con Gemini.

Nada de esto se persiste. La extraccion PRELLENA un formulario que la persona
revisa y confirma, y la explicacion es texto sobre un ranking que el motor ya
calculo. Por eso no hay `id`, ni `version`, ni Create/Update: no son recursos.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.domain.tipos import Veredicto

Confianza = Literal["alta", "media", "baja"]
ModoPago = Literal["minimo", "total"]

__all__ = [
    "Confianza",
    "ModoPago",
    "PlanLeido",
    "PagosLeidos",
    "ExtraccionResponse",
    "ExplicacionDeudaResponse",
    "AnalisisCompraIA",
    "AnalisisCompraResponse",
]


# =====================================================================
# EXTRACCION DE ESTADO DE CUENTA
# =====================================================================

class PlanLeido(BaseModel):
    """
    Un plan a meses tal como lo imprime el estado de cuenta.

    NO es un MSICreate: le faltan `meses_totales` y `fecha_inicio`, que el
    documento no imprime nunca. Inventarlos seria peor que pedirlos - en el
    backend `meses_restantes` se DERIVA de `fecha_inicio`, asi que una fecha
    inventada mueve la deuda. El formulario los deja para el usuario.
    """

    descripcion: Optional[str] = None
    monto_mensual: float
    meses_restantes: int


class PagosLeidos(BaseModel):
    """
    Los dos pagos que imprime el estado de cuenta.

    Viajan los dos aunque la tarjeta solo guarde uno: cual se usa depende de
    como pague la persona, y mandarlos juntos deja que el formulario cambie de
    modo sin volver a leer el PDF.
    """

    minimo: Optional[float] = None
    sin_intereses: Optional[float] = None


class ExtraccionResponse(BaseModel):
    """
    Lo que Gemini leyo, ya normalizado y listo para pintar el formulario.

    `valores` trae los campos del CONTRATO (tasa en fraccion, saldo derivado);
    `campos_ia` trae los nombres de los campos del FORMULARIO, que no son los
    mismos: alli la tasa se captura en porcentaje y el saldo no se captura, se
    deriva del credito disponible.
    """

    valores: dict = Field(
        default_factory=dict,
        description="Campos del contrato que si venian en el documento. Los que "
                    "no aparecieron no vienen: el formulario los deja en blanco.",
    )
    banco: Optional[str] = None
    campos_ia: list[str] = Field(
        default_factory=list,
        description="Nombres de campos del formulario que salieron del PDF, para "
                    "resaltarlos.",
    )
    avisos: list[str] = Field(
        default_factory=list,
        description="Texto ya redactado para mostrar arriba del formulario.",
    )
    confianza: Confianza
    pagos: PagosLeidos
    disponible: Optional[float] = Field(
        default=None,
        description="Credito disponible impreso. De aqui sale el saldo, no al reves.",
    )
    planes: list[PlanLeido] = Field(default_factory=list)


# =====================================================================
# EXPLICACION DE LA PRIORIDAD DE DEUDA
# =====================================================================

class ExplicacionDeudaResponse(BaseModel):
    """
    El ranking de GET /deuda/prioridad, contado en espanol llano.

    Gemini redacta; no calcula. Cada cifra que aparece aqui salio del motor.
    """

    titular: str
    explicacion: str
    siguiente_paso: str
    comparativa: Optional[str] = None
    confianza: Confianza


# =====================================================================
# ANALISIS PROFUNDO DE UNA COMPRA
# =====================================================================

class AnalisisCompraIA(BaseModel):
    """
    SOLO lo que redacta el modelo. Este es el `response_schema` que se le exige.

    En la extraccion y en la explicacion de deuda, el esquema que se le pide a
    Gemini es el mismo DTO que devuelve el endpoint, porque son 1:1. Aqui no:
    la respuesta lleva ademas el veredicto y sus razones, que salen del motor.
    Pedirselos al modelo seria dejarle decidir si la compra es sana — justo lo
    que este diseno evita.
    """

    titular: str = Field(description="Una linea, maximo 70 caracteres.")
    explicacion: str = Field(
        description="2 o 3 oraciones: por que la forma de pago recomendada le "
                    "gana a las demas."
    )
    comparativas: list[str] = Field(
        default_factory=list,
        description="De 2 a 4 contrastes, uno por oracion, contra las otras "
                    "opciones de la mesa.",
    )
    categoria: str = Field(
        description="La clave del catalogo que mejor describe lo que se compra. "
                    "Solo una de las claves entregadas."
    )
    reflexion: Optional[str] = Field(
        default=None,
        description="Pregunta que invita a pensar si de verdad hace falta. Solo "
                    "cuando el veredicto no es 'conviene'; si no, null.",
    )
    riesgos: list[str] = Field(
        default_factory=list,
        description="Lo que puede salir mal, en las palabras de la persona.",
    )
    confianza: Confianza


class AnalisisCompraResponse(BaseModel):
    """
    Lo que devuelve POST /simulaciones/analisis.

    Mezcla deliberada de dos fuentes, y el orden importa: el `veredicto` y sus
    `razones` son del MOTOR —auditables, reproducibles, defendibles— y el resto
    es prosa de Gemini construida sobre ellos. La IA nunca decide si la compra
    conviene; la cuenta.
    """

    titular: str
    explicacion: str
    comparativas: list[str] = Field(default_factory=list)
    reflexion: Optional[str] = None
    riesgos: list[str] = Field(default_factory=list)
    confianza: Confianza

    # Del motor, no del modelo.
    veredicto: Veredicto
    razones_veredicto: list[str] = Field(default_factory=list)

    # La categoria la elige el modelo de entre las claves del catalogo; el
    # nombre lo resuelve el backend. Viaja porque es lo que prellena el
    # formulario cuando la persona decide registrar la compra.
    categoria: str
    categoria_nombre: str