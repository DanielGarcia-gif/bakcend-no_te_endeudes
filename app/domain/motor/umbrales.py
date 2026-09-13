"""
UMBRALES DEL SCORE — el unico lugar donde se tocan estos numeros.

Portado de contexto/motor.py sin cambiar un solo valor. Los cuatro
componentes estan acoplados: si mueves un umbral, el demo del pitch deja de
dar 80 y hay que volver a correr todo.

El motor esta basado en REGLAS, no en ML. Esa es la fortaleza: es auditable
y explicable linea por linea.
"""

PESOS = {
    "liquidez": 0.30,
    "deuda": 0.30,
    "utilizacion": 0.20,
    "flujo": 0.20,
}

# Liquidez: meses de gasto total cubiertos por el dinero disponible.
# Curva quebrada: llegar al primer mes vale mas que pasar del segundo al tercero.
LIQ_MES_1 = 1.0      # 1 mes de colchon  ->  50 puntos
LIQ_MES_MAX = 3.0    # 3 meses o mas     -> 100 puntos

# Carga de deuda: obligaciones mensuales / ingreso mensual.
DEUDA_OPTIMA = 0.25   # 25% o menos -> 100 puntos
DEUDA_CRITICA = 0.55  # 55% o mas   ->   0 puntos

# Utilizacion de credito: saldo total / limite total.
UTIL_OPTIMA = 0.30    # 30% o menos -> 100 puntos
UTIL_CRITICA = 0.80   # 80% o mas   ->   0 puntos

# Salud del flujo: saldo minimo proyectado / gasto mensual total.
FLUJO_OBJETIVO = 0.50  # medio mes de colchon en el peor dia -> 100 puntos

DIAS_PROYECCION = 30

# Bandas de interpretacion del score total.
BANDAS = [
    (80, "Saludable", "verde"),
    (60, "Estable", "amarillo"),
    (40, "En riesgo", "naranja"),
    (0, "Critico", "rojo"),
]

MODALIDADES = ["contado", "credito", "3_msi", "6_msi", "12_msi"]

PLAZOS_COMUNES = [3, 6, 9, 12, 15, 18]


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))