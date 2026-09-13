"""
Caso de uso: registro, login, sesion demo, perfil del usuario en sesion y la
correccion manual de su liquidez.

Auth minima segun el briefing: hash + token. Sin verificacion de correo, sin
recuperacion, sin OAuth.
"""

from app.core.exceptions import CredencialesInvalidas, RecursoNoEncontrado
from app.core.security import crear_token, hashear_password, verificar_password
from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.repositories.usuario_repository import UsuarioRepository
from app.schemas.consultas import LiquidezUpdate, UsuarioResumen
from app.services.onboarding_service import tiene_datos_capturados


class AuthService:

    def __init__(
        self,
        usuario_repository: UsuarioRepository,
        ingreso_repository: IngresoRepository,
        tarjeta_repository: TarjetaRepository,
        recurrente_repository: RecurrenteRepository,
        auditoria_repository: AuditoriaRepository,
    ):
        self.usuarios = usuario_repository
        self.ingresos = ingreso_repository
        self.tarjetas = tarjeta_repository
        self.recurrentes = recurrente_repository
        self.auditoria = auditoria_repository

    def registrar(self, nombre: str, email: str, password: str) -> dict:
        """El repositorio lanza ConflictoDeEstado si el correo ya existe."""
        usuario = self.usuarios.crear(
            nombre=nombre,
            email=email.lower().strip(),
            password_hash=hashear_password(password),
        )
        return self._sesion(usuario)

    def login(self, email: str, password: str) -> dict:
        usuario = self.usuarios.buscar_por_email(email.lower().strip())
        # Mismo mensaje exista o no el correo: no confirmamos que emails
        # estan registrados.
        if usuario is None or not verificar_password(password, usuario.password_hash):
            raise CredencialesInvalidas("Correo o contrasena incorrectos")
        return self._sesion(usuario)

    def sesion_demo(self) -> dict:
        """
        Token del usuario demo precargado. Es el guion del pitch: el jurado
        entra con un clic y ve datos que cuentan una historia.
        """
        usuario = self.usuarios.buscar_demo()
        if usuario is None:
            raise RecursoNoEncontrado(
                "No hay usuario demo. Siembra la base con: python -m app.scripts.seed_demo"
            )
        return self._sesion(usuario)

    def perfil(self, usuario_id: int) -> UsuarioResumen:
        """
        Quien es el dueño del token.

        El frontend guarda el token y poco mas; al recargar la PWA, el nombre
        que devolvio el login ya se perdio. Este endpoint lo recupera y de
        paso confirma que la sesion sigue viva: si el token esta vencido, ni
        siquiera llega hasta aqui (la dependencia lanza 401 antes).
        """
        u = self.usuarios.obtener(usuario_id)
        return UsuarioResumen(
            id=str(u.id),
            nombre=u.nombre,
            email=u.email,
            es_demo=u.es_demo,
            onboarding_completo=tiene_datos_capturados(
                self.ingresos, self.tarjetas, usuario_id, self.recurrentes
            ),
            saldo_disponible=u.saldo_disponible,
            creado_en=u.creado_en,
            version=u.version,
        )

    def corregir_liquidez(self, usuario_id: int, datos: LiquidezUpdate) -> UsuarioResumen:
        """
        "Mi banco dice otra cosa". No es un movimiento: fija el saldo absoluto
        y deja fila en auditoria, porque un saldo que cambia sin movimiento que
        lo explique tiene que ser rastreable.

        Con `version`, el repositorio responde 409 si alguien escribio primero.
        """
        antes = self.usuarios.obtener(usuario_id)
        self.usuarios.fijar_liquidez(usuario_id, datos.saldo, datos.version)
        self.auditoria.registrar(
            "usuarios", usuario_id, "actualizado", usuario_id,
            datos_antes={"saldo_disponible": antes.saldo_disponible},
            datos_despues={"saldo_disponible": datos.saldo, "motivo": datos.motivo},
            origen="api:PUT /usuarios/me/liquidez",
        )
        return self.perfil(usuario_id)

    def _sesion(self, usuario) -> dict:
        return {
            "token": crear_token(usuario.id),
            "usuario_id": usuario.id,
            "nombre": usuario.nombre,
        }
