"""
Priorizacion de deuda — que tarjeta pagar primero.

No es un solver: es un puntaje ponderado y explicable, que es justo lo que
queremos poder defender ante el jurado.

Las razones se redactan AQUI, con aritmetica. El frontend puede pedirle a
Gemini que las vuelva a contar mas bonito, pero el numero y el motivo salen de
este archivo: la IA explica, no calcula.

Portado de contexto/motor.py sin cambios de logica.
"""

# Pesos de la formula de prioridad y sus normalizadores.
PESO_TASA = 0.45
PESO_UTIL = 0.35
PESO_COSTO = 0.20

TASA_REFERENCIA = 0.80      # 80% anual satura el componente de tasa
UTIL_REFERENCIA = 0.90      # 90% de utilizacion satura el componente
COSTO_REFERENCIA = 1500.0   # $1,500/mes de intereses satura el componente

# Umbrales a partir de los cuales se redacta cada razon.
UMBRAL_RAZON_TASA = 0.55
UMBRAL_RAZON_UTIL = 0.70
UMBRAL_RAZON_COSTO = 400.0


def priorizar_deudas(estado: dict) -> list[dict]:
    """Ordena tarjetas por urgencia. Las que no deben nada quedan fuera."""
    ranking = []
    for t in estado["tarjetas"]:
        if t["saldo"] <= 0:
            continue
        util = t["saldo"] / t["limite"] if t["limite"] else 0
        costo_mensual = t["saldo"] * (t["tasa"] / 12)

        # Normalizamos a 0-100 y ponderamos
        p_tasa = min(t["tasa"] / TASA_REFERENCIA, 1.0) * 100
        p_util = min(util / UTIL_REFERENCIA, 1.0) * 100
        p_costo = min(costo_mensual / COSTO_REFERENCIA, 1.0) * 100

        prioridad = p_tasa * PESO_TASA + p_util * PESO_UTIL + p_costo * PESO_COSTO

        razones = []
        if t["tasa"] >= UMBRAL_RAZON_TASA:
            razones.append(f"tasa alta ({t['tasa']*100:.0f}% anual)")
        if util >= UMBRAL_RAZON_UTIL:
            razones.append(f"utilizacion al {util*100:.0f}%, castiga tu score")
        if costo_mensual >= UMBRAL_RAZON_COSTO:
            razones.append(f"te cuesta ${costo_mensual:,.0f} al mes solo en intereses")

        ranking.append({
            # El id ademas del nombre. Sin el, el frontend tenia que cruzar este
            # ranking contra GET /estado buscando por nombre para saber a que
            # tarjeta pagar; dos tarjetas del mismo banco rompian ese cruce.
            # No altera ninguna cifra: solo agrega una clave.
            "tarjeta_id": t["id"],
            "tarjeta": t["nombre"],
            "saldo": t["saldo"],
            "utilizacion": round(util * 100, 1),
            "tasa": t["tasa"],
            "costo_intereses_mes": round(costo_mensual, 2),
            "prioridad": round(prioridad, 1),
            "razones": razones,
        })

    ranking.sort(key=lambda x: -x["prioridad"])
    return ranking