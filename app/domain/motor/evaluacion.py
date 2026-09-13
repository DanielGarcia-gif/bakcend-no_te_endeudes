"""
evaluar() — la funcion unica del producto.

Toma un `estado` y una accion hipotetica, y devuelve como queda la situacion
financiera. Trabaja sobre una copia profunda: NUNCA muta el estado recibido,
que es lo que permite usarla desde el simulador de solo lectura.

Portado de contexto/motor.py sin cambios de logica.
"""

import copy

from app.domain.motor.score import calcular_score


def buscar_tarjeta(estado: dict, tarjeta_id: str) -> dict:
    for t in estado["tarjetas"]:
        if t["id"] == tarjeta_id:
            return t
    raise KeyError(f"Tarjeta no encontrada: {tarjeta_id}")


def evaluar(estado: dict, accion: dict) -> dict:
    """
    accion:
      {"tipo": "ninguna"}
      {"tipo": "compra",  "monto": 15000, "tarjeta_id": "bbva", "modalidad": "12_msi"}
      {"tipo": "compra",  "monto": 15000, "modalidad": "contado"}
      {"tipo": "pago",    "monto": 2500,  "tarjeta_id": "nu"}
      {"tipo": "gasto",   "monto": 850,   "medio": "debito"}
      {"tipo": "gasto",   "monto": 850,   "medio": "credito", "tarjeta_id": "bbva"}
      {"tipo": "recurrente", "monto": 4000, "dia": 1, "concepto": "Renta"}
    """
    nuevo = copy.deepcopy(estado)
    t = accion["tipo"]

    if t == "compra":
        monto = accion["monto"]
        mod = accion["modalidad"]
        if mod == "contado":
            nuevo["liquidez"] -= monto
        else:
            tarjeta = buscar_tarjeta(nuevo, accion["tarjeta_id"])
            tarjeta["saldo"] += monto
            if mod == "credito":
                # Revolver no es gratis: para salir en 12 meses hay que cubrir
                # capital mas intereses. Comparar contra MSI (0%) usando solo
                # el pago minimo del 5% haria ver el revolvente como mejor opcion.
                tasa_m = tarjeta["tasa"] / 12
                tarjeta["pago_minimo"] += monto * (tasa_m / (1 - (1 + tasa_m) ** -12))
            else:
                meses = int(mod.split("_")[0])
                tarjeta.setdefault("msi", []).append({
                    "monto_mensual": monto / meses,
                    "meses_restantes": meses,
                })

    elif t == "pago":
        tarjeta = buscar_tarjeta(nuevo, accion["tarjeta_id"])
        nuevo["liquidez"] -= accion["monto"]
        tarjeta["saldo"] = max(0, tarjeta["saldo"] - accion["monto"])

    elif t == "gasto":
        if accion.get("medio") == "credito":
            buscar_tarjeta(nuevo, accion["tarjeta_id"])["saldo"] += accion["monto"]
        else:
            nuevo["liquidez"] -= accion["monto"]

    elif t == "recurrente":
        # Un gasto recurrente NO cobra nada hoy: describe un compromiso que se
        # repite. No toca la liquidez; sube el gasto fijo mensual y agrega un
        # evento a la proyeccion de flujo. Es exactamente lo que produce
        # EstadoRepository al leer la tabla `recurrentes`, asi que el antes y
        # el despues que se calculan aqui coinciden con lo que quedara guardado.
        nuevo["gastos"]["fijos"] += accion["monto"]
        nuevo["compromisos"].append({
            "dia": accion["dia"],
            "monto": accion["monto"],
            "concepto": accion.get("concepto", ""),
        })

    antes = calcular_score(estado)
    despues = calcular_score(nuevo)

    return {
        "estado_resultante": nuevo,
        "score_antes": antes["score"],
        "score_despues": despues["score"],
        "delta": despues["score"] - antes["score"],
        "score_antes_exacto": antes["score_exacto"],
        "score_despues_exacto": despues["score_exacto"],
        # `desglose` son los componentes DESPUES. Los de antes se exponen
        # aparte porque el micro-momento necesita comparar componente a
        # componente, no solo el score global.
        "desglose": despues["componentes"],
        "desglose_antes": antes["componentes"],
        "saldo_minimo": despues["saldo_minimo"],
        "dia_saldo_minimo": despues["dia_saldo_minimo"],
    }