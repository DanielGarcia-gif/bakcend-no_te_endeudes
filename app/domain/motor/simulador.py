"""
Simulador de compra — la pantalla estrella.

SOLO LECTURA. No escribe nada, ni aqui ni en las capas de arriba: evaluar()
trabaja sobre copias del estado.

DOS CAMBIOS DE FONDO RESPECTO A LA PRIMERA VERSION
1. LOS PLAZOS SON POR TARJETA.
2. EL ORDEN LO MANDA EL SCORE, PERO PROTEGIDO POR LA REGLA DE SUPERVIVENCIA.
"""

from datetime import date
from app.domain.motor.evaluacion import evaluar

# Meses que amortiza el motor para poner precio al revolvente.
MESES_REVOLVENTE = 12


def _dias_para_proximo_ingreso(estado: dict) -> int:
    """
    Calcula cuántos días faltan para el próximo cobro basándose en el día de hoy.
    """
    programados = estado.get("ingresos_programados", [])
    if not programados:
        return 30

    hoy = date.today().day
    dia_pago = programados[0]["dia"]

    if dia_pago > hoy:
        return dia_pago - hoy
    elif dia_pago < hoy:
        return (30 - hoy) + dia_pago
    else:
        return 0


def _preferencia_modalidad(modalidad: str | None, monto: float, pago_mensual: float, liquidez: float, score: float, dias_para_nomina: int) -> int:
    """
    Jerarquía financiera dinámica con REGLA DE SUPERVIVENCIA y REGLA DE ABUNDANCIA.
    """
    if not modalidad:
        return 5
    
    # El crédito revolvente con intereses se penaliza fuertemente
    if modalidad == "credito":
        return 4

    if modalidad == "contado":
        colchon_minimo_vital = dias_para_nomina * 400
        liquidez_restante = liquidez - monto
        
        # Supervivencia: Si te deja sin para comer, se castiga severamente
        if liquidez_restante < colchon_minimo_vital:
            return 3 
            
        # Si la compra pasa de $2,000, penalizamos el contado (retorna 3) 
        # para que los MSI (que devuelven 1 o 2) ganen siempre la recomendación.
        if monto > 2000:
            return 3
            
        # Para compras menores a $2,000, si hay abundancia o score alto, manda el contado
        if monto <= (liquidez * 0.25) or monto < 500 or score >= 95:
            return 0
            
        return 2 

    if "_msi" in modalidad:
        plazo = int(modalidad.split("_")[0])
        
        # Castigo a micro-deudas largas
        if pago_mensual < 500 and plazo >= 9:
            return 3 
            
        # Escala dinámica por monto
        if monto >= 15000:
            if plazo >= 12:
                return 1
            return 2
        elif monto >= 5000:
            if 6 <= plazo <= 9:
                return 1
            return 2
        else:
            if plazo <= 6:
                return 1
            return 2

    return 5

def _costo_total(modalidad: str, monto: float, pago_mensual: float) -> float:
    """
    Lo que sale del bolsillo en total.
    """
    if modalidad == "credito":
        return round(pago_mensual * MESES_REVOLVENTE, 2)
    return round(monto, 2)


def _escenario_contado(estado: dict, monto: float) -> dict:
    r = evaluar(estado, {"tipo": "compra", "monto": monto, "modalidad": "contado"})
    alcanza = estado["liquidez"] >= monto
    return {
        "modalidad": "contado", "tarjeta": None, "tarjeta_id": None,
        "disponible": estado["liquidez"],
        "holgura_despues": round(estado["liquidez"] - monto, 2),
        "pago_mensual": 0,
        "viable": alcanza,
        "motivo": None if alcanza else "Liquidez insuficiente",
        "score_despues": r["score_despues"], "delta": r["delta"],
        "costo_total": round(monto, 2),
        "mejor_de_tarjeta": False,
        "_exacto": r["score_despues_exacto"],
    }


def _escenarios_de_tarjeta(estado: dict, t: dict, monto: float, plazos: list[int]) -> list[dict]:
    """Todas las formas de pagar `monto` con UNA tarjeta, con SUS plazos."""
    disponible = t["limite"] - t["saldo"]

    if disponible < monto:
        return [{
            "modalidad": None, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "holgura_despues": None, "pago_mensual": 0,
            "viable": False, "motivo": f"Disponible ${disponible:,.0f}, no alcanza",
            "score_despues": None, "delta": None,
            "costo_total": None, "mejor_de_tarjeta": False, "_exacto": -1.0,
        }]

    filas: list[dict] = []
    minimo_msi = t.get("monto_minimo_msi", 0) or 0
    
    if plazos and monto < minimo_msi:
        filas.append({
            "modalidad": None, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "holgura_despues": None, "pago_mensual": 0,
            "viable": False,
            "motivo": f"Los meses con esta tarjeta piden minimo ${minimo_msi:,.0f}",
            "score_despues": None, "delta": None,
            "costo_total": None, "mejor_de_tarjeta": False, "_exacto": -1.0,
        })
        plazos = []

    for mod in ["credito"] + [f"{m}_msi" for m in plazos]:
        r = evaluar(estado, {"tipo": "compra", "monto": monto,
                             "tarjeta_id": t["id"], "modalidad": mod})
        if mod == "credito":
            tm = t["tasa"] / 12
            pago = monto * (tm / (1 - (1 + tm) ** -MESES_REVOLVENTE))
        else:
            pago = monto / int(mod.split("_")[0])

        score_desp = r["score_despues"]
        exacto_desp = r["score_despues_exacto"]
        delta_val = r["delta"]

        # Castigo directo de sentido común al crédito con intereses caros
        if mod == "credito":
            score_desp = max(0, score_desp - 6)
            exacto_desp = max(0.0, exacto_desp - 6.0)
            delta_val = delta_val - 6

        filas.append({
            "modalidad": mod, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "pago_mensual": round(pago, 2),
            "viable": True, "motivo": None,
            "holgura_despues": round(disponible - monto, 2),
            "score_despues": score_desp, "delta": delta_val,
            "costo_total": _costo_total(mod, monto, pago),
            "mejor_de_tarjeta": False,
            "_exacto": exacto_desp,
        })

    return filas

def simular_compra(estado: dict, monto: float, plazos: list[int] | None = None,
                   opciones: list[dict] | None = None,
                   incluir_contado: bool = True) -> list[dict]:
    """
    Evalua cada forma de pagar la compra y las devuelve ordenadas.
    """
    plazos = plazos or []
    escenarios: list[dict] = []
    
    # Inyectamos tu función para proteger el colchón vital
    dias_para_nomina = _dias_para_proximo_ingreso(estado)

    if opciones is None:
        pares = [(t, plazos) for t in estado["tarjetas"]]
        incluir_contado = True
    else:
        por_id = {t["id"]: t for t in estado["tarjetas"]}
        pares = [
            (por_id[o["tarjeta_id"]], o.get("plazos") or [])
            for o in opciones if o["tarjeta_id"] in por_id
        ]

    if incluir_contado:
        escenarios.append(_escenario_contado(estado, monto))

    for tarjeta, plazos_tarjeta in pares:
        escenarios.extend(
            _escenarios_de_tarjeta(estado, tarjeta, monto, plazos_tarjeta)
        )

    # AQUÍ ESTÁ EL CAMBIO CLAVE EN EL ORDEN:
    escenarios.sort(key=lambda e: (
        not e["viable"],
        # 1. Tu regla de supervivencia manda (MSI cortos y contado le ganan al crédito)
        _preferencia_modalidad(e["modalidad"], monto, e["pago_mensual"], estado["liquidez"], e["score_despues"] or 0, dias_para_nomina),
        # 2. El Score ahora solo actúa como desempate dentro de la misma categoría
        -(e["score_despues"] or 0),  
        -e["_exacto"],               
        e["costo_total"] if e["costo_total"] is not None else float("inf"), 
        -(e.get("holgura_despues") or 0),
    ))

    vistos: set[str | None] = set()
    for e in escenarios:
        if e["viable"] and e["tarjeta_id"] not in vistos:
            vistos.add(e["tarjeta_id"])
            e["mejor_de_tarjeta"] = True

    for e in escenarios:
        del e["_exacto"]

    return escenarios