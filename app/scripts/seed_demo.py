"""
Siembra el usuario demo.

    python -m app.scripts.seed_demo

NO ES DATOS DE PRUEBA: ES EL GUION DEL PITCH. Cada cifra esta calibrada para
que el demo cuente una historia concreta:

    score base 80  (liquidez 63 · deuda 75 · utilizacion 92 · flujo 100)

    NU al 85% de utilizacion y 68% de tasa  -> la que hay que pagar primero
    BBVA sana con holgura                   -> la que gana la simulacion
    Santander de contraste

    laptop de $15,000 a [3, 6, 12] MSI      -> gana 12 MSI en BBVA, score 61
    BBVA le gana a Santander por holgura restante ($7,000 contra $5,500)

Si cambias cualquier numero, vuelve a correr el motor: los cuatro componentes
del score estan acoplados y mover uno mueve los otros.

Idempotente por borrado: elimina el demo anterior y lo vuelve a crear. Las FK
con ON DELETE CASCADE se llevan sus ingresos, tarjetas, recurrentes y
movimientos; los movimientos se borran a mano primero porque msi_vigentes los
referencia con RESTRICT.
"""

import random
from datetime import date, timedelta

from app.core.conversion import a_dinero, a_tasa
from app.domain.calendario import dia_efectivo, sumar_meses
from app.core.database import conectar_directo

EMAIL_DEMO = "demo@app.mx"

# bcrypt de "demo1234". Es un hash real: con el placeholder de antes
# ($2b$12$demo) el login del demo fallaba y solo servia POST /auth/demo.
HASH_DEMO = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyDPvS8VJ0ZHVe"

LIQUIDEZ = 19500.00

INGRESOS = [
    # concepto,    monto, frecuencia,  dia, dia2, ancla
    ("Nomina",     6000,  "quincenal", 15,  30,   None),
    ("Freelance",  2000,  "mensual",   20,  None, None),
]

# concepto, monto, dia, clave de categoria, frecuencia_meses, es_variable
RECURRENTES = [
    ("Renta",         4000, 1, "hogar",         1, False),
    ("Transporte",    1000, 3, "transporte",    1, False),
    ("Servicios",      800, 5, "servicios",     1, True),
    ("Suscripciones",  500, 8, "suscripciones", 1, False),
]

# banco, nombre, limite, saldo, tasa, minimo, corte, limite_pago, min_msi
TARJETAS = [
    ("BBVA",      "BBVA",      28000, 6000,  0.38,  600, 15,  5, 300),
    ("NU",        "NU",        15000, 12750, 0.68, 1275, 20, 10, 500),
    ("Santander", "Santander", 25000, 4500,  0.42,  450, 25, 15, 600),
]

# tarjeta, descripcion, mensual, meses_totales, meses_restantes
MSI = [
    ("BBVA",      "Celular", 833, 12, 7),
    ("Santander", "Vuelo",   600, 12, 5),
]

CATEGORIAS_GASTO = ["comida", "transporte", "entretenimiento", "compras", "salud"]


def _hace_meses(n: int) -> date:
    """La misma fecha del mes, n meses atras. Espejo de TIMESTAMPDIFF(MONTH)."""
    hoy = date.today()
    anio, mes = sumar_meses(hoy, -n)
    return dia_efectivo(anio, mes, hoy.day)


def _categorias(cur) -> dict[str, int]:
    cur.execute("SELECT clave, id FROM categorias")
    return {f["clave"]: f["id"] for f in cur.fetchall()}


def _borrar_demo(cur) -> None:
    """
    Los movimientos primero: msi_vigentes los referencia con ON DELETE RESTRICT,
    asi que borrar el usuario de golpe fallaria con el error 1451.
    """
    cur.execute("SELECT id FROM usuarios WHERE es_demo = 1")
    ids = [f["id"] for f in cur.fetchall()]
    for uid in ids:
        cur.execute("DELETE FROM msi_vigentes WHERE usuario_id = %s", (uid,))
        cur.execute("DELETE FROM movimientos WHERE usuario_id = %s", (uid,))
        cur.execute("DELETE FROM periodos_tarjeta WHERE usuario_id = %s", (uid,))
        cur.execute("DELETE FROM usuarios WHERE id = %s", (uid,))


def _movimientos_historicos(uid: int, categorias: dict, tarjeta_debito: int):
    """
    90 dias de gastos sueltos, calibrados a unos $2,800 al mes.

    random.seed(42) fija la serie: el demo tiene que dar el mismo score cada vez
    que se siembra, o los numeros del pitch dejan de cuadrar.

    Todos van con medio='debito'. Antes el medio no existia como columna y estos
    movimientos eran ambiguos —efectivo o debito, no se sabia—, que es
    exactamente lo que el modelo nuevo elimina.
    """
    random.seed(42)
    filas = []
    for dias_atras in range(90, 0, -1):
        fecha = date.today() - timedelta(days=dias_atras)
        for _ in range(random.choice([0, 0, 1, 1])):
            clave = random.choice(CATEGORIAS_GASTO)
            filas.append((
                # El rango esta calibrado para dar los ~$2,650/mes de variables
                # que documenta el briefing, y con eso los componentes exactos
                # del pitch (63 · 75 · 92 · 100). Con el rango anterior salian
                # $2,487 y los componentes se iban a 64 · 76: el seed y el
                # fixture de tests/test_motor.py, que usa 2650 fijo, llevaban
                # tiempo descalibrados entre si sin que se notara.
                uid, "gasto", "debito", a_dinero(random.uniform(65, 340)),
                categorias[clave], "Gasto cotidiano", fecha, None,
            ))
    return filas


def sembrar(cx) -> int:
    """Crea el demo y devuelve su usuario_id. No hace commit."""
    with cx.cursor() as cur:
        categorias = _categorias(cur)
        _borrar_demo(cur)

        cur.execute(
            "INSERT INTO usuarios (nombre, email, password_hash, saldo_disponible, es_demo)"
            " VALUES (%s, %s, %s, %s, 1)",
            ("Ana Demo", EMAIL_DEMO, HASH_DEMO, a_dinero(LIQUIDEZ)),
        )
        uid = cur.lastrowid

        for concepto, monto, frecuencia, dia, dia2, ancla in INGRESOS:
            cur.execute(
                "INSERT INTO ingresos"
                " (usuario_id, concepto, monto, frecuencia, dia_pago, dia_pago_2, fecha_ancla)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (uid, concepto, a_dinero(monto), frecuencia, dia, dia2, ancla),
            )

        # fecha_inicio en el pasado y en enero: hace que los mensuales caigan
        # todos los meses. Es la columna que define la FASE del ciclo.
        inicio = date.today().replace(month=1, day=1) - timedelta(days=365)
        for concepto, monto, dia, clave, frecuencia, variable in RECURRENTES:
            cur.execute(
                "INSERT INTO recurrentes"
                " (usuario_id, concepto, monto, es_variable, dia_del_mes,"
                "  frecuencia_meses, categoria_id, fecha_inicio)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (uid, concepto, a_dinero(monto), int(variable), dia,
                 frecuencia, categorias[clave], inicio),
            )

        ids_tarjeta = {}
        for banco, nombre, limite, saldo, tasa, minimo, corte, pago, min_msi in TARJETAS:
            cur.execute(
                "INSERT INTO tarjetas"
                " (usuario_id, banco, nombre, tipo, limite, saldo, tasa_anual,"
                "  pago_minimo, dia_corte, dia_limite_pago, monto_minimo_msi)"
                " VALUES (%s, %s, %s, 'credito', %s, %s, %s, %s, %s, %s, %s)",
                (uid, banco, nombre, a_dinero(limite), a_dinero(saldo), a_tasa(tasa),
                 a_dinero(minimo), corte, pago, a_dinero(min_msi)),
            )
            ids_tarjeta[nombre] = cur.lastrowid

        cur.execute(
            "INSERT INTO tarjetas (usuario_id, banco, nombre, tipo)"
            " VALUES (%s, 'BBVA', 'Debito BBVA', 'debito')",
            (uid,),
        )
        tarjeta_debito = cur.lastrowid

        # MSI declarados, sin movimiento_id: son compras anteriores a que Ana
        # usara la app. Inventarles un movimiento seria meter un hecho falso en
        # la bitacora.
        for nombre, descripcion, mensual, totales, restantes in MSI:
            # Aritmetica de MESES, no de dias. v_msi_calculado deriva los meses
            # restantes con TIMESTAMPDIFF(MONTH, fecha_inicio, CURDATE()), y
            # `hoy - 30*n dias` no da n meses completos: 150 dias son 4 meses y
            # medio, asi que el MSI de 7 restantes aparecia con 8 y movia un
            # punto del componente de deuda.
            meses_transcurridos = totales - restantes
            cur.execute(
                "INSERT INTO msi_vigentes"
                " (usuario_id, tarjeta_id, movimiento_id, descripcion, monto_total,"
                "  monto_mensual, meses_totales, meses_restantes, fecha_inicio)"
                " VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s)",
                (uid, ids_tarjeta[nombre], descripcion,
                 a_dinero(mensual * totales), a_dinero(mensual), totales, restantes,
                 _hace_meses(meses_transcurridos)),
            )

        cur.executemany(
            "INSERT INTO movimientos"
            " (usuario_id, tipo, medio, monto, categoria_id, descripcion, fecha, tarjeta_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            _movimientos_historicos(uid, categorias, tarjeta_debito),
        )
    return uid


def main() -> None:
    from app.core.config import settings
    from app.repositories.estado_repository import EstadoRepository

    cx = conectar_directo(database=settings.db_name)
    try:
        uid = sembrar(cx)
        cx.commit()

        estado = EstadoRepository(cx).armar(uid)
        from app.domain.motor import banda, calcular_score

        resultado = calcular_score(estado)
        nombre, _ = banda(resultado["score"])

        print(f"Demo sembrado. usuario_id={uid}  ({EMAIL_DEMO} / demo1234)")
        print(f"  liquidez        {estado['liquidez']:>12,.2f}")
        print(f"  ingreso mensual {estado['ingreso']['mensual']:>12,.2f}")
        print(f"  fijos           {estado['gastos']['fijos']:>12,.2f}")
        print(f"  variables prom  {estado['gastos']['variables_prom']:>12,.2f}")
        print(f"  tarjetas        {len(estado['tarjetas']):>12}")
        print(f"\n  SCORE {resultado['score']}  ({nombre})")
        print(f"  {resultado['componentes']}")
    except Exception:
        cx.rollback()
        raise
    finally:
        cx.close()


if __name__ == "__main__":
    main()