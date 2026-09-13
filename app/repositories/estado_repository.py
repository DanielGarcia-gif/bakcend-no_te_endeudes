"""
armar_estado() — LA frontera de datos.

Construye el objeto `estado` que consume el motor. Esta es la unica funcion que
sabe simultaneamente de la base y de la forma que el motor espera: si algun dia
cambia la fuente de datos (Nessie, Belvo, open banking), se reescribe SOLO este
repositorio y el motor no se entera.

Esa invariante se acaba de cobrar su valor: la base paso de SQLite a MySQL, el
modelo gano periodos de corte, frecuencias no mensuales y MSI ligados a su
compra, y app/domain/motor/ no cambio una linea. Las claves del dict de salida
(`tasa`, `corte`, `limite_pago`, el id como string) se conservan tal cual por
eso mismo.

AQUI TERMINA Decimal. MySQL devuelve DECIMAL para todo lo que es dinero, y el
motor opera con divisiones, potencias fraccionarias y round(). `Decimal * float`
lanza TypeError, asi que un Decimal que se cuele mas alla de esta linea no
revienta aqui: revienta dentro de un calculo de intereses, tres capas mas
adentro. La conversion la hacen los desde_fila() de app/models/.

TRES CIFRAS QUE ANTES ERAN UNA:

  gastos.fijos        Amortizado por frecuencia. Una luz de $900 bimestral pesa
                      $450/mes. Sale de v_obligaciones_mensuales y alimenta el
                      score. Antes era SUM(monto) de todos los activos, que daba
                      por sentado que todo era mensual: un predial anual de
                      $8,000 contaba como $8,000 cada mes.

  compromisos         Monto COMPLETO, solo los que caen en la ventana. Esa misma
                      luz sale a $900 el mes que toca y no aparece el que no.
                      Alimenta la proyeccion de flujo a 30 dias.

  variables_prom      Gasto suelto, ya filtrado de credito, fijos y MSI.

Usar un solo numero para "cuanto pesa al mes" y "cuanto sale este mes"
garantiza que una de las dos preguntas este mal respondida.
"""

from datetime import date, timedelta

from app.domain.calendario import ocurrencias_ingreso
from app.repositories.ingreso_repository import IngresoRepository
from app.repositories.movimiento_repository import MovimientoRepository
from app.repositories.msi_repository import MSIRepository
from app.repositories.periodo_repository import PeriodoRepository
from app.repositories.recurrente_repository import RecurrenteRepository
from app.repositories.tarjeta_repository import TarjetaRepository
from app.repositories.usuario_repository import UsuarioRepository

DIAS_VENTANA = 30


class EstadoRepository:

    def __init__(self, cx):
        self.usuarios = UsuarioRepository(cx)
        self.ingresos = IngresoRepository(cx)
        self.recurrentes = RecurrenteRepository(cx)
        self.tarjetas = TarjetaRepository(cx)
        self.movimientos = MovimientoRepository(cx)
        self.msi = MSIRepository(cx)
        self.periodos = PeriodoRepository(cx)

    def armar(self, usuario_id: int) -> dict:
        """
        Devuelve el `estado` como dict, que es lo que el motor consume.

        No devuelve el modelo Pydantic a proposito: el motor esta portado tal
        cual y habla dicts. La conversion a DTO ocurre en los servicios.
        """
        usuario = self.usuarios.obtener(usuario_id)

        ingreso_mensual, programados = self._ingresos(usuario_id)
        fijos, compromisos = self._recurrentes(usuario_id)
        variables_prom = self.movimientos.gasto_variable_promedio(usuario_id)

        return {
            "liquidez": usuario.saldo_disponible,
            "ingreso": {"mensual": round(ingreso_mensual, 2)},
            "ingresos_programados": programados,
            "gastos": {"fijos": round(fijos, 2),
                       "variables_prom": round(variables_prom, 2)},
            "compromisos": compromisos,
            "tarjetas": self._tarjetas(usuario_id),
        }

    # --- piezas del estado --------------------------------------------------

    def _ingresos(self, usuario_id: int) -> tuple[float, list[dict]]:
        """
        Normaliza a mensual y coloca cada cobro en su fecha real.

        Las fechas ya no se leen de `dia_pago` a secas: las calcula
        app/domain/calendario.py, que distingue las dos familias de frecuencia
        y reancla el ciclo con el ultimo cobro confirmado. Antes un ingreso
        catorcenal se repartia en dos eventos al mes; son 26 al ano, y hay meses
        con tres.
        """
        fuentes = self.ingresos.listar(usuario_id, solo_activos=True)
        if not fuentes:
            return 0.0, []

        mensual = sum(f.monto_mensual for f in fuentes)
        ultimos = self.ingresos.ultimos_confirmados(usuario_id)

        hoy = date.today()
        hasta = hoy + timedelta(days=DIAS_VENTANA)
        programados: list[dict] = []

        for f in fuentes:
            ancla = date.fromisoformat(f.fecha_ancla) if f.fecha_ancla else None
            fechas = ocurrencias_ingreso(
                frecuencia=f.frecuencia,
                desde=hoy,
                hasta=hasta,
                dia_pago=f.dia_pago,
                dia_pago_2=f.dia_pago_2,
                fecha_ancla=ancla,
                ultimo_confirmado=ultimos.get(f.id),
                ajuste=f.ajuste_mes_corto,
            )
            for fecha in fechas:
                programados.append({
                    # El motor proyecta sobre dias del mes, no sobre fechas.
                    "dia": fecha.day,
                    "monto": round(f.monto, 2),
                    "concepto": f.concepto,
                })
        return mensual, programados

    def _recurrentes(self, usuario_id: int) -> tuple[float, list[dict]]:
        """
        Dos numeros distintos de la misma tabla. Ver el docstring del modulo.
        """
        fijos = self.recurrentes.peso_mensual(usuario_id)
        compromisos = [
            {
                "dia": r["dia_del_mes"],
                # monto_para_proyectar viene del historial en los variables y
                # cae al declarado si aun no hay recibos. Usa el MAXIMO reciente:
                # en una app que previene deuda, quedarse corto es el error caro.
                "monto": round(float(r["monto_para_proyectar"]), 2),
                "concepto": r["concepto"],
            }
            for r in self.recurrentes.del_mes(usuario_id)
        ]
        return fijos, compromisos

    def _tarjetas(self, usuario_id: int) -> list[dict]:
        """
        Solo credito activas y con terminos completos: una tarjeta sin limite
        ni tasa reventaria el motor con un None en una division.

        `disponible` NO se incluye: es derivado y lo calcula quien lo necesite.
        """
        tarjetas = self.tarjetas.listar_credito_activas(usuario_id)
        if not tarjetas:
            return []

        # Dos consultas para todas las tarjetas, en vez de dos por tarjeta.
        msi_por_tarjeta = self.msi.por_tarjeta(usuario_id)
        periodos = self.periodos.abiertos_por_tarjeta(usuario_id)

        salida = []
        for t in tarjetas:
            if not t.terminos_completos:
                continue
            periodo = periodos.get(t.id)
            salida.append({
                "id": str(t.id),
                "nombre": t.nombre,
                "limite": t.limite,
                "saldo": t.saldo,
                "tasa": t.tasa_anual,
                # El pago minimo del corte vigente es un hecho fechado; la
                # columna de `tarjetas` es una cache de lo que decia el ultimo
                # estado de cuenta. Se prefiere el periodo cuando existe.
                "pago_minimo": (periodo.pago_minimo if periodo and periodo.pago_minimo
                                else t.pago_minimo),
                "corte": t.dia_corte,
                "limite_pago": t.dia_limite_pago,
                "monto_minimo_msi": t.monto_minimo_msi or 0,
                "msi": [
                    {
                        "monto_mensual": m.monto_mensual,
                        # El derivado de la fecha, no el contador guardado.
                        "meses_restantes": (m.meses_restantes_real
                                            if m.meses_restantes_real is not None
                                            else m.meses_restantes),
                        "descripcion": m.descripcion,
                    }
                    for m in msi_por_tarjeta.get(t.id, [])
                ],
            })
        return salida