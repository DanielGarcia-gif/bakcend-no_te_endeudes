"""
Veredicto de compra — "esto que quieres comprar, ¿te hace dano?".

LO EMITE EL MOTOR, NO LA IA. Es la pieza que hace posible el analisis profundo
sin romper la regla de la casa: Gemini redacta y categoriza, pero la decision de
si la compra es sana sale de aqui, con los mismos umbrales que ya sostienen el
score. Se puede auditar linea por linea y se puede defender ante un jurado.

Consecuencia practica: si Gemini responde 503, la pantalla sigue advirtiendo
"esto te deja sin colchon". Solo se pierde la prosa.

`simular_compra` responde CON QUE conviene pagar. Esto responde algo distinto y
anterior: si conviene comprarlo.
"""

from app.domain.motor.agregados import (
    gasto_mensual_total,
    intereses_mensuales,
    limite_credito_total,
    obligaciones_mensuales,
    saldo_credito_total,
)
from app.domain.motor.evaluacion import evaluar
from app.domain.motor.umbrales import (
    DEUDA_CRITICA,
    LIQ_MES_1,
    UTIL_CRITICA,
    UTIL_OPTIMA,
)

# Umbrales propios del veredicto. Van aqui y no en umbrales.py porque no tocan
# el score: mover uno cambia cuando se advierte, nunca cuanto se puntua.
COLCHON_CRITICO = 0.5        # menos de medio mes de gastos cubiertos
CAIDA_GRAVE = 15             # puntos de score que se pierden con la compra
CAIDA_NOTABLE = 5
PESO_INGRESO_ALTO = 50.0     # la compra vale medio sueldo mensual o mas


def _ratio(numerador: float, denominador: float) -> float:
    """Division que no revienta con el usuario recien registrado (todo en 0)."""
    return numerador / denominador if denominador > 0 else 0.0


def _carga_de_deuda(estado: dict) -> float:
    """
    Que parte del ingreso se van los pagos fijos de credito.

    Misma formula que usa score_deuda: obligaciones MAS intereses devengados.
    Si aqui se calculara distinto, el veredicto podria advertir de algo que el
    score no ve, o al reves.
    """
    return _ratio(
        obligaciones_mensuales(estado) + intereses_mensuales(estado),
        estado["ingreso"]["mensual"],
    )


def _accion_de(escenario: dict, monto: float) -> dict:
    if escenario["modalidad"] == "contado":
        return {"tipo": "compra", "monto": monto, "modalidad": "contado"}
    return {
        "tipo": "compra", "monto": monto,
        "tarjeta_id": escenario["tarjeta_id"],
        "modalidad": escenario["modalidad"],
    }


def _metricas(estado: dict, despues: dict, monto: float) -> dict:
    """
    El tamano de la compra medido contra la vida del usuario.

    Son exactamente las cifras que el analisis profundo puede citar. Que existan
    aqui, calculadas, es lo que le quita a Gemini cualquier excusa para estimar.
    """
    gasto_antes = gasto_mensual_total(estado)
    gasto_despues = gasto_mensual_total(despues)

    return {
        "monto_vs_liquidez_pct": round(_ratio(monto, estado["liquidez"]) * 100, 1),
        "monto_vs_ingreso_mensual_pct": round(
            _ratio(monto, estado["ingreso"]["mensual"]) * 100, 1
        ),
        "colchon_meses_antes": round(_ratio(estado["liquidez"], gasto_antes), 2),
        "colchon_meses_despues": round(_ratio(despues["liquidez"], gasto_despues), 2),
        "utilizacion_antes": round(
            _ratio(saldo_credito_total(estado), limite_credito_total(estado)) * 100, 1
        ),
        "utilizacion_despues": round(
            _ratio(saldo_credito_total(despues), limite_credito_total(despues)) * 100, 1
        ),
    }


def evaluar_compra(estado: dict, monto: float,
                   recomendado: dict | None) -> dict:
    """
    Devuelve `{veredicto, razones, metricas}` para la mejor forma de pagar.

    Se juzga la RECOMENDADA porque es la que el usuario va a tomar: decir "no
    conviene" mirando la peor opcion de la lista seria hacer trampa al reves.

    Las razones se redactan aqui, con aritmetica, igual que en priorizacion.py.
    """
    if recomendado is None:
        return {
            "veredicto": "no_conviene",
            "razones": ["ninguna forma de pago te alcanza hoy"],
            "metricas": None,
        }

    resultado = evaluar(estado, _accion_de(recomendado, monto))
    despues = resultado["estado_resultante"]
    metricas = _metricas(estado, despues, monto)

    caida = resultado["score_antes"] - resultado["score_despues"]
    carga_antes = _carga_de_deuda(estado)
    carga_despues = _carga_de_deuda(despues)

    # TODAS las reglas de nivel exigen ademas que la compra EMPEORE ese nivel.
    # Sin esa condicion, comprar algo de $300 en efectivo avisaba "tu credito
    # subiria al 34% de uso" — un 34% que ya estaba ahi antes y que el efectivo
    # no toca. El veredicto juzga lo que hace la compra; la situacion de partida
    # ya la cuentan el score y la pantalla de deuda.
    baja_colchon = metricas["colchon_meses_despues"] < metricas["colchon_meses_antes"]
    sube_uso = metricas["utilizacion_despues"] > metricas["utilizacion_antes"]

    graves: list[str] = []
    avisos: list[str] = []

    if baja_colchon and metricas["colchon_meses_despues"] < COLCHON_CRITICO:
        graves.append(
            f"te quedarias con {metricas['colchon_meses_despues']:.1f} meses de "
            f"gastos cubiertos: menos de dos semanas de colchon"
        )
    elif baja_colchon and metricas["colchon_meses_despues"] < LIQ_MES_1:
        avisos.append(
            f"tu colchon baja a {metricas['colchon_meses_despues']:.1f} meses de "
            f"gastos, por debajo del mes que se recomienda"
        )

    if sube_uso and metricas["utilizacion_despues"] >= UTIL_CRITICA * 100:
        graves.append(
            f"tu credito quedaria usado al {metricas['utilizacion_despues']:.0f}%, "
            f"que es donde mas castiga tu score"
        )
    elif sube_uso and metricas["utilizacion_despues"] >= UTIL_OPTIMA * 100:
        avisos.append(
            f"tu credito subiria del {metricas['utilizacion_antes']:.0f}% al "
            f"{metricas['utilizacion_despues']:.0f}% de uso"
        )

    if carga_despues > carga_antes and carga_despues >= DEUDA_CRITICA:
        graves.append(
            f"tus pagos fijos se comerian el {carga_despues*100:.0f}% de tu ingreso"
        )

    if caida >= CAIDA_GRAVE:
        graves.append(f"tu score caeria {caida} puntos")
    elif caida >= CAIDA_NOTABLE:
        avisos.append(f"tu score bajaria {caida} puntos")

    if metricas["monto_vs_ingreso_mensual_pct"] >= PESO_INGRESO_ALTO:
        avisos.append(
            f"la compra vale el {metricas['monto_vs_ingreso_mensual_pct']:.0f}% "
            f"de lo que ganas en un mes"
        )

    if graves:
        veredicto = "no_conviene"
        razones = graves + avisos
    elif avisos:
        veredicto = "conviene_con_cuidado"
        razones = avisos
    else:
        veredicto = "conviene"
        razones = []

    return {"veredicto": veredicto, "razones": razones, "metricas": metricas}