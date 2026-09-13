"""
Filas de las tablas `tarjetas` y `msi_vigentes`.

Las de debito traen todos los campos de credito en None: la debito es una
etiqueta que apunta al saldo_disponible del usuario y NO entra al score.
ck_tarjetas_debito lo impone desde el motor de la base.

SOBRE MSI: una compra a meses ES un gasto, y ahora la tabla lo refleja con
`movimiento_id`. Antes vivian en universos separados —podias tener un MSI sin
compra registrada y una compra a meses sin su MSI— y por eso el saldo de una
tarjeta y la suma de sus MSI no cuadran en los datos viejos.

COMO SE REGISTRA UNA COMPRA A MSI (casi todos lo modelan mal):

  Una laptop de $12,000 a 12 MSI se debe COMPLETA desde el dia uno. El banco
  presto los doce mil. Entonces:
    - movimientos:              un gasto de 12,000.00, medio='credito'
    - tarjetas.saldo:           SUBE 12,000.00  (el TOTAL, no la mensualidad)
    - usuarios.saldo_disponible: NO se mueve. No salio dinero del bolsillo.
    - msi_vigentes:             monto_total 12,000 / mensual 1,000 / meses 12

  Los "$1,000 al mes" no son un cobro: son el permiso de pagarlo en 12 sin
  intereses. La utilizacion brinca por los 12,000 completos, y la utilizacion
  es 30% del score. Modelarlo como +1,000 al mes le diria al usuario que esta
  mucho menos endeudado de lo que esta.

  El dinero liquido solo se mueve al PAGAR la tarjeta (tipo='pago').

`monto_total` es la verdad; `monto_mensual` es informativo. $10,899/12 = 908.25
exacto, pero la mayoria de las compras no dan redondo y la ultima mensualidad
absorbe la diferencia: calcular la deuda como mensual * restantes arrastra
centavos hasta el final.
"""

from dataclasses import dataclass, field

from app.core.conversion import (
    a_bool, a_entero, a_fecha_iso, a_float, a_instante_iso,
)


@dataclass(frozen=True, slots=True)
class MSIVigente:
    id: int
    usuario_id: int
    tarjeta_id: int
    # NULL cuando el plan se capturo de un estado de cuenta y no de una compra
    # registrada en la app. uq_msi_movimiento impide que una compra genere dos.
    movimiento_id: int | None
    descripcion: str | None
    monto_total: float | None
    monto_mensual: float
    meses_totales: int
    meses_restantes: int
    fecha_inicio: str
    eliminado_en: str | None = None
    # Solo presente al leer desde la vista v_msi_calculado.
    meses_restantes_real: int | None = None
    saldo_msi_pendiente: float | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "MSIVigente":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            tarjeta_id=f["tarjeta_id"],
            movimiento_id=f.get("movimiento_id"),
            descripcion=f.get("descripcion"),
            monto_total=a_float(f.get("monto_total")),
            monto_mensual=a_float(f["monto_mensual"]),
            meses_totales=a_entero(f["meses_totales"]),
            # La vista renombra la columna guardada; la tabla no.
            meses_restantes=a_entero(
                f.get("meses_restantes", f.get("meses_restantes_guardado"))),
            fecha_inicio=a_fecha_iso(f["fecha_inicio"]),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
            # GREATEST(...) devuelve DECIMAL aunque cuente meses. Sin este
            # a_entero, el Decimal viaja hasta el calculo de intereses.
            meses_restantes_real=a_entero(f.get("meses_restantes_real")),
            saldo_msi_pendiente=a_float(f.get("saldo_msi_pendiente")),
        )

    @property
    def pendiente(self) -> float:
        """
        Lo que falta por pagar de este plan.

        Prefiere monto_total menos lo ya cubierto; cae a mensual * restantes
        solo si no hay total capturado. Ver el docstring del modulo.
        """
        restantes = (self.meses_restantes_real
                     if self.meses_restantes_real is not None
                     else self.meses_restantes)
        if self.monto_total is not None and self.meses_totales:
            pagados = self.meses_totales - restantes
            return max(0.0, self.monto_total - self.monto_mensual * pagados)
        return self.monto_mensual * restantes


@dataclass(frozen=True, slots=True)
class Tarjeta:
    id: int
    usuario_id: int
    banco: str
    nombre: str
    tipo: str                       # credito | debito
    limite: float | None
    saldo: float | None
    tasa_anual: float | None        # fraccion decimal: 38% -> 0.38
    # Estado DE HOY (cache). La obligacion real de cada corte vive en
    # periodos_tarjeta.pago_minimo, que es un hecho del periodo y no una
    # columna estatica capturada una vez del estado de cuenta.
    pago_minimo: float | None
    dia_corte: int | None
    dia_limite_pago: int | None
    monto_minimo_msi: float | None  # este SI es del banco
    activa: bool
    version: int = 0
    creado_en: str | None = None
    actualizado_en: str | None = None
    eliminado_en: str | None = None
    # Los plazos MSI NO viven aqui: los define el COMERCIO, no la tarjeta.
    msi: list[MSIVigente] = field(default_factory=list)

    @classmethod
    def desde_fila(cls, f: dict, msi: list[MSIVigente] | None = None) -> "Tarjeta":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            banco=f["banco"],
            nombre=f["nombre"],
            tipo=f["tipo"],
            limite=a_float(f["limite"]),
            saldo=a_float(f["saldo"]),
            tasa_anual=a_float(f["tasa_anual"]),
            pago_minimo=a_float(f["pago_minimo"]),
            dia_corte=f["dia_corte"],
            dia_limite_pago=f["dia_limite_pago"],
            monto_minimo_msi=a_float(f["monto_minimo_msi"]),
            activa=a_bool(f["activa"]),
            version=f.get("version", 0),
            creado_en=a_instante_iso(f.get("creado_en")),
            actualizado_en=a_instante_iso(f.get("actualizado_en")),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
            msi=msi or [],
        )

    @property
    def es_credito(self) -> bool:
        return self.tipo == "credito"

    @property
    def disponible(self) -> float | None:
        """Derivado. NUNCA se guarda en la base de datos."""
        if self.limite is None or self.saldo is None:
            return None
        return self.limite - self.saldo

    @property
    def terminos_completos(self) -> bool:
        """
        Una tarjeta de credito sin terminos no puede entrar al motor: le
        faltan los numeros con los que se calculan el score y la simulacion.
        """
        if not self.es_credito:
            return True
        return None not in (
            self.limite, self.saldo, self.tasa_anual,
            self.pago_minimo, self.dia_corte, self.dia_limite_pago,
        )