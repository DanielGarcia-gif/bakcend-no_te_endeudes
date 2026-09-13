"""
El dominio: el contrato de tipos, las reglas de negocio y el motor.

Todo lo que hay aqui es PURO. No importa FastAPI, no importa sqlite3 y no
sabe que existe una API alrededor. Se puede probar sin base de datos y sin
cliente HTTP.
"""
from app.domain.motor.agregados import intereses_mensuales, obligaciones_mensuales
from app.domain.motor.evaluacion import evaluar
from app.domain.motor.priorizacion import priorizar_deudas
from app.domain.motor.proyeccion import proyectar_flujo
from app.domain.motor.score import banda, calcular_score
from app.domain.motor.simulador import simular_compra
from app.domain.motor.umbrales import PESOS
from app.domain.motor.veredicto import evaluar_compra

__all__ = [
    "PESOS",
    "banda",
    "calcular_score",
    "evaluar",
    "evaluar_compra",
    "intereses_mensuales",
    "obligaciones_mensuales",
    "priorizar_deudas",
    "proyectar_flujo",
    "simular_compra",
]
