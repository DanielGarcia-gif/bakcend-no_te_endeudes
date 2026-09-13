"""
Casos de uso de las tablas DECLARATIVAS: ingresos, recurrentes y pendientes.

Los tres van juntos porque comparten el mismo patron y separarlos obligaria a
duplicarlo:

    declaracion  ->  el usuario confirma  ->  movimiento
                                                 |
                           FK de vuelta a su declaracion

Lo "esperado" NO se guarda. PendientesService lo deriva al vuelo cruzando las
declaraciones contra los movimientos que ya existen. Materializarlo obligaria a
un proceso que lo genere, a decidir que pasa con los que nadie confirma, y a
limpiar los que se generaron con datos que despues cambiaron.
"""

from datetime import date, timedelta

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain.calendario import ocurrencias_ingreso, ocurrencias_recurrente
from app.domain.reglas import a_id_interno
from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.categoria_repository import CategoriaRepository
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.schemas.comunes import coleccion
from app.schemas.declarativas import (
    ConfirmacionCreate,
    IngresoCreate,
    IngresoResumen,
    IngresoUpdate,
    Pendiente,
    PendientesResponse,
    RecurrenteCreate,
    RecurrenteHistorial,
    RecurrenteResumen,
    RecurrenteUpdate,
)
from app.services.motor_service import MotorService

# Ventana de la pantalla de pendientes. Coincide con la proyeccion de flujo a
# 30 dias del motor: lo que el usuario ve como pendiente es lo mismo que la
# grafica esta contando.
DIAS_PENDIENTES = 30


def _fecha(valor) -> date | None:
    if valor is None:
        return None
    return date.fromisoformat(valor) if isinstance(valor, str) else valor


# =====================================================================
# INGRESOS
# =====================================================================

class IngresoService:

    def __init__(self, ingreso_repository: IngresoRepository,
                 movimiento_repository: MovimientoRepository,
                 auditoria_repository: AuditoriaRepository,
                 motor_service: MotorService):
        self.ingresos = ingreso_repository
        self.movimientos = movimiento_repository
        self.auditoria = auditoria_repository
        self.motor = motor_service

    def listar(self, usuario_id: int) -> dict:
        ultimos = self.ingresos.ultimos_confirmados(usuario_id)
        fuentes = self.ingresos.listar(usuario_id, solo_activos=False)
        return coleccion([self._a_resumen(f, ultimos.get(f.id)) for f in fuentes],
                         total=len(fuentes))

    def obtener(self, usuario_id: int, ingreso_id: str) -> IngresoResumen:
        interno = a_id_interno(ingreso_id)
        fuente = self.ingresos.obtener(interno, usuario_id)
        return self._a_resumen(fuente, self.ingresos.ultimo_confirmado(interno, usuario_id))

    def crear(self, usuario_id: int, req: IngresoCreate) -> IngresoResumen:
        nuevo = self.ingresos.crear(
            usuario_id=usuario_id,
            concepto=req.concepto,
            monto=req.monto,
            frecuencia=req.frecuencia,
            dia_pago=req.dia_pago,
            dia_pago_2=req.dia_pago_2,
            fecha_ancla=req.fecha_ancla,
            ajuste_mes_corto=req.ajuste_mes_corto,
        )
        return self.obtener(usuario_id, str(nuevo))

    def actualizar(self, usuario_id: int, ingreso_id: str,
                   req: IngresoUpdate) -> IngresoResumen:
        interno = a_id_interno(ingreso_id)
        antes = self.ingresos.obtener(interno, usuario_id)
        cambios = req.model_dump(exclude_unset=True)

        self.ingresos.actualizar(interno, usuario_id, cambios)
        if "monto" in cambios:
            # Regla practica: fila de auditoria en todo cambio que toque dinero.
            self.auditoria.registrar(
                "ingresos", interno, "actualizado", usuario_id,
                datos_antes={"monto": antes.monto},
                datos_despues={"monto": cambios["monto"]},
                origen="api:PATCH /ingresos",
            )
        return self.obtener(usuario_id, ingreso_id)

    def eliminar(self, usuario_id: int, ingreso_id: str) -> None:
        interno = a_id_interno(ingreso_id)
        antes = self.ingresos.obtener(interno, usuario_id)
        self.ingresos.eliminar_logico(interno, usuario_id)
        self.auditoria.registrar(
            "ingresos", interno, "eliminado", usuario_id,
            datos_antes={"concepto": antes.concepto, "monto": antes.monto},
            origen="api:DELETE /ingresos",
        )

    def confirmar(self, usuario_id: int, ingreso_id: str, req: ConfirmacionCreate,
                  idempotency_key: str | None = None) -> dict:
        """
        El usuario confirma que el cobro ocurrio: se materializa el movimiento.

        Es lo que resincroniza el calendario con la realidad del banco — el
        proximo cobro se calcula desde aqui, no desde la fecha_ancla original.
        """
        interno = a_id_interno(ingreso_id)
        fuente = self.ingresos.obtener(interno, usuario_id)

        nuevo = self.movimientos.registrar(
            usuario_id=usuario_id,
            tipo="ingreso",
            medio=req.medio,
            monto=req.monto if req.monto is not None else fuente.monto,
            fecha=req.fecha or date.today().isoformat(),
            descripcion=req.descripcion or fuente.concepto,
            ingreso_id=interno,
            idempotency_key=idempotency_key,
        )
        return {"movimiento_id": str(nuevo),
                "score_actualizado": self.motor.score_simple(usuario_id)}

    def _a_resumen(self, f, ultimo) -> IngresoResumen:
        ultimo_fecha = _fecha(ultimo)
        proximo = None
        ocurrencias = ocurrencias_ingreso(
            frecuencia=f.frecuencia,
            desde=date.today(),
            hasta=date.today() + timedelta(days=70),
            dia_pago=f.dia_pago,
            dia_pago_2=f.dia_pago_2,
            fecha_ancla=_fecha(f.fecha_ancla),
            ultimo_confirmado=ultimo_fecha,
            ajuste=f.ajuste_mes_corto,
        )
        if ocurrencias:
            proximo = ocurrencias[0].isoformat()

        return IngresoResumen(
            id=str(f.id), concepto=f.concepto, monto=f.monto,
            frecuencia=f.frecuencia, dia_pago=f.dia_pago, dia_pago_2=f.dia_pago_2,
            fecha_ancla=f.fecha_ancla, ajuste_mes_corto=f.ajuste_mes_corto,
            activo=f.activo,
            monto_mensual=round(f.monto_mensual, 2),
            ultimo_cobro=ultimo_fecha.isoformat() if ultimo_fecha else None,
            proximo_cobro=proximo,
        )


# =====================================================================
# RECURRENTES
# =====================================================================

class RecurrenteService:

    def __init__(self, recurrente_repository: RecurrenteRepository,
                 categoria_repository: CategoriaRepository,
                 movimiento_repository: MovimientoRepository,
                 auditoria_repository: AuditoriaRepository,
                 motor_service: MotorService):
        self.recurrentes = recurrente_repository
        self.categorias = categoria_repository
        self.movimientos = movimiento_repository
        self.auditoria = auditoria_repository
        self.motor = motor_service

    def listar(self, usuario_id: int) -> dict:
        filas = self.recurrentes.listar(usuario_id, solo_activos=False)
        return coleccion([self._a_resumen(r) for r in filas], total=len(filas))

    def obtener(self, usuario_id: int, recurrente_id: str) -> RecurrenteResumen:
        return self._a_resumen(
            self.recurrentes.obtener(a_id_interno(recurrente_id), usuario_id)
        )

    def crear(self, usuario_id: int, req: RecurrenteCreate) -> RecurrenteResumen:
        nuevo = self.recurrentes.crear(
            usuario_id=usuario_id,
            concepto=req.concepto,
            monto=req.monto,
            dia_del_mes=req.dia_del_mes,
            categoria_id=self.categorias.resolver(req.categoria),
            fecha_inicio=req.fecha_inicio,
            es_variable=req.es_variable,
            frecuencia_meses=req.frecuencia_meses,
            ajuste_mes_corto=req.ajuste_mes_corto,
            fecha_fin=req.fecha_fin,
        )
        return self.obtener(usuario_id, str(nuevo))

    def actualizar(self, usuario_id: int, recurrente_id: str,
                   req: RecurrenteUpdate) -> RecurrenteResumen:
        interno = a_id_interno(recurrente_id)
        antes = self.recurrentes.obtener(interno, usuario_id)
        cambios = req.model_dump(exclude_unset=True)
        if "categoria" in cambios:
            cambios["categoria_id"] = self.categorias.resolver(cambios.pop("categoria"))

        self.recurrentes.actualizar(interno, usuario_id, cambios)
        if "monto" in cambios:
            self.auditoria.registrar(
                "recurrentes", interno, "actualizado", usuario_id,
                datos_antes={"monto": antes.monto},
                datos_despues={"monto": cambios["monto"]},
                origen="api:PATCH /recurrentes",
            )
        return self.obtener(usuario_id, recurrente_id)

    def eliminar(self, usuario_id: int, recurrente_id: str) -> None:
        interno = a_id_interno(recurrente_id)
        antes = self.recurrentes.obtener(interno, usuario_id)
        self.recurrentes.eliminar_logico(interno, usuario_id)
        self.auditoria.registrar(
            "recurrentes", interno, "eliminado", usuario_id,
            datos_antes={"concepto": antes.concepto, "monto": antes.monto},
            origen="api:DELETE /recurrentes",
        )

    def historial(self, usuario_id: int, recurrente_id: str) -> RecurrenteHistorial:
        """
        El rango REAL de un gasto variable. Sale de los ultimos 6 pagos, no de
        lo que el usuario recuerda: con tres recibos ya hay datos que le ganan a
        esa memoria.
        """
        interno = a_id_interno(recurrente_id)
        fila = self.recurrentes.historial(interno, usuario_id)
        if fila is None:
            self.recurrentes.obtener(interno, usuario_id)   # lanza 404 si no existe
        return RecurrenteHistorial(
            recurrente_id=str(fila["recurrente_id"]),
            concepto=fila["concepto"],
            es_variable=bool(fila["es_variable"]),
            monto_declarado=float(fila["monto_declarado"]),
            pagos_considerados=int(fila["pagos_considerados"] or 0),
            monto_min=float(fila["monto_min"]) if fila["monto_min"] is not None else None,
            monto_max=float(fila["monto_max"]) if fila["monto_max"] is not None else None,
            monto_promedio=(float(fila["monto_promedio"])
                            if fila["monto_promedio"] is not None else None),
            ultimo_pago=fila["ultimo_pago"].isoformat() if fila["ultimo_pago"] else None,
            monto_para_proyectar=float(fila["monto_para_proyectar"]),
        )

    def confirmar(self, usuario_id: int, recurrente_id: str, req: ConfirmacionCreate,
                  idempotency_key: str | None = None) -> dict:
        """
        El usuario confirma que pago ese gasto fijo.

        En un recurrente VARIABLE el monto es obligatorio, y eso no es una
        decision de diseno: el monto de la luz no existe hasta que llega el
        recibo, asi que no hay nada que dar por sentado.
        """
        interno = a_id_interno(recurrente_id)
        fuente = self.recurrentes.obtener(interno, usuario_id)

        if fuente.es_variable and req.monto is None:
            raise ReglaDeNegocioViolada(
                f"'{fuente.concepto}' es un gasto variable: indica de cuanto vino "
                "este periodo.",
                {"campo": "monto", "referencia": fuente.monto},
            )

        nuevo = self.movimientos.registrar(
            usuario_id=usuario_id,
            tipo="gasto",
            medio=req.medio,
            monto=req.monto if req.monto is not None else fuente.monto,
            fecha=req.fecha or date.today().isoformat(),
            # Hereda la categoria de su declaracion: ck_mov_categoria exige una,
            # y pedirsela otra vez al usuario seria preguntarle algo que ya dijo.
            categoria_id=fuente.categoria_id,
            descripcion=req.descripcion or fuente.concepto,
            recurrente_id=interno,
            idempotency_key=idempotency_key,
        )
        return {"movimiento_id": str(nuevo),
                "score_actualizado": self.motor.score_simple(usuario_id)}

    @staticmethod
    def _a_resumen(r) -> RecurrenteResumen:
        return RecurrenteResumen(
            id=str(r.id), concepto=r.concepto, monto=r.monto,
            categoria=r.categoria_clave, categoria_nombre=r.categoria_nombre,
            dia_del_mes=r.dia_del_mes, frecuencia_meses=r.frecuencia_meses,
            es_variable=r.es_variable, ajuste_mes_corto=r.ajuste_mes_corto,
            fecha_inicio=r.fecha_inicio, fecha_fin=r.fecha_fin, activo=r.activo,
            peso_mensual=round(r.peso_mensual, 2),
        )


# =====================================================================
# PENDIENTES
# =====================================================================

class PendientesService:
    """
    Lo que toca y aun no se ha confirmado.

    No lee ninguna tabla de pendientes porque no existe: cruza las declaraciones
    contra los movimientos que ya hay y devuelve la resta. Es la pantalla que
    hace visible el patron declaracion -> confirmacion.
    """

    def __init__(self, ingreso_repository: IngresoRepository,
                 recurrente_repository: RecurrenteRepository):
        self.ingresos = ingreso_repository
        self.recurrentes = recurrente_repository

    def listar(self, usuario_id: int, dias: int = DIAS_PENDIENTES) -> PendientesResponse:
        hoy = date.today()
        hasta = hoy + timedelta(days=dias)

        pendientes_ingreso = self._ingresos(usuario_id, hoy, hasta)
        pendientes_gasto = self._recurrentes(usuario_id, hoy, hasta)

        return PendientesResponse(
            ingresos=pendientes_ingreso,
            gastos=pendientes_gasto,
            total_por_cobrar=round(sum(p.monto_esperado for p in pendientes_ingreso), 2),
            total_por_pagar=round(sum(p.monto_esperado for p in pendientes_gasto), 2),
        )

    def _ingresos(self, usuario_id: int, hoy: date, hasta: date) -> list[Pendiente]:
        ultimos = self.ingresos.ultimos_confirmados(usuario_id)
        salida = []
        for f in self.ingresos.listar(usuario_id, solo_activos=True):
            ultimo = _fecha(ultimos.get(f.id))
            for fecha in ocurrencias_ingreso(
                frecuencia=f.frecuencia, desde=hoy, hasta=hasta,
                dia_pago=f.dia_pago, dia_pago_2=f.dia_pago_2,
                fecha_ancla=_fecha(f.fecha_ancla), ultimo_confirmado=ultimo,
                ajuste=f.ajuste_mes_corto,
            ):
                # Si ya se confirmo un cobro en esa fecha o despues, no esta
                # pendiente: el usuario ya lo registro.
                if ultimo is not None and ultimo >= fecha:
                    continue
                salida.append(Pendiente(
                    tipo="ingreso", origen_id=str(f.id), concepto=f.concepto,
                    fecha_esperada=fecha.isoformat(), monto_esperado=round(f.monto, 2),
                    dias_restantes=(fecha - hoy).days,
                ))
        return sorted(salida, key=lambda p: p.fecha_esperada)

    def _recurrentes(self, usuario_id: int, hoy: date, hasta: date) -> list[Pendiente]:
        ya_confirmados = self.recurrentes.confirmados_del_mes(usuario_id)
        salida = []
        for r in self.recurrentes.listar(usuario_id, solo_activos=True):
            if r.id in ya_confirmados:
                continue
            for fecha in ocurrencias_recurrente(
                dia_del_mes=r.dia_del_mes, fecha_inicio=_fecha(r.fecha_inicio),
                frecuencia_meses=r.frecuencia_meses, desde=hoy, hasta=hasta,
                fecha_fin=_fecha(r.fecha_fin), ajuste=r.ajuste_mes_corto,
            ):
                salida.append(Pendiente(
                    tipo="recurrente", origen_id=str(r.id), concepto=r.concepto,
                    fecha_esperada=fecha.isoformat(),
                    # Monto COMPLETO, no amortizado: la pregunta aqui es "me
                    # alcanza este mes", y la luz bimestral llega entera.
                    monto_esperado=round(r.monto, 2),
                    monto_incierto=r.es_variable,
                    categoria=r.categoria_clave,
                    dias_restantes=(fecha - hoy).days,
                ))
        return sorted(salida, key=lambda p: p.fecha_esperada)