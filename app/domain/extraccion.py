"""
Lo que se hace con lo que Gemini leyo de un estado de cuenta.

Puro: se declara el esquema que se le exige al modelo, entra el dict crudo
que contesto y sale el mapeo listo para el formulario.
Sin base de datos, sin red, sin FastAPI - como sus vecinos `reglas.py` y
`calendario.py`, y por eso se prueba solo con `pytest tests/test_extraccion.py`.

Este archivo es un puerto de `aTerminos()`, que vivia en el frontend. Se mudo
porque son reglas financieras, no presentacion: decidir que el saldo se deriva
del credito disponible impreso, o que una tasa de "38" en realidad es 0.38, es
del mismo tipo de decision que toma el motor.

DOS COSAS QUE ESTE MODULO NO HACE, A PROPOSITO:

  1. No inventa. Si el documento no imprime un dato, el campo no viaja y el
     formulario lo deja en blanco para que lo escriba la persona.
  2. No persiste. Esto prellena un formulario; nada se guarda hasta que el
     usuario confirma.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Confianza = Literal["alta", "media", "baja"]
ModoPago = Literal["minimo", "total"]


# =====================================================================
# LO QUE SE LE EXIGE AL MODELO
# =====================================================================
# Esto NO es lo que devuelve la API - eso es `schemas/ia.ExtraccionResponse`.
# Esto es la forma cruda que se le pide a Gemini, y viaja como `response_schema`
# en la llamada.
#
# Antes el esquema estaba escrito como texto dentro del prompt ("Esquema
# exacto: {...}") y era una PROMESA: el modelo podia contestar otra cosa y solo
# se descubria al parsear. Ahora es una GARANTIA del servicio, y con eso se
# fueron las vallas de ```json, los campos con nombres inventados y el
# "Gemini no devolvio JSON valido".

# OJO al escribir aqui: los docstrings de estas clases y las `description` de sus
# campos VIAJAN a Gemini dentro del esquema. Sirven para decirle al modelo que
# significa un campo; las notas para quien mantiene el codigo van en comentarios
# como este, que el SDK no manda.

# Los tres campos van opcionales, al reves que el resto del esquema: con
# `response_schema` un campo requerido OBLIGA al modelo a inventarlo cuando el
# documento no lo trae, que es justo lo que este archivo promete no hacer.
# `mapear()` descarta los planes a los que les falte algo.
class MSILeidoIA(BaseModel):

    descripcion: Optional[str] = None
    monto_mensual: Optional[float] = None
    meses_restantes: Optional[int] = None


# El estado de cuenta leido, antes de que `mapear()` lo sanee.
class EstadoDeCuentaIA(BaseModel):

    banco: Optional[str] = None
    limite_credito: Optional[float] = None
    saldo_al_corte: Optional[float] = None
    limite_disponible: Optional[float] = None
    pago_minimo: Optional[float] = None
    pago_no_intereses: Optional[float] = None
    fecha_corte: Optional[int] = Field(None, description="Dia del mes (1-31)")
    fecha_limite_pago: Optional[int] = Field(None, description="Dia del mes (1-31)")
    tasa_anual: Optional[float] = Field(
        None, description="Fraccion decimal: 38% -> 0.38"
    )
    cat: Optional[float] = None
    msi: list[MSILeidoIA] = []
    confianza: Confianza


# El prompt ya no describe la FORMA (de eso se encarga el esquema de arriba):
# solo la SEMANTICA. Que significa fecha_corte, cuando devolver null, que cuenta
# como MSI vigente. Esas reglas vienen palabra por palabra de
# contexto/test_gemini.py, donde se probaron: cambiarlas cambia lo que extrae.
PROMPT_EXTRACCION = """Eres un extractor de datos de estados de cuenta bancarios mexicanos.
Extrae unicamente los campos del esquema, siguiendo rigurosamente estas reglas:

- Si un campo no aparece explicitamente en el documento, devuelvelo como null.
- Nunca calcules ni infieras un valor que no este impreso.
- fecha_corte y fecha_limite_pago son el DIA DEL MES, como numero entero (1-31).
- Las tasas van como fraccion decimal: 38% -> 0.38
- En "msi" incluye solo las compras a meses sin intereses todavia vigentes.
- "confianza" refleja que tan legible fue el documento: alta, media o baja."""


# =====================================================================
# SANEADO DE LO QUE CONTESTO EL MODELO
# =====================================================================
# `response_schema` garantiza la FORMA, no el SENTIDO: un 38 donde se pidio
# 0.38 es un float perfectamente valido, y un dia 32 es un int perfectamente
# valido. Todo lo que entra sigue pasando por aqui antes de que alguna regla
# lo use.

def _numero(v) -> Optional[float]:
    """Un numero de verdad, o None. Los bool no cuentan: True no es 1 aqui."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN e infinitos
        return None
    return float(v)


def _positivo(v) -> Optional[float]:
    n = _numero(v)
    return n if n is not None and n > 0 else None


def _no_negativo(v) -> Optional[float]:
    n = _numero(v)
    return n if n is not None and n >= 0 else None


def _dia(v) -> Optional[int]:
    """Dia del mes: entero de 1 a 31, o nada."""
    n = _numero(v)
    if n is None or n != int(n):
        return None
    return int(n) if 1 <= n <= 31 else None


def _entero_positivo(v) -> Optional[int]:
    """Meses restantes de un plan: entero mayor que cero."""
    n = _numero(v)
    if n is None or n != int(n) or n <= 0:
        return None
    return int(n)


def _r2(n: float) -> float:
    return round(n, 2)


def _pesos(n: float) -> str:
    """$1,250 si es entero, $1,250.50 si no. Espejo de `mxn()` del frontend."""
    if n == int(n):
        return f"${int(n):,}"
    return f"${n:,.2f}"


# =====================================================================
# EL MAPEO
# =====================================================================

def mapear(crudo: dict, banco_tarjeta: Optional[str] = None,
           modo: ModoPago = "minimo") -> dict:
    """
    Convierte la extraccion cruda en lo que necesita el formulario de terminos.

    `banco_tarjeta` es el banco con el que la tarjeta esta dada de alta: sirve
    para avisar cuando el PDF resulta ser de otra. `modo` dice como paga la
    persona esa tarjeta y decide cual de los dos pagos impresos se prellena.

    Devuelve un dict con la forma de `ExtraccionResponse`.
    """
    avisos: list[str] = []
    valores: dict = {}

    limite = _positivo(crudo.get("limite_credito"))
    saldo_corte = _no_negativo(crudo.get("saldo_al_corte"))
    disponible = _no_negativo(crudo.get("limite_disponible"))

    # --- tasa ---
    # El prompt pide fraccion, pero el documento imprime "38.00%" y el modelo a
    # veces copia el 38. Arriba de 1.5 no puede ser fraccion: seria 150% anual.
    tasa = _numero(crudo.get("tasa_anual"))
    if tasa is not None and tasa > 1.5:
        tasa = tasa / 100
    if tasa is not None and (tasa <= 0 or tasa > 2):
        tasa = None
        avisos.append("La tasa leida no era creible, capturala a mano")

    # --- fechas ---
    corte = _dia(crudo.get("fecha_corte"))
    limite_pago = _dia(crudo.get("fecha_limite_pago"))

    # El backend rechaza que sean el mismo dia. Si salieron iguales, uno de los
    # dos esta mal y no hay forma de saber cual: se vacian los dos.
    if corte is not None and corte == limite_pago:
        corte = limite_pago = None
        avisos.append("La fecha de corte y la de pago salieron iguales, revisalas")

    # --- saldo ---
    # Sale del credito disponible impreso, NO del saldo al corte. La app calcula
    # disponible = limite - saldo, asi que esta es la unica forma de que lo que
    # ve la persona cuadre con su estado de cuenta: el disponible impreso ya
    # trae los cargos posteriores al corte y el capital de los MSI que debe.
    saldo: Optional[float] = None

    if disponible is not None and limite is not None and disponible > limite:
        avisos.append("El credito disponible salio mayor que el limite, revisa los dos")
        disponible = None

    if limite is not None and disponible is not None:
        saldo = _r2(limite - disponible)
        if saldo_corte is not None and abs(saldo - saldo_corte) >= 1:
            avisos.append(
                f"Tu saldo al corte era {_pesos(saldo_corte)}, pero contra tu "
                f"credito disponible debes {_pesos(saldo)}. Se usa este ultimo, "
                "que es el que cuadra con tu estado de cuenta"
            )
    elif saldo_corte is not None:
        saldo = saldo_corte
        if limite is not None:
            disponible = _r2(limite - saldo_corte)
            avisos.append(
                "Tu estado de cuenta no traia el credito disponible: sale de "
                "restarle el saldo al limite y puede no cuadrar con el impreso"
            )

    if limite is not None:
        valores["limite"] = limite
    if saldo is not None:
        valores["saldo"] = saldo
    if tasa is not None:
        valores["tasa_anual"] = tasa
    if corte is not None:
        valores["dia_corte"] = corte
    if limite_pago is not None:
        valores["dia_limite_pago"] = limite_pago

    # --- los dos pagos ---
    # El estado de cuenta imprime el pago minimo y el "pago para no generar
    # intereses". Son numeros distintos y la tarjeta guarda uno solo: cual,
    # depende de como pague la persona. Viajan los dos para que cambiar de modo
    # en el formulario no tenga que pedir otra lectura del PDF.
    pagos = {
        "minimo": _positivo(crudo.get("pago_minimo")),
        "sin_intereses": _positivo(crudo.get("pago_no_intereses")),
    }
    if modo == "total":
        pago = pagos["sin_intereses"] if pagos["sin_intereses"] is not None else pagos["minimo"]
    else:
        pago = pagos["minimo"] if pagos["minimo"] is not None else pagos["sin_intereses"]
    if pago is not None:
        valores["pago_minimo"] = pago

    # --- planes a meses ---
    # Lo que el PDF SI trae. No es un MSICreate: falta `meses_totales` y
    # `fecha_inicio`, que el estado de cuenta no imprime nunca. Inventarlos
    # seria peor que pedirlos, porque `meses_restantes` se DERIVA de la fecha de
    # inicio y una fecha inventada mueve la deuda.
    planes = []
    for m in crudo.get("msi") or []:
        if not isinstance(m, dict):
            continue
        mensual = _positivo(m.get("monto_mensual"))
        restantes = _entero_positivo(m.get("meses_restantes"))
        if mensual is None or restantes is None:
            continue
        descripcion = m.get("descripcion")
        planes.append({
            "descripcion": descripcion if isinstance(descripcion, str) else None,
            "monto_mensual": mensual,
            "meses_restantes": restantes,
        })

    if planes:
        avisos.append(
            "Falta decir a cuantos meses fue cada compra: el estado de cuenta "
            "no lo imprime"
        )

    # Este dato no viene impreso NUNCA. Siempre es manual.
    avisos.append("El monto minimo para MSI no viene en el estado de cuenta, capturalo tu")

    confianza = crudo.get("confianza")
    if confianza not in ("alta", "media", "baja"):
        confianza = "baja"
    if confianza == "baja":
        avisos.append(
            "El documento se leyo con dificultad. Revisa campo por campo antes de guardar"
        )

    banco = crudo.get("banco")
    banco = banco.strip() if isinstance(banco, str) and banco.strip() else None
    if banco and banco_tarjeta and banco.lower() != banco_tarjeta.lower():
        # Va al principio: si el PDF es de otra tarjeta, lo demas sobra.
        avisos.insert(
            0,
            f"El PDF dice que es de {banco}, tu tarjeta esta registrada como {banco_tarjeta}",
        )

    # Nombres de los CAMPOS DEL FORMULARIO, no los del contrato: alli la tasa se
    # captura en porcentaje y el saldo no se captura, se deriva del disponible.
    campos_ia: list[str] = []
    if limite is not None:
        campos_ia.append("limite")
    if disponible is not None:
        campos_ia.append("disponible")
    if tasa is not None:
        campos_ia.append("tasa_pct")
    if pago is not None:
        campos_ia.append("pago")
    if corte is not None:
        campos_ia.append("dia_corte")
    if limite_pago is not None:
        campos_ia.append("dia_limite_pago")

    return {
        "valores": valores,
        "banco": banco,
        "campos_ia": campos_ia,
        "avisos": avisos,
        "confianza": confianza,
        "pagos": pagos,
        "disponible": disponible,
        "planes": planes,
    }