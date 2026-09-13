"""
Configuracion centralizada de la aplicacion.

Todo valor configurable vive aqui y se lee de variables de entorno o del
archivo .env. Ningun otro modulo debe leer os.environ directamente.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- aplicacion ---
    app_name: str = "Financial Decision Simulator"
    app_version: str = "2.0.0"
    debug: bool = False

    # --- base de datos ---
    # MySQL 8.0.16+. Antes de esa version los CHECK se aceptan y se IGNORAN en
    # silencio, y este esquema apoya casi toda su integridad en CHECKs: correrlo
    # en 8.0.15 produce una base que parece correcta y no valida nada.
    #
    # La base YA EXISTE. La app no ejecuta DDL al arrancar (eso era de la epoca
    # de SQLite y CREATE TABLE IF NOT EXISTS); el esquema se aplica una vez con
    # `python -m scripts.aplicar_esquema`.
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "no_te_endudes"
    db_pool_size: int = 5

    # --- HTTP ---
    # El contrato vive bajo /api/v1. Los routers estan organizados en api/v1 y
    # este valor decide donde se montan.
    api_prefix: str = "/api/v1"
    # NoDecode: sin el, pydantic-settings intenta parsear el valor del .env
    # como JSON antes de que corra el validador de abajo, y una linea normal
    # como `CORS_ORIGINS=http://a,http://b` revienta el arranque entero.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # --- seguridad ---
    # Auth minima segun el briefing: hash con passlib + JWT simple.
    # Sin verificacion de correo, sin recuperacion, sin OAuth.
    #
    # SIN DEFAULT a proposito (hallazgo A3): una clave de firma con valor por
    # defecto es una clave publica. Si falta, la app no arranca — que es
    # exactamente lo que debe pasar, y falla en el import, no en el primer
    # login de la demo.
    secret_key: str = Field(min_length=16)
    algoritmo_token: str = "HS256"
    # 7 dias: cubre el demo del hackathon sin obligar a re-login en el ensayo.
    token_expire_minutes: int = 60 * 24 * 7

    # --- Gemini ---
    # La llave vive AQUI y solo aqui. Antes viajaba en el bundle de la PWA, o
    # sea que cualquiera con las devtools abiertas se la llevaba; ahora el
    # navegador nunca la ve.
    #
    # Vacia = IA apagada. La app arranca igual y los dos endpoints de IA
    # responden 503: el ranking, el score y la captura manual no dependen de
    # Gemini para nada.
    gemini_api_key: str = ""
    # En orden de preferencia. Si uno responde 503 (saturado) se prueba el
    # siguiente; un 404 corta, porque significa que la llave no tiene ese
    # modelo y reintentar no lo va a arreglar.
    gemini_modelos: Annotated[list[str], NoDecode] = [
        "gemini-3.1-flash-lite",
        "gemini-3.7-flash",
    ]
    # Un estado de cuenta de 15 MB tarda. 120 s es lo que usa el script de
    # contexto/test_gemini.py, que es donde se midio. En SEGUNDOS: el SDK lo
    # quiere en milisegundos y la conversion la hace app/core/gemini.py.
    gemini_timeout: int = 120

    @field_validator("cors_origins", "gemini_modelos", mode="before")
    @classmethod
    def _separar_lista(cls, v):
        """Acepta 'a,b,c' ademas de una lista JSON."""
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("secret_key")
    @classmethod
    def _rechazar_clave_de_ejemplo(cls, v: str) -> str:
        if v.strip().lower() in ("cambiame-esta-clave-en-el-entorno", "changeme", "secret"):
            raise ValueError(
                "SECRET_KEY tiene el valor de ejemplo. Generar una propia con:\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Cacheada: la configuracion se lee una sola vez por proceso."""
    return Settings()


settings = get_settings()