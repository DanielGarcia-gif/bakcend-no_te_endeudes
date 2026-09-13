"""
Fila de la tabla `recurrentes` — DECLARATIVA.

Gastos fijos. Dos cambios de modelo respecto a SQLite:

(a) `frecuencia_meses` — antes la tabla solo tenia `dia_del_mes`, o sea que
    asumia mensual y punto. La luz bimestral, el predial anual, la tenencia y
    el seguro del coche NO eran representables:
      1 mensual | 2 bimestral | 3 trimestral | 6 semestral | 12 anual
    La FASE (que meses, los pares o los nones) sale de `fecha_inicio`.

(b) `es_variable` — para servicios cuyo monto cambia (luz, agua, gas). NO se
    modela como rango min/max: el rango real se DERIVA del historial via
    movimientos.recurrente_id (ver la vista v_recurrentes_historial). Guardar
    500-1000 no elimina la decision de que numero proyectar, solo la esconde.

    `es_variable` no guarda el monto: cambia el comportamiento de la app. En un
    recurrente fijo (Netflix $219) el monto es un hecho; en uno variable la app
    tiene que preguntar "de cuanto vino este mes?". Y ahi la confirmacion del
    usuario no es una decision de diseno: es la unica opcion, porque el monto
    no existe hasta que llega el recibo.

`monto` es el monto exacto cuando es_variable = 0, y la estimacion inicial
cuando es_variable = 1 (solo se usa mientras no haya historial).
"""

from dataclasses import dataclass

from app.core.conversion import a_bool, a_fecha_iso, a_float, a_instante_iso


@dataclass(frozen=True, slots=True)
class Recurrente:
    id: int
    usuario_id: int
    concepto: str
    monto: float
    es_variable: bool
    dia_del_mes: int
    frecuencia_meses: int            # 1 mensual, 2 bimestral, 12 anual...
    ajuste_mes_corto: str            # ultimo_dia | mes_siguiente
    categoria_id: int
    fecha_inicio: str                # 'YYYY-MM-DD' — define la FASE del ciclo
    fecha_fin: str | None
    activo: bool
    creado_en: str | None = None
    actualizado_en: str | None = None
    eliminado_en: str | None = None
    # Se rellenan cuando la fila viene de un JOIN con `categorias`.
    categoria_clave: str | None = None
    categoria_nombre: str | None = None

    @classmethod
    def desde_fila(cls, f: dict) -> "Recurrente":
        return cls(
            id=f["id"],
            usuario_id=f["usuario_id"],
            concepto=f["concepto"],
            monto=a_float(f["monto"]),
            es_variable=a_bool(f.get("es_variable", 0)),
            dia_del_mes=f["dia_del_mes"],
            frecuencia_meses=f.get("frecuencia_meses", 1),
            ajuste_mes_corto=f.get("ajuste_mes_corto", "ultimo_dia"),
            categoria_id=f["categoria_id"],
            fecha_inicio=a_fecha_iso(f["fecha_inicio"]),
            fecha_fin=a_fecha_iso(f.get("fecha_fin")),
            activo=a_bool(f.get("activo", 1)),
            creado_en=a_instante_iso(f.get("creado_en")),
            actualizado_en=a_instante_iso(f.get("actualizado_en")),
            eliminado_en=a_instante_iso(f.get("eliminado_en")),
            categoria_clave=f.get("categoria_clave"),
            categoria_nombre=f.get("categoria_nombre"),
        )

    @property
    def peso_mensual(self) -> float:
        """
        Cuanto PESA al mes, en promedio. Una luz de $900 bimestral pesa $450.

        Es la cifra correcta para "cuanto de mi ingreso se va en obligaciones"
        y la INCORRECTA para "me alcanza este mes". Usar un solo numero para
        las dos preguntas garantiza que una este mal.
        """
        return self.monto / self.frecuencia_meses