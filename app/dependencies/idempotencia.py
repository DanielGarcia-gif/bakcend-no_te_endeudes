"""
Dependencia de idempotencia.

Lee la cabecera `Idempotency-Key` de los POST que mueven dinero.

POR QUE UNA CABECERA Y NO UN CAMPO DEL CUERPO: porque no es parte del recurso.
El movimiento no tiene una propiedad "clave de idempotencia" que al usuario le
importe; es metadato del transporte, igual que un ETag. Ademas asi la misma
convencion sirve para todos los endpoints de escritura sin tocar sus schemas, y
es la que ya usan Stripe y compania — un cliente que las conozca no tiene que
aprender nada nuevo.

POR GESTO, NO POR PETICION. El cliente genera un UUID cuando el usuario toca
"guardar" y lo reusa en todos los reintentos de ESE gesto. Si generara uno
nuevo por peticion, un reintento de la libreria HTTP tras un timeout crearia el
gasto dos veces — que es exactamente lo que esto evita.

Es opcional: sin cabecera, la columna queda NULL. MySQL admite varios NULL en
un UNIQUE, asi que los clientes que no la manden siguen funcionando (y pagan el
riesgo del doble tap, que es su decision).
"""

from typing import Annotated, Optional

from fastapi import Header

from app.core.exceptions import ReglaDeNegocioViolada

LARGO_MAXIMO = 64   # el ancho de movimientos.idempotency_key


def get_idempotency_key(
    idempotency_key: Annotated[Optional[str], Header(
        alias="Idempotency-Key",
        description=(
            "UUID generado por el cliente para ESTE gesto del usuario. "
            "Reintentar con la misma clave devuelve 200 y el movimiento que ya "
            "existe, en vez de crear uno nuevo."
        ),
    )] = None,
) -> str | None:
    if idempotency_key is None:
        return None

    clave = idempotency_key.strip()
    if not clave:
        return None
    if len(clave) > LARGO_MAXIMO:
        # Truncarla en silencio seria peor: dos gestos distintos con prefijo
        # comun colisionarian y el segundo devolveria el movimiento del primero.
        raise ReglaDeNegocioViolada(
            f"La cabecera Idempotency-Key no puede pasar de {LARGO_MAXIMO} caracteres.",
            {"recibidos": len(clave)},
        )
    return clave


IdempotencyKey = Annotated[Optional[str], get_idempotency_key]