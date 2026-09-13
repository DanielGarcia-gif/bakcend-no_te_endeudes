"""
Fila de la tabla `periodos_tarjeta` — el corte.

Tabla nueva. Antes solo existian `dia_corte` y `dia_limite_pago` como numeros
sueltos. Pero en credito mexicano lo que determina si pagas intereses NO es el
saldo de hoy: es el saldo al corte. Sin esta tabla la app no puede decir la
frase mas util que puede decir:

    "tu corte fue el 15 con $6,000; paga eso antes del 5 y no generas intereses"

Tres cifras distintas que la gente confunde y que aqui quedan separadas:

  saldo_al_corte     lo que debias el dia del corte.
  pago_minimo        lo que el banco exige para no caer en mora. Deja de ser
                     columna estatica de `tarjetas` y pasa a ser un hecho de
                     cada periodo.
  pago_no_intereses  saldo_al_corte menos la parte en promocion a meses. Es el
                     numero que de verdad importa: pagando esto la tasa no corre.

Mientras `cerrado = 0` las cifras son proyectadas; al cerrar se congelan y los
movimientos del rango reciben su periodo_id.
"""

from dataclasses import dataclass

from app.core.conversion import a_bool, a_fecha_iso, a_float, a_instante_iso


@dataclass(frozen=True, slots=True)
class PeriodoTarjeta:
    id: int
    usuario_id: int
    tarjeta_id: int
    fecha_inicio: str          # dia siguiente al corte anterior
    fecha_corte: str           # cuando cierra
    fecha_limite_pago: str     # cuando vence
    saldo_al_corte: float
    pago_minimo: float
    pago_no_intereses: float
    msi_del_periodo: float
    pagado: float
    intereses_generados: float
    cerrado: bool
    creado_en: str | None = None
    actualizado_en: str | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "PeriodoTarjeta":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            tarjeta_id=f["tarjeta_id"],
            fecha_inicio=a_fecha_iso(f["fecha_inicio"]),
            fecha_corte=a_fecha_iso(f["fecha_corte"]),
            fecha_limite_pago=a_fecha_iso(f["fecha_limite_pago"]),
            saldo_al_corte=a_float(f["saldo_al_corte"]),
            pago_minimo=a_float(f["pago_minimo"]),
            pago_no_intereses=a_float(f["pago_no_intereses"]),
            msi_del_periodo=a_float(f["msi_del_periodo"]),
            pagado=a_float(f["pagado"]),
            intereses_generados=a_float(f["intereses_generados"]),
            cerrado=a_bool(f["cerrado"]),
            creado_en=a_instante_iso(f.get("creado_en")),
            actualizado_en=a_instante_iso(f.get("actualizado_en")),
        )

    @property
    def falta_para_no_intereses(self) -> float:
        return max(0.0, self.pago_no_intereses - self.pagado)

    @property
    def falta_para_no_mora(self) -> float:
        return max(0.0, self.pago_minimo - self.pagado)