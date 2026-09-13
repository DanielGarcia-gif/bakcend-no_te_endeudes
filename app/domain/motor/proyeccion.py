"""
Proyeccion de flujo a 30 dias.

La app no tiene nocion del paso del tiempo: esta proyeccion es una foto del
presente proyectada hacia adelante, no un historial. No hay corte de mes ni
persistencia de la serie.

Portado de contexto/motor.py sin cambios de logica.
"""

from app.domain.motor.umbrales import DIAS_PROYECCION


def proyectar_flujo(estado: dict, dias: int = DIAS_PROYECCION):
    """
    Simula dia por dia el saldo disponible.
    Devuelve (serie_diaria, saldo_minimo, dia_del_minimo).
    """
    saldo = estado["liquidez"]
    gasto_diario = estado["gastos"]["variables_prom"] / 30.0

    # Mapa dia -> monto (positivo entra, negativo sale)
    eventos: dict[int, float] = {}

    def agregar(dia, monto):
        if 1 <= dia <= dias:
            eventos[dia] = eventos.get(dia, 0.0) + monto

    for ing in estado["ingresos_programados"]:
        agregar(ing["dia"], ing["monto"])

    for c in estado["compromisos"]:
        agregar(c["dia"], -c["monto"])

    for t in estado["tarjetas"]:
        pago = t["pago_minimo"] + sum(
            m["monto_mensual"] for m in t.get("msi", []) if m["meses_restantes"] > 0
        )
        agregar(t["limite_pago"], -pago)

    serie = []
    minimo = saldo
    dia_min = 0
    for d in range(1, dias + 1):
        saldo += eventos.get(d, 0.0) - gasto_diario
        serie.append(round(saldo, 2))
        if saldo < minimo:
            minimo = saldo
            dia_min = d

    return serie, minimo, dia_min