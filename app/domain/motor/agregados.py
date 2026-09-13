"""
Agregados derivados del `estado`.

Funciones puras de lectura: reciben el dict `estado` y devuelven numeros.
Ninguna toca la base de datos ni guarda nada.

Portado de contexto/motor.py sin cambios de logica.
"""


def obligaciones_mensuales(estado: dict) -> float:
    """Pagos minimos de tarjetas + mensualidades de MSI vigentes."""
    total = 0.0
    for t in estado["tarjetas"]:
        total += t["pago_minimo"]
        for m in t.get("msi", []):
            if m["meses_restantes"] > 0:
                total += m["monto_mensual"]
    return total


def intereses_mensuales(estado: dict) -> float:
    """
    Costo real de la deuda revolvente. NO incluye MSI, que en Mexico son 0%.
    Esto es lo que hace que el motor prefiera MSI sobre revolver saldo,
    y lo que hace que pagar deuda cara mejore el score.
    """
    total = 0.0
    for t in estado["tarjetas"]:
        msi_pendiente = sum(
            m["monto_mensual"] * m["meses_restantes"]
            for m in t.get("msi", []) if m["meses_restantes"] > 0
        )
        revolvente = max(0.0, t["saldo"] - msi_pendiente)
        total += revolvente * (t["tasa"] / 12)
    return total


def gasto_mensual_total(estado: dict) -> float:
    """Todo lo que sale al mes: fijos + variables + obligaciones de credito."""
    return (estado["gastos"]["fijos"]
            + estado["gastos"]["variables_prom"]
            + obligaciones_mensuales(estado))


def saldo_credito_total(estado: dict) -> float:
    return sum(t["saldo"] for t in estado["tarjetas"])


def limite_credito_total(estado: dict) -> float:
    return sum(t["limite"] for t in estado["tarjetas"])


def disponible(tarjeta: dict) -> float:
    """Derivado, NUNCA se guarda en la base de datos."""
    return tarjeta["limite"] - tarjeta["saldo"]