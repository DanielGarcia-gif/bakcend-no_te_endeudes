"""
Casos de uso de tarjetas, planes a meses y periodos de corte.

Los tres viven juntos porque son el mismo agregado visto desde tres angulos: la
tarjeta es el estado de hoy, el periodo es la obligacion fechada, y el MSI es el
compromiso a futuro. Separarlos en tres servicios obligaria a que se llamen
entre si para cualquier respuesta util.
"""

from datetime import date

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.reglas import a_id_interno
from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.msi_repository import MSIRepository
from app.repositories.periodo_repository import PeriodoRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.schemas.comunes import coleccion
from app.schemas.tarjetas import (
    MSICreate,
    MSIResumen,
    PagoPendiente,
    PeriodoCreate,
    PeriodoResumen,
    TarjetaCreate,
    TarjetaResumen,
    TarjetaUpdate,
)
from app.services.motor_service import MotorService


class TarjetaService:

    def __init__(self, tarjeta_repository: TarjetaRepository,
                 msi_repository: MSIRepository,
                 periodo_repository: PeriodoRepository,
                 auditoria_repository: AuditoriaRepository,
                 motor_service: MotorService):
        self.tarjetas = tarjeta_repository
        self.msi = msi_repository
        self.periodos = periodo_repository
        self.auditoria = auditoria_repository
        self.motor = motor_service

    # =====================================================================
    # TARJETAS
    # =====================================================================

    def listar(self, usuario_id: int) -> dict:
        tarjetas = self.tarjetas.listar(usuario_id)
        msi = self.msi.por_tarjeta(usuario_id)
        return coleccion([self._a_resumen(t, msi.get(t.id, [])) for t in tarjetas],
                         total=len(tarjetas))

    def obtener(self, usuario_id: int, tarjeta_id: str) -> TarjetaResumen:
        interno = a_id_interno(tarjeta_id)
        t = self.tarjetas.obtener(interno, usuario_id)
        return self._a_resumen(t, self.msi.por_tarjeta(usuario_id).get(interno, []))

    def crear(self, usuario_id: int, req: TarjetaCreate) -> TarjetaResumen:
        nueva = self.tarjetas.crear(usuario_id, req.banco, req.nombre, req.tipo)
        return self.obtener(usuario_id, str(nueva))

    def actualizar(self, usuario_id: int, tarjeta_id: str,
                   req: TarjetaUpdate) -> TarjetaResumen:
        interno = a_id_interno(tarjeta_id)
        antes = self.tarjetas.obtener(interno, usuario_id)
        cambios = req.model_dump(exclude_unset=True)
        version = cambios.pop("version", None)

        # Solo si vienen los seis: validar un corte contra un limite de pago que
        # no se esta mandando compararia con lo que ya habia.
        if {"dia_corte", "dia_limite_pago", "limite", "saldo"} <= set(cambios):
            error = reglas.validar_terminos_tarjeta(
                cambios["dia_corte"], cambios["dia_limite_pago"],
                cambios["limite"], cambios["saldo"],
            )
            if error:
                raise ReglaDeNegocioViolada(error)

        actualizada = self.tarjetas.actualizar(interno, usuario_id, cambios, version)

        if {"limite", "saldo", "pago_minimo", "tasa_anual"} & set(cambios):
            self.auditoria.registrar(
                "tarjetas", interno, "actualizado", usuario_id,
                datos_antes={"limite": antes.limite, "saldo": antes.saldo,
                             "pago_minimo": antes.pago_minimo,
                             "tasa_anual": antes.tasa_anual},
                datos_despues={k: v for k, v in cambios.items()},
                origen="api:PATCH /tarjetas",
            )
        return self._a_resumen(
            actualizada, self.msi.por_tarjeta(usuario_id).get(interno, [])
        )

    def eliminar(self, usuario_id: int, tarjeta_id: str) -> None:
        interno = a_id_interno(tarjeta_id)
        antes = self.tarjetas.obtener(interno, usuario_id)
        self.tarjetas.eliminar_logico(interno, usuario_id)
        self.auditoria.registrar(
            "tarjetas", interno, "eliminado", usuario_id,
            datos_antes={"banco": antes.banco, "nombre": antes.nombre,
                         "saldo": antes.saldo},
            origen="api:DELETE /tarjetas",
        )

    # =====================================================================
    # MSI
    # =====================================================================

    def listar_msi(self, usuario_id: int) -> dict:
        planes = self.msi.listar(usuario_id, solo_vigentes=True)
        return coleccion([self._a_msi(m) for m in planes], total=len(planes))

    def crear_msi(self, usuario_id: int, req: MSICreate) -> MSIResumen:
        """
        Un plan capturado de un estado de cuenta, sin compra en la app.

        Para una compra NUEVA se manda el bloque `msi` dentro de
        POST /movimientos: asi la compra y su plan nacen en la misma transaccion
        y el saldo de la tarjeta sube por el total en el mismo momento.
        """
        interno_tarjeta = a_id_interno(req.tarjeta_id)
        self.tarjetas.obtener(interno_tarjeta, usuario_id)   # 404 si no es suya

        if req.meses_restantes > req.meses_totales:
            raise ReglaDeNegocioViolada(
                "Los meses restantes no pueden superar los meses totales."
            )

        nuevo = self.msi.crear_declarado(
            usuario_id=usuario_id, tarjeta_id=interno_tarjeta,
            monto_mensual=req.monto_mensual, meses_totales=req.meses_totales,
            meses_restantes=req.meses_restantes, fecha_inicio=req.fecha_inicio,
            descripcion=req.descripcion, monto_total=req.monto_total,
        )
        return self._a_msi(self.msi.obtener(nuevo, usuario_id))

    def eliminar_msi(self, usuario_id: int, msi_id: str) -> None:
        self.msi.eliminar_logico(a_id_interno(msi_id), usuario_id)

    # =====================================================================
    # PERIODOS
    # =====================================================================

    def listar_periodos(self, usuario_id: int, tarjeta_id: str) -> dict:
        interno = a_id_interno(tarjeta_id)
        self.tarjetas.obtener(interno, usuario_id)
        periodos = self.periodos.listar(interno, usuario_id)
        return coleccion([self._a_periodo(p) for p in periodos], total=len(periodos))

    def abrir_periodo(self, usuario_id: int, tarjeta_id: str,
                      req: PeriodoCreate) -> PeriodoResumen:
        interno = a_id_interno(tarjeta_id)
        tarjeta = self.tarjetas.obtener(interno, usuario_id)
        if not tarjeta.es_credito:
            raise ReglaDeNegocioViolada("Solo una tarjeta de credito tiene cortes.")

        nuevo = self.periodos.abrir(usuario_id, interno, req.fecha_inicio,
                                    req.fecha_corte, req.fecha_limite_pago)
        self._recalcular(usuario_id, interno, nuevo)
        return self._a_periodo(self.periodos.obtener(nuevo, usuario_id))

    def cerrar_periodo(self, usuario_id: int, tarjeta_id: str,
                       periodo_id: str) -> PeriodoResumen:
        """
        Congela las cifras del corte y adopta sus movimientos.

        Mientras esta abierto las cifras son proyectadas; al cerrar dejan de
        moverse, que es lo que permite decir "tu corte fue el 15 con $6,000"
        aunque el usuario siga gastando el 16.
        """
        interno_tarjeta = a_id_interno(tarjeta_id)
        interno_periodo = a_id_interno(periodo_id)
        self.tarjetas.obtener(interno_tarjeta, usuario_id)

        self._recalcular(usuario_id, interno_tarjeta, interno_periodo)
        self.periodos.cerrar(interno_periodo, usuario_id)

        periodo = self.periodos.obtener(interno_periodo, usuario_id)
        self.auditoria.registrar(
            "periodos_tarjeta", interno_periodo, "actualizado", usuario_id,
            datos_despues={"cerrado": True,
                           "saldo_al_corte": periodo.saldo_al_corte,
                           "pago_no_intereses": periodo.pago_no_intereses},
            origen="api:POST /tarjetas/{id}/periodos/{id}/cierre",
        )
        return self._a_periodo(periodo)

    def pagos_pendientes(self, usuario_id: int) -> dict:
        filas = self.periodos.pagos_pendientes(usuario_id)
        return coleccion([
            PagoPendiente(
                tarjeta_id=str(f["tarjeta_id"]), banco=f["banco"], tarjeta=f["tarjeta"],
                fecha_corte=f["fecha_corte"].isoformat(),
                fecha_limite_pago=f["fecha_limite_pago"].isoformat(),
                dias_restantes=int(f["dias_restantes"]),
                saldo_al_corte=float(f["saldo_al_corte"]),
                pago_minimo=float(f["pago_minimo"]),
                pago_no_intereses=float(f["pago_no_intereses"]),
                pagado=float(f["pagado"]),
                falta_para_no_intereses=float(f["falta_para_no_intereses"]),
                falta_para_no_mora=float(f["falta_para_no_mora"]),
            )
            for f in filas
        ], total=len(filas))

    def _recalcular(self, usuario_id: int, tarjeta_id: int, periodo_id: int) -> None:
        """
        Calcula las tres cifras del corte a partir de los movimientos del rango.

        `pago_no_intereses` = lo cargado menos lo que esta a meses. Esa resta es
        la que el usuario no hace y por la que acaba pagando tasa sobre un saldo
        que creia cubierto.
        """
        periodo = self.periodos.obtener(periodo_id, usuario_id)
        if periodo.cerrado:
            return

        cargos = self.periodos.cargos_del_rango(
            usuario_id, tarjeta_id, periodo.fecha_inicio, periodo.fecha_corte
        )
        tarjeta = self.tarjetas.obtener(tarjeta_id, usuario_id)

        saldo_al_corte = max(0.0, cargos["cargos"] - cargos["pagos"])
        msi_periodo = min(cargos["cargos_msi"], saldo_al_corte)
        self.periodos.actualizar_cifras(
            periodo_id, usuario_id,
            saldo_al_corte=saldo_al_corte,
            # ck_periodo_coherencia exige que no supere el saldo al corte.
            pago_minimo=min(tarjeta.pago_minimo or 0.0, saldo_al_corte),
            pago_no_intereses=saldo_al_corte - msi_periodo,
            msi_del_periodo=msi_periodo,
        )

    # =====================================================================
    # CONVERSION
    # =====================================================================

    @staticmethod
    def _a_resumen(t, msi: list) -> TarjetaResumen:
        return TarjetaResumen(
            id=str(t.id), banco=t.banco, nombre=t.nombre, tipo=t.tipo,
            activa=t.activa, limite=t.limite, saldo=t.saldo,
            disponible=t.disponible, tasa_anual=t.tasa_anual,
            pago_minimo=t.pago_minimo, dia_corte=t.dia_corte,
            dia_limite_pago=t.dia_limite_pago,
            monto_minimo_msi=t.monto_minimo_msi,
            msi=[TarjetaService._a_msi(m) for m in msi],
            requiere_terminos=not t.terminos_completos,
            version=t.version,
        )

    @staticmethod
    def _a_msi(m) -> MSIResumen:
        restantes = (m.meses_restantes_real if m.meses_restantes_real is not None
                     else m.meses_restantes)
        return MSIResumen(
            id=str(m.id), tarjeta_id=str(m.tarjeta_id), descripcion=m.descripcion,
            monto_total=m.monto_total, monto_mensual=m.monto_mensual,
            meses_totales=m.meses_totales, meses_restantes=restantes,
            saldo_pendiente=round(m.pendiente, 2), fecha_inicio=m.fecha_inicio,
            movimiento_id=str(m.movimiento_id) if m.movimiento_id else None,
        )

    @staticmethod
    def _a_periodo(p) -> PeriodoResumen:
        return PeriodoResumen(
            id=str(p.id), tarjeta_id=str(p.tarjeta_id),
            fecha_inicio=p.fecha_inicio, fecha_corte=p.fecha_corte,
            fecha_limite_pago=p.fecha_limite_pago,
            saldo_al_corte=p.saldo_al_corte, pago_minimo=p.pago_minimo,
            pago_no_intereses=p.pago_no_intereses,
            msi_del_periodo=p.msi_del_periodo, pagado=p.pagado,
            intereses_generados=p.intereses_generados, cerrado=p.cerrado,
            falta_para_no_intereses=round(p.falta_para_no_intereses, 2),
            falta_para_no_mora=round(p.falta_para_no_mora, 2),
        )