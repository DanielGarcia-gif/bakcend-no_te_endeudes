"""
Financial Decision Simulator — backend.

Arquitectura por capas:

    HTTP -> Router -> Schema -> Service -> Motor -> Repository -> SQLite

El motor de negocio (app.domain.motor) es un motor de REGLAS, no un modelo de
IA, y vive dentro de esta aplicacion como capa de negocio: no es un script ni
un proceso aparte.
"""