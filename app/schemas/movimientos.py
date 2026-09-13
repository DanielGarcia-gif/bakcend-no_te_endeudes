"""
DTOs de `movimientos` — el recurso transaccional.

Sustituye a los antiguos GastoRequest/GastoResponse y absorbe tres cosas que
antes vivian separadas y no deberian: registrar un gasto, registrar un pago a
tarjeta y registrar un ingreso extraordinario. Los tres son el mismo hecho
—dinero que se movio— y comparten idempotencia, borrado y auditoria.

QUE CAMBIA RESPECTO AL CONTRATO VIEJO

  categoria: str libre        ->  categoria: clave del catalogo
      Antes cualquier cadena entraba, y las dos tablas que la usaban ya habian
      divergido (Comida/Compras/Salud en una, Servicios/Transporte en otra).

  medio: debito | credito     ->  efectivo | debito | credito
      Efectivo no era representable: colapsaba con debito porque el medio se
      inferia de `tarjeta_id IS NULL`.

  tipo: recurrente|espontaneo ->  desaparece
      "Recurrente" no era un tipo de gasto: era declarar un gasto fijo, que es
      otro recurso (POST /recurrentes). Mezclarlos hacia que un POST /gastos con
      tipo=recurrente no escribiera ningun movimiento ni moviera ningun saldo, y
      que `categoria` se usara a la vez como concepto y como categoria.

  (nuevo) msi
      Una compra a meses se registra JUNTO con su plan, en una sola peticion y
      una sola transaccion. Antes eran dos universos separados y por eso el
      saldo de una tarjeta y la suma de sus MSI no cuadraban.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.domain.tipos import Componente, MedioPago

TipoMovimiento = Literal["gasto", "pago", "ingreso"]


class MSIEnCompra(BaseModel):
    """
    El plan a meses de esta compra.

    `meses` los define el COMERCIO, no la tarjeta: Liverpool da 18 con la misma
    tarjeta con la que la tienda de la esquina no da ninguno. Por eso llegan en
    el request y no salen de la base.
    """
    meses: int = Field(ge=1, le=60)
    descripcion: Optional[str] = Field(default=None, max_length=160)
    # Informativo. Si no viene se calcula como total/meses; la deuda real
    # siempre sale de monto_total.
    monto_mensual: Optional[float] = Field(default=None, gt=0)


class MovimientoCreate(BaseModel):
    tipo: TipoMovimiento
    medio: MedioPago
    monto: float = Field(gt=0)
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    categoria: Optional[str] = Field(
        default=None,
        description="Clave del catalogo (GET /categorias). Obligatoria en los gastos.",
    )
    descripcion: Optional[str] = Field(default=None, max_length=255)
    tarjeta_id: Optional[str] = None
    ingreso_id: Optional[str] = Field(
        default=None,
        description="De que ingreso declarado viene este cobro. Sin el, es extraordinario.",
    )
    recurrente_id: Optional[str] = None
    msi: Optional[MSIEnCompra] = None

    @model_validator(mode="after")
    def _coherencia(self):
        """
        Adelanta en 422 lo que ck_mov_coherencia rechazaria en la base.

        La base es la autoridad —esa validacion no se puede saltar aunque este
        codigo tenga un hueco—, pero un mensaje que dice cual campo sobra es
        mas util que uno que nombra una restriccion SQL.
        """
        if self.tipo == "gasto":
            if (self.medio == "credito") != (self.tarjeta_id is not None):
                raise ValueError(
                    "Un gasto a credito necesita tarjeta, y uno en efectivo o "
                    "debito no puede llevarla"
                )
        elif self.tipo == "pago":
            if self.tarjeta_id is None:
                raise ValueError("Un pago necesita saber que tarjeta se paga")
            if self.medio == "credito":
                raise ValueError(
                    "Un pago sale de efectivo o debito: no se paga una tarjeta "
                    "con la misma tarjeta"
                )
        elif self.tipo == "ingreso":
            if self.tarjeta_id is not None:
                raise ValueError("Un ingreso no entra a una tarjeta")
            if self.medio == "credito":
                raise ValueError("Un ingreso no puede llegar por credito")

        if self.msi is not None and self.medio != "credito":
            raise ValueError("Solo una compra a credito puede ir a meses")
        return self


class MovimientoResumen(BaseModel):
    id: str
    tipo: str
    medio: str
    monto: float
    fecha: str
    categoria: Optional[str] = None          # clave
    categoria_nombre: Optional[str] = None   # para mostrar
    descripcion: Optional[str] = None
    tarjeta_id: Optional[str] = None
    tarjeta_nombre: Optional[str] = None
    periodo_id: Optional[str] = None
    ingreso_id: Optional[str] = None
    recurrente_id: Optional[str] = None


class Impacto(BaseModel):
    """
    El micro-momento.

    Muestra el COMPONENTE, no el score global: un gasto chico mueve menos de un
    punto entero del score, y decir "tu score sigue en 80" despues de gastar
    parece que la app no hizo nada. El componente si se mueve visiblemente.
    """
    score_antes: float
    score_despues: float
    componente_afectado: Componente
    componente_antes: int
    componente_despues: int


class MovimientoResponse(BaseModel):
    movimiento: MovimientoResumen
    impacto: Impacto
    # Presente solo cuando la peticion se resolvio por idempotencia: el
    # movimiento ya existia y no se creo nada nuevo. El cliente no deberia
    # volver a descontar nada de su UI optimista.
    repetido: bool = False