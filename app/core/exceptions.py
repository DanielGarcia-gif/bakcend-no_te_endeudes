"""
Jerarquia de excepciones del dominio.

Los servicios lanzan estas excepciones; los handlers registrados en main.py
las traducen a respuestas HTTP uniformes. Los endpoints NO llevan try/except.
"""


class DominioError(Exception):
    """Raiz de todos los errores propios de la aplicacion."""

    status_code: int = 400
    codigo: str = "error_dominio"

    def __init__(self, mensaje: str, detalle: dict | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.detalle = detalle or {}


class RecursoNoEncontrado(DominioError):
    """El usuario, la tarjeta o el registro pedido no existe."""

    status_code = 404
    codigo = "no_encontrado"


class ReglaDeNegocioViolada(DominioError):
    """
    La operacion es sintacticamente valida pero rompe una regla del negocio:
    un gasto que excede la liquidez, un pago mayor al saldo de la tarjeta,
    una compra que no cabe en la linea disponible.
    """

    status_code = 422
    codigo = "regla_de_negocio"


class CredencialesInvalidas(DominioError):
    """Email o password incorrectos."""

    status_code = 401
    codigo = "credenciales_invalidas"


class NoAutenticado(DominioError):
    """Falta el token, esta vencido o es ilegible."""

    status_code = 401
    codigo = "no_autenticado"


class ConflictoDeEstado(DominioError):
    """El recurso ya existe o su estado impide la operacion (email duplicado)."""

    status_code = 409
    codigo = "conflicto"


class ErrorDePersistencia(DominioError):
    """Fallo al escribir en la base. La transaccion quedo revertida."""

    status_code = 500
    codigo = "error_persistencia"


class ServicioIANoDisponible(DominioError):
    """
    Gemini no contesto util: falta la llave, esta saturado, se acabo el tiempo
    o devolvio algo que no es el JSON pedido.

    Es 503 y no 500 a proposito. La IA es adorno: lee el PDF para prellenar un
    formulario que se puede capturar a mano, y redacta un texto sobre un
    ranking que el motor ya calculo. Un 503 le dice al frontend "vuelve a
    intentar o sigue sin esto", que es exactamente lo que hace.
    """

    status_code = 503
    codigo = "ia_no_disponible"


# El PDF ilegible NO va aqui: un archivo que no es PDF, que pesa de mas o que
# viene cifrado es culpa de lo que subio el usuario, no del servicio. Eso sale
# como ReglaDeNegocioViolada (422) con un mensaje que dice que hacer.