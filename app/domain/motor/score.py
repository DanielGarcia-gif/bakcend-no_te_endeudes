"""
Financial Health Score — los cuatro componentes y el total ponderado.

Es la moneda con la que se comparan todas las decisiones del producto.

Portado de contexto/motor.py sin cambios de logica ni de umbrales.
"""

from app.domain.motor.agregados import (
    gasto_mensual_total,
    intereses_mensuales,
    limite_credito_total,
    obligaciones_mensuales,
    saldo_credito_total,
)
from app.domain.motor.proyeccion import proyectar_flujo
from app.domain.motor.umbrales import (
    BANDAS,
    DEUDA_CRITICA,
    DEUDA_OPTIMA,
    FLUJO_OBJETIVO,
    LIQ_MES_1,
    LIQ_MES_MAX,
    PESOS,
    UTIL_CRITICA,
    UTIL_OPTIMA,
    clamp,
)


# =====================================================================
# COMPONENTES DEL SCORE
# =====================================================================

def score_liquidez(disponible: float, gasto_mensual: float) -> float:
    if gasto_mensual <= 0:
        return 100.0
    meses = disponible / gasto_mensual
    if meses <= LIQ_MES_1:
        return clamp(meses / LIQ_MES_1 * 50)
    extra = (meses - LIQ_MES_1) / (LIQ_MES_MAX - LIQ_MES_1)
    return clamp(50 + extra * 50)


def score_deuda(obligaciones: float, ingreso_mensual: float) -> float:
    if ingreso_mensual <= 0:
        return 0.0
    ratio = obligaciones / ingreso_mensual
    return clamp((DEUDA_CRITICA - ratio) / (DEUDA_CRITICA - DEUDA_OPTIMA) * 100)


def score_utilizacion(saldo_total: float, limite_total: float) -> float:
    if limite_total <= 0:
        return 100.0
    ratio = saldo_total / limite_total
    return clamp((UTIL_CRITICA - ratio) / (UTIL_CRITICA - UTIL_OPTIMA) * 100)


def score_flujo(saldo_minimo: float, gasto_mensual: float) -> float:
    if gasto_mensual <= 0:
        return 100.0
    ratio = saldo_minimo / gasto_mensual
    return clamp(ratio / FLUJO_OBJETIVO * 100)


# =====================================================================
# SCORE COMPLETO
# =====================================================================

def calcular_score(estado: dict) -> dict:
    gasto_total = gasto_mensual_total(estado)
    _, saldo_min, dia_min = proyectar_flujo(estado)
    
    # Obtenemos obligaciones e intereses por separado para aplicarles un factor de castigo real
    obligaciones = obligaciones_mensuales(estado)
    intereses = intereses_mensuales(estado)

    comp = {
        "liquidez": score_liquidez(estado["liquidez"], gasto_total),
        # CORRECCIÓN DE SENTIDO COMÚN: Multiplicamos los intereses por un factor de castigo (2.0)
        # para que el crédito revolvente caro no infle artificialmente su score con una mensualidad baja.
        "deuda": score_deuda(
            obligaciones + (intereses * 2.0),
            estado["ingreso"]["mensual"],
        ),
        "utilizacion": score_utilizacion(
            saldo_credito_total(estado), limite_credito_total(estado)
        ),
        "flujo": score_flujo(saldo_min, gasto_total),
    }
    total = sum(comp[k] * PESOS[k] for k in PESOS)

    return {
        "score": round(total),
        "score_exacto": round(total, 1),
        "componentes": {k: round(v) for k, v in comp.items()},
        "saldo_minimo": round(saldo_min, 2),
        "dia_saldo_minimo": dia_min,
        "gasto_mensual_total": round(gasto_total, 2),
    }


def banda(score: int) -> tuple[str, str]:
    """Devuelve (nombre, color) para el score dado."""
    for minimo, nombre, color in BANDAS:
        if score >= minimo:
            return nombre, color
    return "Critico", "rojo"