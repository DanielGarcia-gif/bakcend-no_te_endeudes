"""
Caso de uso: la bitacora. Registrar, listar y borrar movimientos.

Sustituye a GastoService. El cambio no es de nombre: es que gasto, pago e
ingreso dejaron de ser tres caminos distintos con reglas distintas y pasaron a
ser un solo recurso, porque los tres son el mismo hecho —dinero que se movio— y
comparten idempotencia, borrado que revierte y auditoria.

LA DOBLE DISCRIMINACION QUE SE ELIMINA

La version anterior decidia dos veces, en dos sitios, con dos criterios:

    el servicio      por  req.medio         ('debito' -> valida contra liquidez)
    el repositorio   por  tarjeta_id IS NULL ('no es None' -> escribe en tarjeta)

y `medio` ni siquiera se guardaba. Un gasto con medio='debito' y un tarjeta_id
ajeno se validaba contra la liquidez, se le reportaba al usuario como impacto en
liquidez, y terminaba sumandole el monto al saldo de la tarjeta de otro usuario.
Ahora `medio` es una columna, viaja hasta la base y ck_mov_coherencia valida la
combinacion en el motor.

EL ORDEN DE LAS OPERACIONES, y por que es ese:

    1. leer el estado
    2. validar reglas de negocio        <- 422 antes de tocar nada
    3. calcular el impacto sobre una COPIA
    4. escribir movimiento + saldos     <- misma transaccion
    5. responder con el impacto del paso 3

El impacto se mide antes de escribir, no despues, y no es un atajo: el
micro-momento es "asi te queda si haces esto", y calcularlo sobre el estado ya
escrito daria el mismo numero pero perderia la posibilidad de abortar en el
paso 2 sin efectos.
"""

from datetime import date

from app.core.exceptions import ReglaDeNegocioViolada
from app.domain import reglas
from app.domain.reglas import a_id_interno
from app.repositories.auditoria_repository import AuditoriaRepository
from app.repositories.categoria_repository import CategoriaRepository
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.msi_repository import MSIRepository
from app.schemas.comunes import coleccion
from app.schemas.movimientos import (
    Impacto,
    MovimientoCreate,
    MovimientoResponse,
    MovimientoResumen,
)
from app.services.motor_service import MotorService

# Que componente del score mueve cada cosa. El micro-momento muestra el
# componente, no el score global: un gasto chico mueve menos de un punto entero
# del score y decir "sigues en 80" parece que la app no hizo nada.
COMPONENTE_POR_MEDIO = {
    "efectivo": "liquidez",
    "debito": "liquidez",
    "credito": "utilizacion",
}
COMPONENTE_POR_TIPO = {"pago": "deuda", "ingreso": "liquidez"}


class MovimientoService:

    def __init__(
        self,
        movimiento_repository: MovimientoRepository,
        categoria_repository: CategoriaRepository,
        msi_repository: MSIRepository,
        auditoria_repository: AuditoriaRepository,
        motor_service: MotorService,
    ):
        self.movimientos = movimiento_repository
        self.categorias = categoria_repository
        self.msi = msi_repository
        self.auditoria = auditoria_repository
        self.motor = motor_service

    # =====================================================================
    # LECTURA
    # =====================================================================

    def listar(self, usuario_id: int, limite: int = 50, cursor: str | None = None,
               **filtros) -> dict:
        """
        Historial paginado por cursor.

        Se piden `limite + 1` filas para saber si hay mas SIN un COUNT aparte:
        el COUNT sobre una tabla que crece cuesta lo mismo que la consulta.
        """
        cursor_fecha, cursor_id = self._descomponer(cursor)

        categoria = filtros.pop("categoria", None)
        categoria_id = (self.categorias.resolver(categoria, obligatoria=False)
                        if categoria else None)

        filas = self.movimientos.listar(
            usuario_id,
            limite=limite + 1,
            categoria_id=categoria_id,
            tarjeta_id=a_id_interno(filtros.pop("tarjeta_id", None)),
            cursor_fecha=cursor_fecha,
            cursor_id=cursor_id,
            **filtros,
        )

        hay_mas = len(filas) > limite
        filas = filas[:limite]
        siguiente = f"{filas[-1].fecha}:{filas[-1].id}" if hay_mas and filas else None
        return coleccion([self._a_resumen(m) for m in filas], hay_mas, siguiente)

    def obtener(self, usuario_id: int, movimiento_id: str) -> MovimientoResumen:
        return self._a_resumen(
            self.movimientos.obtener(a_id_interno(movimiento_id), usuario_id)
        )

    # =====================================================================
    # ESCRITURA
    # =====================================================================

    def registrar(self, usuario_id: int, req: MovimientoCreate,
                  idempotency_key: str | None = None) -> MovimientoResponse:
        # 1. Idempotencia ANTES de nada. Un doble tap no debe ni leer el estado.
        if idempotency_key:
            previo = self.movimientos.buscar_por_idempotencia(usuario_id,
                                                              idempotency_key)
            if previo is not None:
                return MovimientoResponse(
                    movimiento=self._a_resumen(previo),
                    impacto=self._impacto_nulo(usuario_id),
                    repetido=True,
                )

        estado = self.motor.estado_de(usuario_id)
        tarjeta_id = a_id_interno(req.tarjeta_id)

        # 2. Reglas de negocio. 422 antes de tocar ningun saldo.
        self._validar(estado, req)

        categoria_id = self.categorias.resolver(
            req.categoria, obligatoria=(req.tipo == "gasto")
        )

        # 3. Impacto sobre una COPIA del estado. No escribe nada.
        impacto = self.motor.evaluar_accion(estado, self._accion(req))

        # 4. Escritura. Movimiento y saldos, misma transaccion.
        movimiento_id = self.movimientos.registrar(
            usuario_id=usuario_id,
            tipo=req.tipo,
            medio=req.medio,
            monto=req.monto,
            fecha=req.fecha,
            categoria_id=categoria_id,
            descripcion=req.descripcion,
            tarjeta_id=tarjeta_id,
            ingreso_id=a_id_interno(req.ingreso_id),
            recurrente_id=a_id_interno(req.recurrente_id),
            idempotency_key=idempotency_key,
        )

        # La compra y su plan a meses nacen juntos. Antes vivian en universos
        # separados y por eso el saldo de una tarjeta y la suma de sus MSI no
        # cuadraban: habia MSI sin compra y compras a meses sin MSI.
        if req.msi is not None:
            self.msi.crear_ligado(
                usuario_id=usuario_id,
                tarjeta_id=tarjeta_id,
                movimiento_id=movimiento_id,
                monto_total=req.monto,
                meses=req.msi.meses,
                fecha_inicio=req.fecha,
                descripcion=req.msi.descripcion or req.descripcion,
                monto_mensual=req.msi.monto_mensual,
            )

        return MovimientoResponse(
            movimiento=self._a_resumen(
                self.movimientos.obtener(movimiento_id, usuario_id)
            ),
            impacto=self._a_impacto(impacto, req),
            repetido=False,
        )

    def eliminar(self, usuario_id: int, movimiento_id: str, motivo: str) -> None:
        """
        Borrado logico que revierte su efecto sobre los saldos.

        Si la compra tenia plan a meses, se borra tambien: sin eso,
        fk_msi_movimiento (RESTRICT) bloquearia la operacion — y con razon, un
        plan colgando de una compra que ya no existe seguiria contando como
        obligacion mensual para siempre.
        """
        interno = a_id_interno(movimiento_id)
        self.msi.eliminar_por_movimiento(interno, usuario_id)
        anterior = self.movimientos.eliminar_logico(interno, usuario_id, motivo)

        self.auditoria.registrar(
            tabla="movimientos",
            registro_id=interno,
            accion="eliminado",
            usuario_id=usuario_id,
            datos_antes={
                "tipo": anterior.tipo, "medio": anterior.medio,
                "monto": anterior.monto, "fecha": anterior.fecha,
                "tarjeta_id": anterior.tarjeta_id,
            },
            origen="api:DELETE /movimientos",
        )

    # =====================================================================
    # INTERNOS
    # =====================================================================

    def _validar(self, estado: dict, req: MovimientoCreate) -> None:
        error = reglas.validar_fecha(req.fecha)
        if error:
            raise ReglaDeNegocioViolada(error)

        if req.tipo == "gasto":
            error = reglas.validar_gasto(estado, req)
        elif req.tipo == "pago":
            reglas.tarjeta_o_404(estado, req.tarjeta_id)
            error = reglas.validar_pago(estado, req.tarjeta_id, req.monto)
        else:
            error = None

        if error:
            raise ReglaDeNegocioViolada(error)

    def _accion(self, req: MovimientoCreate) -> dict:
        """Traduce el request al vocabulario que entiende el motor."""
        if req.tipo == "pago":
            return {"tipo": "pago", "monto": req.monto, "tarjeta_id": req.tarjeta_id}
        if req.tipo == "ingreso":
            # El motor no tiene accion de ingreso: se modela como el negativo de
            # un gasto en efectivo, que sobre la liquidez es exactamente lo mismo.
            return {"tipo": "gasto", "medio": "debito", "monto": -req.monto}
        if req.msi is not None:
            return {"tipo": "compra", "modalidad": f"{req.msi.meses}_msi",
                    "monto": req.monto, "tarjeta_id": req.tarjeta_id}
        return {"tipo": "gasto", "medio": req.medio, "monto": req.monto,
                "tarjeta_id": req.tarjeta_id}

    def _a_impacto(self, impacto: dict, req: MovimientoCreate) -> Impacto:
        componente = COMPONENTE_POR_TIPO.get(req.tipo) or COMPONENTE_POR_MEDIO[req.medio]
        return Impacto(
            score_antes=impacto["score_antes_exacto"],
            score_despues=impacto["score_despues_exacto"],
            componente_afectado=componente,
            componente_antes=impacto["desglose_antes"][componente],
            componente_despues=impacto["desglose"][componente],
        )

    def _impacto_nulo(self, usuario_id: int) -> Impacto:
        """
        Para una peticion resuelta por idempotencia: no hubo cambio, porque el
        movimiento ya existia. Devolver el impacto original seria mentir — ese
        efecto ya esta en el saldo actual.
        """
        actual = self.motor.score_de(usuario_id)
        return Impacto(
            score_antes=actual["score_exacto"],
            score_despues=actual["score_exacto"],
            componente_afectado="liquidez",
            componente_antes=actual["componentes"]["liquidez"],
            componente_despues=actual["componentes"]["liquidez"],
        )

    @staticmethod
    def _descomponer(cursor: str | None) -> tuple[str | None, int | None]:
        """El cursor es 'YYYY-MM-DD:id'. Uno corrupto se ignora, no revienta."""
        if not cursor or ":" not in cursor:
            return None, None
        fecha, _, ident = cursor.rpartition(":")
        try:
            return fecha, int(ident)
        except ValueError:
            return None, None

    @staticmethod
    def _a_resumen(m) -> MovimientoResumen:
        return MovimientoResumen(
            id=str(m.id),
            tipo=m.tipo,
            medio=m.medio,
            monto=m.monto,
            fecha=m.fecha,
            categoria=m.categoria_clave,
            categoria_nombre=m.categoria_nombre,
            descripcion=m.descripcion,
            tarjeta_id=str(m.tarjeta_id) if m.tarjeta_id else None,
            tarjeta_nombre=m.tarjeta_nombre,
            periodo_id=str(m.periodo_id) if m.periodo_id else None,
            ingreso_id=str(m.ingreso_id) if m.ingreso_id else None,
            recurrente_id=str(m.recurrente_id) if m.recurrente_id else None,
        )