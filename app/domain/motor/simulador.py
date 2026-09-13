"""
Simulador de compra — la pantalla estrella.

SOLO LECTURA. No escribe nada, ni aqui ni en las capas de arriba: evaluar()
trabaja sobre copias del estado.

DOS CAMBIOS DE FONDO RESPECTO A LA PRIMERA VERSION

1. LOS PLAZOS SON POR TARJETA. Antes habia una sola lista de meses que se
   aplicaba a todas: la misma tienda daba magicamente 18 meses con las tres
   tarjetas del usuario. En la realidad la promocion la define el comercio
   PARA CADA banco. Ahora se reciben `opciones` —tarjeta + los meses que le
   ofrecen con ella— y `plazos` se conserva solo para las llamadas viejas.

2. EL ORDEN LO MANDA EL SCORE, no la preferencia de modalidad. Antes
   `_preferencia_modalidad` ponia cualquier MSI arriba del contado para todo
   monto >= $500, aunque el contado dejara mejor score. Eso era indefendible en
   cuanto alguien —o el analisis profundo— tuviera que explicar POR QUE gana la
   recomendada. Hoy la preferencia solo desempata: cuando dos formas de pagar
   dejan el mismo score, se prefiere la que no cobra intereses.
"""

from app.domain.motor.evaluacion import evaluar

# Meses que amortiza el motor para poner precio al revolvente. Es el mismo
# horizonte que usa evaluacion.py al subir el pago minimo: si aqui y alla no
# fuera el mismo numero, el costo mostrado no correspondaria al score calculado.
MESES_REVOLVENTE = 12


def _preferencia_modalidad(modalidad: str | None, monto: float) -> int:
    """
    DESEMPATE, no criterio principal.

    Solo se consulta cuando dos escenarios dejan el mismo score, y entonces:

    - el revolvente siempre pierde: es el unico que cobra intereses;
    - en compras chicas gana el contado, porque endeudarse por $300 es
      papeleo sin beneficio;
    - en compras grandes ganan los MSI, porque a igualdad de score protegen
      el efectivo, que es el colchon ante un imprevisto.
    """
    if not modalidad:
        return 3

    if modalidad == "credito":
        return 4

    if monto < 500:
        return 0 if modalidad == "contado" else 2

    if "_msi" in modalidad:
        return 0

    if modalidad == "contado":
        return 1

    return 3


def _costo_total(modalidad: str, monto: float, pago_mensual: float) -> float:
    """
    Lo que sale del bolsillo en total.

    Contado y MSI valen el monto pelado —los MSI en Mexico son 0%—; el
    revolvente vale las doce mensualidades que amortiza el motor. Sin esta
    cifra no hay forma de contrastar "18 meses" contra "revolver" en una frase.
    """
    if modalidad == "credito":
        return round(pago_mensual * MESES_REVOLVENTE, 2)
    return round(monto, 2)


def _escenario_contado(estado: dict, monto: float) -> dict:
    r = evaluar(estado, {"tipo": "compra", "monto": monto, "modalidad": "contado"})
    alcanza = estado["liquidez"] >= monto
    return {
        "modalidad": "contado", "tarjeta": None, "tarjeta_id": None,
        "disponible": estado["liquidez"],
        "holgura_despues": round(estado["liquidez"] - monto, 2),
        "pago_mensual": 0,
        "viable": alcanza,
        "motivo": None if alcanza else "Liquidez insuficiente",
        "score_despues": r["score_despues"], "delta": r["delta"],
        "costo_total": round(monto, 2),
        "mejor_de_tarjeta": False,
        "_exacto": r["score_despues_exacto"],
    }


def _escenarios_de_tarjeta(estado: dict, t: dict, monto: float,
                           plazos: list[int]) -> list[dict]:
    """Todas las formas de pagar `monto` con UNA tarjeta, con SUS plazos."""
    disponible = t["limite"] - t["saldo"]

    if disponible < monto:
        return [{
            "modalidad": None, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "holgura_despues": None, "pago_mensual": 0,
            "viable": False, "motivo": f"Disponible ${disponible:,.0f}, no alcanza",
            "score_despues": None, "delta": None,
            "costo_total": None, "mejor_de_tarjeta": False, "_exacto": -1.0,
        }]

    filas: list[dict] = []

    # El minimo para meses lo pone EL BANCO, no la tienda. Antes los plazos se
    # descartaban en silencio; ahora el usuario los eligio a proposito para esta
    # tarjeta y merece saber por que no aplican.
    minimo_msi = t.get("monto_minimo_msi", 0) or 0
    if plazos and monto < minimo_msi:
        filas.append({
            "modalidad": None, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "holgura_despues": None, "pago_mensual": 0,
            "viable": False,
            "motivo": f"Los meses con esta tarjeta piden minimo ${minimo_msi:,.0f}",
            "score_despues": None, "delta": None,
            "costo_total": None, "mejor_de_tarjeta": False, "_exacto": -1.0,
        })
        plazos = []

    for mod in ["credito"] + [f"{m}_msi" for m in plazos]:
        r = evaluar(estado, {"tipo": "compra", "monto": monto,
                             "tarjeta_id": t["id"], "modalidad": mod})
        if mod == "credito":
            tm = t["tasa"] / 12
            pago = monto * (tm / (1 - (1 + tm) ** -MESES_REVOLVENTE))
        else:
            pago = monto / int(mod.split("_")[0])

        filas.append({
            "modalidad": mod, "tarjeta": t["nombre"], "tarjeta_id": t["id"],
            "disponible": disponible, "pago_mensual": round(pago, 2),
            "viable": True, "motivo": None,
            "holgura_despues": round(disponible - monto, 2),
            "score_despues": r["score_despues"], "delta": r["delta"],
            "costo_total": _costo_total(mod, monto, pago),
            "mejor_de_tarjeta": False,
            "_exacto": r["score_despues_exacto"],
        })

    return filas


def simular_compra(estado: dict, monto: float, plazos: list[int] | None = None,
                   opciones: list[dict] | None = None,
                   incluir_contado: bool = True) -> list[dict]:
    """
    Evalua cada forma de pagar la compra y las devuelve ordenadas.

    `opciones` es la forma nueva: `[{"tarjeta_id": "bbva", "plazos": [3, 12]}]`.
    Cuando viene, define ademas QUE tarjetas entran — las que el usuario no puso
    sobre la mesa no se evaluan, porque en esa tienda no las va a usar.

    `plazos` es la forma vieja: una sola lista para todas las tarjetas. Se
    conserva para no romper a quien ya llamaba asi.
    """
    plazos = plazos or []
    escenarios: list[dict] = []

    if opciones is None:
        # Camino legado: todas las tarjetas del estado, con los mismos plazos.
        pares = [(t, plazos) for t in estado["tarjetas"]]
        incluir_contado = True
    else:
        por_id = {t["id"]: t for t in estado["tarjetas"]}
        pares = [
            (por_id[o["tarjeta_id"]], o.get("plazos") or [])
            for o in opciones if o["tarjeta_id"] in por_id
        ]

    if incluir_contado:
        escenarios.append(_escenario_contado(estado, monto))

    for tarjeta, plazos_tarjeta in pares:
        escenarios.extend(
            _escenarios_de_tarjeta(estado, tarjeta, monto, plazos_tarjeta)
        )

    # 1. Viables primero
    # 2. MEJOR SCORE — el criterio, no un desempate. Se ordena por el score
    #    exacto y no por el redondeado: dos opciones que muestran "61" pueden
    #    no valer lo mismo, y desempatarlas por preferencia seria arbitrario.
    # 3. Preferencia de modalidad, solo cuando el score empata de verdad
    # 4. Costo total: a igualdad de todo, la que sale mas barata
    # 5. Holgura restante
    escenarios.sort(key=lambda e: (
        not e["viable"],
        -e["_exacto"],
        _preferencia_modalidad(e["modalidad"], monto),
        e["costo_total"] if e["costo_total"] is not None else float("inf"),
        -(e.get("holgura_despues") or 0),
    ))

    # El mejor de cada tarjeta (y el contado) queda marcado: es lo que viaja al
    # analisis profundo. Una tarjeta compite con su mejor carta, no con las seis.
    vistos: set[str | None] = set()
    for e in escenarios:
        if e["viable"] and e["tarjeta_id"] not in vistos:
            vistos.add(e["tarjeta_id"])
            e["mejor_de_tarjeta"] = True

    for e in escenarios:
        del e["_exacto"]

    return escenarios