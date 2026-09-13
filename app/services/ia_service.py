"""
Casos de uso que pasan por Gemini: leer un estado de cuenta, explicar el
ranking de deuda y analizar a fondo una compra.

Los dos vivian en el frontend, que llamaba a Google directamente con la API key
metida en el bundle de Vite. Aqui la llave no sale del servidor y el navegador
solo manda el PDF.

LA REGLA QUE NO CAMBIA: Gemini extrae y redacta, NO calcula. La extraccion
prellena un formulario que la persona confirma; la explicacion habla de cifras
que ya produjo el motor determinista. Si este servicio entero se cae, la app
sigue funcionando: los terminos se capturan a mano y el ranking se lee con sus
razones calculadas.
"""

import json
import logging

from google.genai import types

from app.core import gemini
from app.core.exceptions import ReglaDeNegocioViolada, ServicioIANoDisponible
from app.domain.extraccion import (
    PROMPT_EXTRACCION,
    EstadoDeCuentaIA,
    ModoPago,
    mapear,
)
from app.schemas.ia import (
    AnalisisCompraIA,
    AnalisisCompraResponse,
    ExplicacionDeudaResponse,
    ExtraccionResponse,
)
from app.schemas.simulacion import SimulacionRequest
from app.services.categoria_service import CategoriaService
from app.services.motor_service import MotorService
from app.services.tarjeta_service import TarjetaService

log = logging.getLogger("app")

# 15 MB. Es el mismo tope que ya aplicaba el navegador, y por arriba de eso el
# documento casi siempre trae el anio entero en vez del resumen del mes.
MAX_BYTES = 15 * 1024 * 1024


PROMPT_PRIORIDAD = """Eres un asesor financiero que explica en espanol de Mexico, breve y llano,
el resultado de un motor que prioriza que tarjeta de credito conviene pagar primero.
Recibes el JSON que produjo el motor y llenas los campos del esquema.

Reglas estrictas:
- Usa unicamente los numeros que vienen en el JSON. Nunca calcules, estimes ni inventes cifras.
- La tarjeta prioritaria es SIEMPRE la primera del arreglo "ranking". No propongas otro orden ni otro criterio.
- No prometas resultados: nada de "vas a subir tu score", "te ahorras X al ano", ni proyecciones a futuro.
- No recomiendes productos, refinanciamientos, prestamos, consolidaciones ni instituciones.
- Hablale de tu a la persona. Frases cortas. Sin tecnicismos: di "lo que pagas de intereses cada mes",
  no "costo financiero devengado".
- Formatea los montos como $1,234 y las tasas como 68% anual.
- Si "ranking" viene vacio: titular "No tienes deuda de tarjetas registrada",
  explicacion de una linea, siguiente_paso invitando a registrar una tarjeta,
  comparativa null y confianza "alta".
- "titular": una sola linea, maximo 70 caracteres, nombra la tarjeta prioritaria.
- "explicacion": 2 o 3 oraciones. Di por que esa va primero, apoyandote en su tasa,
  su utilizacion y lo que cuesta al mes en intereses.
- "siguiente_paso": una accion concreta que la persona pueda hacer hoy, en una oracion.
- "comparativa": una oracion que contraste la prioritaria contra la segunda del ranking.
  Si solo hay una tarjeta, devuelvelo como null.
- "confianza": "alta" si el ranking trae tasa, saldo y utilizacion completos;
  "media" si falta alguno; "baja" si el JSON viene incompleto o contradictorio."""


PROMPT_ANALISIS = """Eres un asesor financiero que explica en espanol de Mexico, breve y llano,
por que conviene (o no) una compra y con que forma de pago.
Recibes el JSON que produjo un motor determinista y llenas los campos del esquema.

Reglas estrictas:
- Usa unicamente los numeros que vienen en el JSON. Nunca calcules, estimes ni inventes cifras.
- La forma de pago recomendada es SIEMPRE la de "recomendada". No propongas otra ni otro criterio.
- El veredicto ya esta decidido en "situacion.veredicto" y no te toca cambiarlo: tu lo cuentas.
- No prometas resultados: nada de "vas a subir tu score" ni proyecciones a futuro.
- No recomiendes productos, refinanciamientos, prestamos, consolidaciones ni instituciones.
- Hablale de tu a la persona. Frases cortas. Sin tecnicismos: di "lo que te queda disponible",
  no "holgura post-transaccion".
- Cada opcion trae "sale_de" y "te_queda": el efectivo y la linea de credito NO son lo mismo
  y no se comparan entre si. Nunca digas que una tarjeta "te deja mas dinero" que el contado.
- Formatea los montos como $1,234 y los porcentajes como 45%.
- "titular": una sola linea, maximo 70 caracteres. Nombra la forma de pago recomendada.
- "explicacion": 2 o 3 oraciones. Por que esa opcion le gana a las otras, apoyandote en
  su pago mensual, su costo total y el score que deja.
- "comparativas": de 2 a 4 oraciones, cada una contrastando la recomendada contra OTRA
  opcion concreta de "opciones", nombrandola. Si solo hay una opcion, devuelve la lista vacia.
- "categoria": elige UNA clave de "categorias_validas", la que mejor describe lo que se
  compra segun "compra.descripcion". Si no hay descripcion o no encaja ninguna, usa "otros".
- "reflexion": SOLO si "situacion.veredicto" es distinto de "conviene". Una pregunta corta y
  sin regano que invite a pensar si esa compra hace falta ahora. Si el veredicto es
  "conviene", devuelvelo como null.
- "riesgos": lo que puede salir mal, tomado de "situacion.razones". Lista vacia si no hay.
- "confianza": "alta" si las opciones traen score y costo completos; "media" si falta alguno;
  "baja" si el JSON viene incompleto o contradictorio."""


# Como se nombra cada forma de pago en el JSON que lee el modelo. Es la misma
# frase que ve el usuario en pantalla: si el texto de Gemini y la tarjeta de la
# UI llaman distinto a la misma opcion, la explicacion deja de servir.
def _nombre_forma(escenario: dict) -> str:
    mod = escenario["modalidad"]
    tarjeta = escenario["tarjeta"]
    if mod == "contado":
        return "de contado, con tu dinero disponible"
    if mod is None:
        return f"con {tarjeta}"
    if mod == "credito":
        return f"a credito revolvente con {tarjeta}"
    return f"a {mod.split('_')[0]} meses sin intereses con {tarjeta}"


def _opcion_para_ia(e: dict) -> dict:
    """
    Una opcion con los campos ETIQUETADOS.

    No se le pasa el escenario crudo a proposito: alli `holgura_despues` vale
    dos cosas distintas —efectivo restante en el contado, linea de credito libre
    en las tarjetas— y un modelo que lee las dos como el mismo campo acaba
    diciendo que la tarjeta "te deja mas dinero" que pagar de contado.
    """
    contado = e["modalidad"] == "contado"
    return {
        "forma": _nombre_forma(e),
        "modalidad": e["modalidad"],
        "tarjeta": e["tarjeta"],
        "viable": e["viable"],
        "motivo_no_viable": e["motivo"],
        "pago_mensual": e["pago_mensual"],
        "costo_total": e["costo_total"],
        "sale_de": "tu dinero disponible" if contado else "tu linea de credito",
        "te_queda": {
            "concepto": "dinero disponible" if contado else "linea de credito libre",
            "monto": e["holgura_despues"],
        },
        "score_despues": e["score_despues"],
        "cambio_en_score": e["delta"],
    }


class IAService:

    def __init__(self, tarjeta_service: TarjetaService, motor_service: MotorService,
                 categoria_service: CategoriaService):
        self.tarjetas = tarjeta_service
        self.motor = motor_service
        # Para el analisis: la categoria que elige el modelo tiene que salir del
        # catalogo real, no de su imaginacion. Es la clave que despues prellena
        # el formulario de registro del movimiento.
        self.categorias = categoria_service

    # =================================================================
    # 1. EXTRACCION DE ESTADO DE CUENTA
    # =================================================================

    def extraer_estado_de_cuenta(
        self, usuario_id: int, tarjeta_id: str, pdf: bytes,
        content_type: str | None = None, modo: ModoPago = "minimo",
    ) -> ExtraccionResponse:
        """
        Lee el PDF y devuelve los terminos listos para prellenar el formulario.

        NO PERSISTE NADA. El usuario revisa lo leido y guarda con PATCH
        /tarjetas/{id} si esta de acuerdo; los planes a meses van despues por
        POST /msi. Esa separacion es deliberada: lo que dice un modelo no entra
        a la base sin que alguien lo confirme.
        """
        # Primero la tarjeta: un id que no existe o que es de otro se responde
        # 404 antes de gastar una llamada a Gemini.
        tarjeta = self.tarjetas.obtener(usuario_id, tarjeta_id)

        self._validar_pdf(pdf, content_type)

        crudo = gemini.generar(
            [types.Part.from_bytes(data=pdf, mime_type="application/pdf")],
            PROMPT_EXTRACCION,
            EstadoDeCuentaIA,
        )

        return ExtraccionResponse.model_validate(
            mapear(crudo, banco_tarjeta=tarjeta.banco, modo=modo)
        )

    @staticmethod
    def _validar_pdf(pdf: bytes, content_type: str | None) -> None:
        """
        Un archivo que no sirve es culpa de lo que se subio, no del servicio:
        sale 422 con un mensaje que dice que hacer, no 503.
        """
        if content_type and content_type.split(";")[0].strip() != "application/pdf":
            raise ReglaDeNegocioViolada("El archivo debe ser un PDF")
        if not pdf.startswith(b"%PDF-"):
            # El content-type lo pone el cliente y se puede mentir; los primeros
            # cinco bytes no.
            raise ReglaDeNegocioViolada("El archivo debe ser un PDF")
        if len(pdf) > MAX_BYTES:
            raise ReglaDeNegocioViolada(
                "El PDF pesa mas de 15 MB. Sube solo las paginas del resumen"
            )
        if b"/Encrypt" in pdf:
            # Los estados de cuenta mexicanos suelen venir protegidos con el
            # RFC. Descifrarlos aqui exigiria pedir esa contrasena y guardarla
            # el tiempo de la peticion: se prefiere no tocarla.
            raise ReglaDeNegocioViolada(
                "El PDF esta protegido con contrasena. Abrelo, guardalo sin "
                "proteccion y vuelve a subirlo, o captura los datos a mano"
            )

    # =================================================================
    # 2. EXPLICACION DE LA PRIORIDAD DE DEUDA
    # =================================================================

    def explicar_prioridad(self, usuario_id: int) -> ExplicacionDeudaResponse:
        """
        Cuenta en espanol llano el ranking de GET /deuda/prioridad.

        El ranking se recalcula aqui adentro en vez de recibirlo en el cuerpo.
        Antes el frontend subia el `DeudaResponse` entero para que se lo
        explicaran, lo que ademas de gastar red dejaba que el cliente decidiera
        sobre que numeros se redacta. Ahora manda una peticion sin cuerpo.
        """
        ranking = self.motor.priorizar(usuario_id)

        # El esquema que se le exige al modelo es el MISMO DTO que devuelve el
        # endpoint, porque hoy son 1:1. Si algun dia el contrato gana un campo
        # derivado, hay que separarlos: no se le puede pedir a Gemini un dato
        # que no redacta el.
        crudo = gemini.generar(
            [types.Part.from_text(text="JSON del motor:\n" + _json(ranking))],
            PROMPT_PRIORIDAD,
            ExplicacionDeudaResponse,
        )

        try:
            return ExplicacionDeudaResponse.model_validate(crudo)
        except Exception as e:
            # El modelo contesto JSON, pero no el que se le pidio. Es el mismo
            # tipo de fallo que un 503: la IA no sirvio esta vez.
            log.warning("Gemini devolvio una explicacion con forma inesperada: %s", e)
            raise ServicioIANoDisponible(
                "Gemini no devolvio la explicacion en el formato esperado"
            ) from e


    # =================================================================
    # 3. ANALISIS PROFUNDO DE UNA COMPRA
    # =================================================================

    def analizar_compra(self, usuario_id: int,
                        req: SimulacionRequest) -> AnalisisCompraResponse:
        """
        Cuenta en espanol llano por que gana la forma de pago que gano, y si
        la compra en si es buena idea.

        RECIBE LA MISMA PETICION QUE EL SIMULADOR, no sus resultados: la
        simulacion se rehace aqui adentro. Es la misma decision que en
        explicar_prioridad — si el cliente subiera los escenarios, seria el
        cliente quien elige sobre que numeros se redacta, y bastaria con
        mandar una lista recortada para conseguir la explicacion que uno
        quiera.

        Al modelo solo le llega LA MEJOR OPCION DE CADA TARJETA mas el contado.
        Mandarle las veinte filas de la simulacion no da mejor prosa: da
        comparativas entre dos plazos de la misma tarjeta, que a nadie le
        importan.
        """
        resultado = self.motor.simular(
            usuario_id, req.monto, req.plazos,
            opciones=[o.model_dump() for o in req.tarjetas]
            if req.tarjetas is not None else None,
            incluir_contado=req.incluir_contado,
        )

        catalogo = {c.clave: c.nombre for c in self.categorias.listar()["data"]}
        crudo = gemini.generar(
            [types.Part.from_text(
                text="JSON del motor:\n" + _json(
                    _payload_analisis(resultado, req, list(catalogo))
                )
            )],
            PROMPT_ANALISIS,
            AnalisisCompraIA,
        )

        try:
            redactado = AnalisisCompraIA.model_validate(crudo)
        except Exception as e:
            log.warning("Gemini devolvio un analisis con forma inesperada: %s", e)
            raise ServicioIANoDisponible(
                "Gemini no devolvio el analisis en el formato esperado"
            ) from e

        clave, confianza = _categoria_valida(
            redactado.categoria, catalogo, redactado.confianza
        )

        return AnalisisCompraResponse(
            titular=redactado.titular,
            explicacion=redactado.explicacion,
            comparativas=redactado.comparativas,
            # La reflexion solo tiene sentido cuando el MOTOR vio algo. Si el
            # veredicto es "conviene" se descarta aunque el modelo la haya
            # escrito: preguntarle a alguien si de verdad necesita algo que su
            # dinero aguanta sin problema es moralizar, no ayudar.
            reflexion=(redactado.reflexion
                       if resultado["veredicto"] != "conviene" else None),
            riesgos=redactado.riesgos,
            confianza=confianza,
            veredicto=resultado["veredicto"],
            razones_veredicto=resultado["razones_veredicto"],
            categoria=clave,
            categoria_nombre=catalogo[clave],
        )


def _mejores_opciones(escenarios: list[dict]) -> list[dict]:
    """
    La primera fila de cada tarjeta (y del contado).

    Como `simular_compra` ordena viables primero, la primera fila de una tarjeta
    es su mejor opcion si tiene alguna, y si no, la inviable con su motivo. Las
    inviables se conservan: que el efectivo NO alcance es justo el dato que
    explica por que gana una tarjeta.
    """
    vistos: set = set()
    mejores = []
    for e in escenarios:
        if e["tarjeta_id"] in vistos:
            continue
        vistos.add(e["tarjeta_id"])
        mejores.append(e)
    return mejores


def _payload_analisis(resultado: dict, req: SimulacionRequest,
                      categorias: list[str]) -> dict:
    """Lo unico que ve Gemini. Todo numero de aqui lo produjo el motor."""
    recomendado = resultado["recomendado"]
    return {
        "compra": {
            "descripcion": req.descripcion,
            "monto": resultado["monto"],
        },
        "recomendada": _opcion_para_ia(recomendado) if recomendado else None,
        "opciones": [_opcion_para_ia(e)
                     for e in _mejores_opciones(resultado["escenarios"])],
        "situacion": {
            "score_actual": resultado["score_actual"],
            "veredicto": resultado["veredicto"],
            "razones": resultado["razones_veredicto"],
            "metricas": resultado["metricas"],
        },
        "categorias_validas": categorias,
    }


def _categoria_valida(clave: str, catalogo: dict[str, str],
                      confianza: str) -> tuple[str, str]:
    """
    La clave que dijo el modelo, si existe en el catalogo.

    Cuando no existe no se tira el analisis entero por un campo: se cae a
    "otros" —que el catalogo siempre trae— y se BAJA la confianza, para que la
    pantalla muestre que esa parte no es de fiar. El texto se salva; la persona
    corrige la categoria en el formulario, que es donde iba a confirmarla de
    todos modos.
    """
    normalizada = (clave or "").strip().lower()
    if normalizada in catalogo:
        return normalizada, confianza

    log.warning("Gemini eligio una categoria fuera del catalogo: %r", clave)
    respaldo = "otros" if "otros" in catalogo else next(iter(catalogo))
    return respaldo, "baja"


def _json(datos) -> str:
    # default=str por si el motor mete un Decimal o una fecha: es un prompt, no
    # una respuesta de la API, y reventar aqui por serializacion seria absurdo.
    return json.dumps(datos, ensure_ascii=False, default=str)