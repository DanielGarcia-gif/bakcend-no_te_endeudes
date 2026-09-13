"""
Reglas de validacion de negocio.

Esta validacion no la da nadie mas: ni la base (los CHECK cubren rangos, no
reglas), ni Pydantic (valida forma, no coherencia contra el estado). La
ponemos nosotros.

Funciones PURAS: reciben el estado y la peticion, devuelven el mensaje de
error o None. No lanzan excepciones ni tocan la base: quien decide convertir
un mensaje en ReglaDeNegocioViolada es el servicio que las llama.

validar_gasto() viene de contexto/tipos.py sin cambios de logica; el resto
son las validaciones que el briefing marca como faltantes.
"""

from datetime import date

from app.core.exceptions import RecursoNoEncontrado

# Ventana aceptable para la fecha de un movimiento.
# TODO: el briefing dice "fechas en rango" sin definir el rango. Estos valores
# son una decision nuestra: hasta 1 año atras para poder capturar historial y
# practicamente nada hacia adelante, porque la app es una foto del presente y
# un gasto futuro descuadraria el saldo que ya se movio. Confirmar con el equipo.
DIAS_ATRAS_MAX = 365
# 1 dia de holgura, no 0: el cliente manda su fecha LOCAL y el servidor puede
# estar en otra zona horaria. Con margen cero, un usuario en Mexico a las 7 pm
# contra un servidor en UTC veria su gasto de hoy rechazado por "futuro".
DIAS_ADELANTE_MAX = 1


def a_id_interno(valor: str | None) -> int | None:
    """
    Convierte un id que viene del cliente al entero de la base.

    Los ids viajan como string en el contrato (`TarjetaEstado.id`), pero en
    SQLite son enteros. Sin esto, un id no numerico revienta con ValueError y
    sale un 500; asi sale un 404, que es lo que realmente pasa.
    """
    if valor is None or valor == "":
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise RecursoNoEncontrado(f"Identificador invalido: {valor!r}")


def _tarjeta(estado: dict, tarjeta_id: str | None) -> dict | None:
    return next((t for t in estado["tarjetas"] if t["id"] == tarjeta_id), None)


def tarjeta_o_404(estado: dict, tarjeta_id: str) -> dict:
    """
    Busca la tarjeta en el estado o lanza RecursoNoEncontrado.

    Es la excepcion a la regla de este modulo (devolver el mensaje en vez de
    lanzar) y es deliberada: un id que no existe NO es una regla de negocio
    incumplida, es un 404. Sin esto salia 422, y el frontend no podia
    distinguir "mandaste un id que no existe" de "no te alcanza el saldo".
    """
    t = _tarjeta(estado, tarjeta_id)
    if t is None:
        raise RecursoNoEncontrado(f"Tarjeta no encontrada: {tarjeta_id!r}")
    return t


def validar_gasto(estado: dict, req) -> str | None:
    """
    Devuelve el mensaje de error, o None si es valido.

    Se discrimina por `medio == "credito"`, no por `medio == "debito"`. Parece
    lo mismo y no lo es: cuando MedioPago solo tenia dos valores, el `else` era
    seguro. Al entrar `efectivo` como tercer medio —antes colapsaba con debito
    porque se infería de tarjeta_id IS NULL— ese `else` empezo a tratar el
    efectivo como credito y a exigirle una tarjeta que no tiene.

    Efectivo y debito salen del mismo bolsillo (`saldo_disponible`) y por eso
    validan igual; credito consume linea, que es otra cosa.
    """
    if req.monto <= 0:
        return "El monto debe ser mayor a cero"

    if req.medio == "credito":
        t = _tarjeta(estado, req.tarjeta_id)
        if t is None:
            return "Tarjeta no encontrada"
        if req.monto > (t["limite"] - t["saldo"]):
            return f"Excede tu linea disponible en {t['nombre']}"
        return None

    if req.monto > estado["liquidez"]:
        return f"No alcanza: tu disponible es ${estado['liquidez']:,.0f}"
    return None


def validar_pago(estado: dict, tarjeta_id: str, monto: float) -> str | None:
    """
    Un pago no puede exceder el saldo de la tarjeta (pagar de mas no es un
    caso de uso del producto) ni la liquidez del usuario.
    """
    if monto <= 0:
        return "El monto debe ser mayor a cero"
    t = _tarjeta(estado, tarjeta_id)
    if t is None:
        return "Tarjeta no encontrada"
    if monto > t["saldo"]:
        return f"El pago excede el saldo de {t['nombre']} (${t['saldo']:,.0f})"
    if monto > estado["liquidez"]:
        return f"No alcanza: tu disponible es ${estado['liquidez']:,.0f}"
    return None


def validar_compra(estado: dict, monto: float, tarjeta_id: str | None) -> str | None:
    """
    Compra contra una tarjeta concreta: debe caber en la linea disponible.
    El simulador NO usa esto: alli un escenario inviable se devuelve marcado
    con su motivo en vez de rechazarse, para que el frontend lo muestre.
    """
    if monto <= 0:
        return "El monto debe ser mayor a cero"
    if tarjeta_id is None:
        if monto > estado["liquidez"]:
            return f"No alcanza: tu disponible es ${estado['liquidez']:,.0f}"
        return None
    t = _tarjeta(estado, tarjeta_id)
    if t is None:
        return "Tarjeta no encontrada"
    disponible = t["limite"] - t["saldo"]
    if monto > disponible:
        return f"Excede tu linea disponible en {t['nombre']} (${disponible:,.0f})"
    return None


def validar_fecha(fecha_iso: str) -> str | None:
    """Formato YYYY-MM-DD y dentro de la ventana aceptable."""
    try:
        f = date.fromisoformat(fecha_iso)
    except ValueError:
        return "La fecha debe tener formato YYYY-MM-DD"
    hoy = date.today()
    if (hoy - f).days > DIAS_ATRAS_MAX:
        return "La fecha es demasiado antigua"
    if (f - hoy).days > DIAS_ADELANTE_MAX:
        return "La fecha no puede estar en el futuro"
    return None


def validar_terminos_tarjeta(
    dia_corte: int,
    dia_limite_pago: int,
    limite: float,
    saldo: float,
) -> str | None:
    """
    Los rangos 1-31 y los minimos ya los cubre Pydantic. Aqui solo lo que
    Pydantic no puede ver: la coherencia entre campos.

    La usan TarjetaService (PUT /tarjetas/{id}/terminos) y OnboardingService
    (POST /onboarding), que capturan lo mismo por caminos distintos.
    """
    if dia_corte == dia_limite_pago:
        return "El dia de corte y el dia limite de pago no pueden ser el mismo"
    if saldo > limite:
        return "El saldo no puede exceder el limite"
    return None


def validar_dias_de_pago(
    frecuencia: str,
    dia_pago: int | None,
    dia_pago_2: int | None,
    fecha_ancla=None,
) -> str | None:
    """
    Cada familia de frecuencia se define con lo suyo, y no son intercambiables.

    ESTA REGLA ESTABA AL REVES. La version anterior exigia `dia_pago_2` para
    catorcenal, y el esquema lo PROHIBE (ck_ingresos_dia2_quincenal). Las dos no
    podian tener razon: cualquier ingreso catorcenal que pasara la validacion
    era rechazado por la base, y cualquiera que la base aceptara era rechazado
    por la validacion. Catorcenal simplemente no era registrable.

    Lo correcto, y lo que el esquema impone:

      semanal, catorcenal    se definen por `fecha_ancla` y se avanzan sumando
                             dias. Catorcenal son 26 pagos al ano: hay meses con
                             dos y meses con tres, asi que NO es expresable como
                             dos dias del mes. Pedirle un dia_pago_2 fabricaba
                             un calendario falso.

      quincenal, mensual     se definen por `dia_pago`. Quincenal en Mexico no
                             es "cada 15 dias": son dos veces al mes (15 y
                             ultimo), y solo esta admite `dia_pago_2`.

    La usan IngresoService (POST /ingresos) y OnboardingService.
    """
    if frecuencia in ("semanal", "catorcenal"):
        if fecha_ancla is None:
            return (f"Un ingreso {frecuencia} se define por su fecha de "
                    "referencia: indica cuando fue el ultimo pago")
        if dia_pago_2 is not None:
            return (f"Un ingreso {frecuencia} no lleva segundo dia de pago: "
                    "su ciclo se cuenta en dias, no en dias del mes")
        return None

    if dia_pago is None:
        return f"Un ingreso {frecuencia} necesita su dia de pago"

    if frecuencia == "mensual":
        if dia_pago_2 is not None:
            return "Un ingreso mensual solo tiene un dia de pago"
        return None

    # quincenal
    if dia_pago_2 is None:
        return "Un ingreso quincenal necesita sus dos dias de pago"
    if dia_pago == dia_pago_2:
        return "Los dos dias de pago no pueden ser el mismo"
    return None