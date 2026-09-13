"""
Comprueba que contrato/tipos.ts sigue siendo espejo del OpenAPI real.

    python -m app.scripts.verificar_contrato

El problema que resuelve: `tipos.ts` es una copia a mano del contrato, y una
copia a mano diverge. No con un cambio grande —eso se nota— sino con un campo
que alguien renombra en el backend y nadie espeja, y que el frontend descubre en
produccion leyendo `undefined`.

Compara, para cada interface de TypeScript que corresponda a un schema del
OpenAPI:

    - campos que el backend devuelve y TypeScript no declara  (el front no los ve)
    - campos que TypeScript declara y el backend no devuelve   (el front lee undefined)

No valida tipos, solo nombres. Es deliberado: los tipos se transforman al
serializar (Decimal -> number, date -> string) y comprobarlos exigiria un mapa
de equivalencias que envejeceria peor que el problema que resuelve. Los nombres
son donde ocurren las divergencias silenciosas.

No corre en la suite de tests: necesita el archivo .ts, que vive fuera del ciclo
de Python. Es una comprobacion de antes de entregar el contrato al frontend.
"""

import re
import sys
from pathlib import Path

TIPOS_TS = Path(__file__).resolve().parent.parent / "contrato" / "tipos.ts"

# interface de TypeScript  ->  schema del OpenAPI.
# Solo las que son espejo directo de un modelo de respuesta; las de request y
# los alias (Partial<>, Omit<>) no tienen contraparte 1:1.
EQUIVALENCIAS = {
    "UsuarioResumen": "UsuarioResumen",
    "CategoriaResumen": "CategoriaResumen",
    "TokenResponse": "TokenResponse",
    "IngresoResumen": "IngresoResumen",
    "RecurrenteResumen": "RecurrenteResumen",
    "RecurrenteHistorial": "RecurrenteHistorial",
    "Pendiente": "Pendiente",
    "PendientesResponse": "PendientesResponse",
    "Confirmacion": "Confirmacion",
    "TarjetaResumen": "TarjetaResumen",
    "MSIResumen": "MSIResumen",
    "PeriodoResumen": "PeriodoResumen",
    "PagoPendiente": "PagoPendiente",
    "MovimientoResumen": "MovimientoResumen",
    "MovimientoResponse": "MovimientoResponse",
    "Impacto": "Impacto",
    "OnboardingResponse": "OnboardingResponse",
    "ScoreResponse": "ScoreResponse",
    "Escenario": "Escenario",
    "MetricasCompra": "MetricasCompra",
    "SimulacionResponse": "SimulacionResponse",
    "DeudaRanking": "DeudaRanking",
    "DeudaResponse": "DeudaResponse",
    "PagoResponse": "PagoResponse",
    "MetaPagina": "MetaPagina",
    "Estado": "Estado",
    "TarjetaEstado": "TarjetaEstado",
    "PlanLeido": "PlanLeido",
    "PagosLeidos": "PagosLeidos",
    "ExtraccionResponse": "ExtraccionResponse",
    "ExplicacionDeudaResponse": "ExplicacionDeudaResponse",
    "AnalisisCompraResponse": "AnalisisCompraResponse",
}


def campos_de_typescript(fuente: str) -> dict[str, set[str]]:
    """
    Saca los nombres de campo de cada `export interface X { ... }`.

    Ignora comentarios de bloque y de linea: sin eso, un `* meses_restantes:`
    dentro de un docstring contaria como campo.
    """
    salida: dict[str, set[str]] = {}
    for m in re.finditer(r"export interface (\w+)[^{]*\{(.*?)\n\}", fuente, re.S):
        nombre, cuerpo = m.group(1), m.group(2)
        cuerpo = re.sub(r"/\*.*?\*/", "", cuerpo, flags=re.S)
        cuerpo = re.sub(r"//.*", "", cuerpo)

        # Solo el primer nivel. Sin contar llaves, los campos de un objeto
        # anidado (flujo_30d: { serie, minimo, dia_minimo }) se atribuyen a la
        # interface que los contiene y se reportan como campos que el backend no
        # devuelve, que es justo el falso positivo que hace ignorar la salida.
        campos, profundidad = set(), 0
        for linea in cuerpo.splitlines():
            if profundidad == 0:
                encontrado = re.match(r"\s*(\w+)\??\s*:", linea)
                if encontrado:
                    campos.add(encontrado.group(1))
            profundidad += linea.count("{") - linea.count("}")
        salida[nombre] = campos
    return salida


def campos_de_openapi(esquemas: dict, nombre: str) -> set[str] | None:
    esquema = esquemas.get(nombre)
    if esquema is None:
        return None
    if "properties" in esquema:
        return set(esquema["properties"])
    # Los modelos con computed_field o alias pueden salir como allOf.
    for parte in esquema.get("allOf", []):
        if "properties" in parte:
            return set(parte["properties"])
    return set()


def main() -> int:
    if not TIPOS_TS.exists():
        print(f"No se encontro {TIPOS_TS}")
        return 1

    from app.main import app

    esquemas = app.openapi().get("components", {}).get("schemas", {})
    interfaces = campos_de_typescript(TIPOS_TS.read_text(encoding="utf-8"))

    problemas = 0
    revisadas = 0

    for ts, py in sorted(EQUIVALENCIAS.items()):
        en_ts = interfaces.get(ts)
        en_py = campos_de_openapi(esquemas, py)

        if en_ts is None:
            print(f"  FALTA en tipos.ts       interface {ts}")
            problemas += 1
            continue
        if en_py is None:
            print(f"  FALTA en el OpenAPI     schema {py}  (interface {ts})")
            problemas += 1
            continue

        revisadas += 1
        sobran = en_ts - en_py
        faltan = en_py - en_ts

        if faltan:
            print(f"  {ts}: el backend devuelve campos que tipos.ts no declara")
            for c in sorted(faltan):
                print(f"      + {c}")
            problemas += 1
        if sobran:
            print(f"  {ts}: tipos.ts declara campos que el backend no devuelve")
            for c in sorted(sobran):
                print(f"      - {c}   (el frontend leeria undefined)")
            problemas += 1

    print()
    if problemas:
        print(f"{problemas} divergencia(s) entre contrato/tipos.ts y el OpenAPI.")
        return 1

    print(f"contrato/tipos.ts coincide con el OpenAPI ({revisadas} interfaces).")
    return 0


if __name__ == "__main__":
    sys.exit(main())