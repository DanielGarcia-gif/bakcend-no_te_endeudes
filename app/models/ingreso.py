"""
Fila de la tabla `ingresos` — DECLARATIVA.

Fuentes de ingreso RECURRENTE. Un ingreso extraordinario (aguinaldo, un
freelance suelto, la venta de algo) NO vive aqui: va directo a `movimientos`
con tipo='ingreso' y sin ingreso_id. Si estuviera aqui, la proyeccion lo
trataria como capacidad mensual permanente y un aguinaldo de $15,000 haria
creer al sistema que el usuario gana eso cada mes, para siempre.

DOS FAMILIAS DE FRECUENCIA, dos representaciones distintas:

  Basada en dias        semanal (7), catorcenal (14)
                        Se define con `fecha_ancla`. NO se puede expresar con
                        dia del mes: catorcenal son 26 pagos al ano y en un mes
                        de 30 dias a veces caen dos y a veces tres.

  Basada en calendario  quincenal, mensual
                        Se define con `dia_pago` (+ dia_pago_2 en quincenal).
                        Quincenal en Mexico NO es "cada 15 dias": es dos veces
                        al mes, normalmente el 15 y el ultimo.

`fecha_ancla` sirve a las dos con papeles distintos: en semanal/catorcenal ES
la definicion; en quincenal/mensual es verificacion.

NO existe `ultimo_pago_confirmado`: se deriva de MAX(movimientos.fecha) con
ingreso_id = este. Cada confirmacion del usuario resincroniza el calendario con
la realidad del banco.
"""

from dataclasses import dataclass

from app.core.conversion import a_bool, a_fecha_iso, a_float, a_instante_iso
from app.domain.tipos import FACTOR_MENSUAL


@dataclass(frozen=True, slots=True)
class Ingreso:
    id: int
    usuario_id: int
    concepto: str
    monto: float
    frecuencia: str                  # semanal | catorcenal | quincenal | mensual
    dia_pago: int | None
    dia_pago_2: int | None
    fecha_ancla: str | None          # 'YYYY-MM-DD'
    # Que hacer cuando dia_pago no existe en el mes (31 de abril, 30 de febrero)
    ajuste_mes_corto: str = "ultimo_dia"
    activo: bool = True
    creado_en: str | None = None
    actualizado_en: str | None = None
    eliminado_en: str | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "Ingreso":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            concepto=f["concepto"],
            monto=a_float(f["monto"]),
            frecuencia=f["frecuencia"],
            dia_pago=f["dia_pago"],
            dia_pago_2=f["dia_pago_2"],
            fecha_ancla=a_fecha_iso(f.get("fecha_ancla")),
            ajuste_mes_corto=f.get("ajuste_mes_corto", "ultimo_dia"),
            activo=a_bool(f.get("activo", 1)),
            creado_en=a_instante_iso(f.get("creado_en")),
            actualizado_en=a_instante_iso(f.get("actualizado_en")),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
        )

    @property
    def monto_mensual(self) -> float:
        """
        Normalizado a mes. Derivado: nunca se guarda.

        semanal 52/12, catorcenal 26/12, quincenal x2, mensual x1.
        """
        return self.monto * FACTOR_MENSUAL[self.frecuencia]

    @property
    def por_calendario(self) -> bool:
        """True si el ciclo se define por dia del mes, no por fecha ancla."""
        return self.frecuencia in ("quincenal", "mensual")