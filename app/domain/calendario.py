"""
Cuando toca cada cosa.

Funciones puras de fechas: no tocan la base, no conocen FastAPI y no guardan
nada. Son la mitad derivada del patron central del modelo:

    declaracion  ->  el usuario confirma  ->  movimiento

Lo "esperado" no existe como fila en ninguna tabla. Se calcula aqui, al vuelo,
cada vez que alguien pregunta que le falta confirmar. Materializar pendientes
obligaria a un proceso que los genere, a decidir que pasa con los que nadie
confirma, y a limpiar los que se generaron con datos que despues cambiaron.

DOS FAMILIAS DE FRECUENCIA DE INGRESO, y no se pueden mezclar:

  Basada en dias      semanal (7), catorcenal (14). Se define por `fecha_ancla`
                      y se avanza sumando dias. NO es expresable como dia del
                      mes: catorcenal son 26 pagos al ano, y en un mes de 30
                      dias a veces caen dos y a veces tres.

  Basada en calendario  quincenal, mensual. Se define por `dia_pago` (mas
                      `dia_pago_2` en quincenal). Quincenal en Mexico NO es
                      "cada 15 dias": son dos veces al mes, normalmente el 15 y
                      el ultimo. Calcularlo como ancla + 15n acumula ~5 dias de
                      error al ano.

EL ANCLA SE RESINCRONIZA. Para las frecuencias por dias, el ciclo no se cuenta
desde la fecha_ancla original para siempre, sino desde
COALESCE(ultimo movimiento confirmado, fecha_ancla). Asi cada confirmacion del
usuario vuelve a alinear el calendario con la realidad del banco, en vez de
acumular deriva contra una fecha que se capturo una vez.

LIMITACION CONOCIDA Y DELIBERADA: no se ajusta por dias inhabiles. En Mexico la
nomina se recorre (si el 15 cae domingo pagan el viernes 13), pero hacerlo bien
exige mantener el calendario oficial de dias festivos, que cambia cada ano.
Mueve la proyeccion uno o dos dias y no vale ese costo de mantenimiento.
"""

from calendar import monthrange
from datetime import date, timedelta

# Cuantos dias avanza cada ciclo de las frecuencias basadas en dias.
DIAS_POR_CICLO = {"semanal": 7, "catorcenal": 14}

# Tope de seguridad: ninguna ventana razonable produce mas ocurrencias, y evita
# que un rango absurdo o un dato corrupto genere un bucle infinito.
MAXIMO_OCURRENCIAS = 400


def dia_efectivo(anio: int, mes: int, dia: int,
                 ajuste: str = "ultimo_dia") -> date:
    """
    Resuelve un "dia del mes" a una fecha real.

    El 31 no existe en abril y el 30 no existe en febrero. Que hacer entonces
    es una decision de negocio, no un detalle: `ajuste_mes_corto` la guarda.

        ultimo_dia      -> 30 de abril, 28 de febrero (lo normal en nomina)
        mes_siguiente   -> 1 de mayo, 1 de marzo (algunos domiciliados)
    """
    ultimo = monthrange(anio, mes)[1]
    if dia <= ultimo:
        return date(anio, mes, dia)
    if ajuste == "mes_siguiente":
        return date(anio, mes, ultimo) + timedelta(days=1)
    return date(anio, mes, ultimo)


def sumar_meses(base: date, meses: int) -> tuple[int, int]:
    """Devuelve (anio, mes) desplazado. No resuelve el dia: eso es dia_efectivo."""
    total = (base.year * 12 + base.month - 1) + meses
    return total // 12, total % 12 + 1


def meses_entre(desde: date, hasta: date) -> int:
    """Meses calendario completos transcurridos. Espejo de TIMESTAMPDIFF(MONTH)."""
    meses = (hasta.year - desde.year) * 12 + (hasta.month - desde.month)
    if hasta.day < desde.day:
        meses -= 1
    return meses


# =====================================================================
# INGRESOS
# =====================================================================

def ocurrencias_ingreso(
    frecuencia: str,
    desde: date,
    hasta: date,
    dia_pago: int | None = None,
    dia_pago_2: int | None = None,
    fecha_ancla: date | None = None,
    ultimo_confirmado: date | None = None,
    ajuste: str = "ultimo_dia",
) -> list[date]:
    """
    Fechas en que ese ingreso cae dentro de [desde, hasta].

    `ultimo_confirmado` reancla las frecuencias por dias: es lo que hace que
    confirmar un pago corrija el calendario en vez de dejarlo derivar.
    """
    if hasta < desde:
        return []

    if frecuencia in DIAS_POR_CICLO:
        return _ocurrencias_por_dias(
            paso=DIAS_POR_CICLO[frecuencia],
            ancla=ultimo_confirmado or fecha_ancla,
            desde=desde,
            hasta=hasta,
        )
    return _ocurrencias_por_calendario(
        dias=[d for d in (dia_pago, dia_pago_2) if d],
        desde=desde,
        hasta=hasta,
        ajuste=ajuste,
    )


def _ocurrencias_por_dias(paso: int, ancla: date | None,
                          desde: date, hasta: date) -> list[date]:
    if ancla is None:
        # ck_ingresos_ancla lo impide en la base; aqui se degrada a "no se
        # sabe cuando toca" en vez de inventar una fecha.
        return []

    # Saltar de golpe hasta la ventana en vez de iterar dia por dia desde una
    # fecha ancla que puede ser de hace anos.
    if ancla < desde:
        ciclos = (desde - ancla).days // paso
        actual = ancla + timedelta(days=ciclos * paso)
        while actual < desde:
            actual += timedelta(days=paso)
    else:
        actual = ancla

    salida: list[date] = []
    while actual <= hasta and len(salida) < MAXIMO_OCURRENCIAS:
        salida.append(actual)
        actual += timedelta(days=paso)
    return salida


def _ocurrencias_por_calendario(dias: list[int], desde: date, hasta: date,
                                ajuste: str) -> list[date]:
    if not dias:
        return []
    salida: list[date] = []
    anio, mes = desde.year, desde.month
    while len(salida) < MAXIMO_OCURRENCIAS:
        if date(anio, mes, 1) > hasta:
            break
        for d in dias:
            f = dia_efectivo(anio, mes, d, ajuste)
            if desde <= f <= hasta:
                salida.append(f)
        anio, mes = sumar_meses(date(anio, mes, 1), 1)
    return sorted(salida)


def proximo_cobro(
    frecuencia: str,
    referencia: date,
    dia_pago: int | None = None,
    dia_pago_2: int | None = None,
    fecha_ancla: date | None = None,
    ultimo_confirmado: date | None = None,
    ajuste: str = "ultimo_dia",
) -> date | None:
    """
    La siguiente fecha de cobro a partir de `referencia`, inclusive.

    Derivado, nunca persistido: por eso `ingresos` no tiene una columna
    `proximo_pago` que alguien tendria que mantener al dia.
    """
    ocurrencias = ocurrencias_ingreso(
        frecuencia, referencia, referencia + timedelta(days=70),
        dia_pago, dia_pago_2, fecha_ancla, ultimo_confirmado, ajuste,
    )
    return ocurrencias[0] if ocurrencias else None


# =====================================================================
# GASTOS RECURRENTES
# =====================================================================

def cae_en_el_mes(fecha_inicio: date, frecuencia_meses: int,
                  referencia: date) -> bool:
    """
    Si un recurrente toca en el mes de `referencia`.

    La FASE sale de fecha_inicio: la luz bimestral de alguien que empezo en
    enero cae en meses nones, y la de quien empezo en febrero, en pares. Sin
    esto, `frecuencia_meses` diria cada cuanto pero no cuando, y todos los
    bimestrales caerian el mismo mes.

    Espejo de la condicion de v_recurrentes_del_mes:
        MOD(TIMESTAMPDIFF(MONTH, fecha_inicio, CURDATE()), frecuencia_meses) = 0

    Se comparan meses calendario, no dias: un recurrente que empieza el 20 de
    enero cae en enero, aunque `referencia` sea el 5.
    """
    if frecuencia_meses < 1:
        return False
    transcurridos = ((referencia.year - fecha_inicio.year) * 12
                     + (referencia.month - fecha_inicio.month))
    if transcurridos < 0:
        return False
    return transcurridos % frecuencia_meses == 0


def ocurrencias_recurrente(
    dia_del_mes: int,
    fecha_inicio: date,
    frecuencia_meses: int,
    desde: date,
    hasta: date,
    fecha_fin: date | None = None,
    ajuste: str = "ultimo_dia",
) -> list[date]:
    """Fechas en que ese gasto fijo cae dentro de [desde, hasta]."""
    if hasta < desde or frecuencia_meses < 1:
        return []

    salida: list[date] = []
    anio, mes = desde.year, desde.month
    while len(salida) < MAXIMO_OCURRENCIAS:
        primero = date(anio, mes, 1)
        if primero > hasta:
            break
        if cae_en_el_mes(fecha_inicio, frecuencia_meses, primero):
            f = dia_efectivo(anio, mes, dia_del_mes, ajuste)
            dentro_de_vigencia = f >= fecha_inicio and (fecha_fin is None or f <= fecha_fin)
            if desde <= f <= hasta and dentro_de_vigencia:
                salida.append(f)
        anio, mes = sumar_meses(primero, 1)
    return salida