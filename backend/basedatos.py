"""Los datos de la tienda, que viven en Supabase.

Cada funcion de aca tiene una gemela **con el mismo nombre** en
`supabase/02_funciones.sql`, y la llama con una sola ida y vuelta por la red (ver
`nube.py`). Las pantallas no se enteraron del cambio: los nombres, los argumentos
y lo que devuelve cada una son los de cuando la base era SQLite en el telefono.

**Que queda aca y que se fue a Supabase:**

- **Aca:** lo que se puede decidir sin mirar los datos —un nombre vacio, un monto
  en cero, un carrito vacio— para no gastar un viaje en avisar algo obvio; los
  rangos de fecha, que dependen de la hora **del telefono**; y las cuentas que se
  arman con lo que vuelve (margen, serie por dia).
- **En Supabase:** todo lo que mira o toca varias filas a la vez. Una venta, un
  abono o una anulacion corren enteras alla dentro, en una transaccion: o entran
  completas o no entra nada, aunque se corte el internet a mitad de camino.

Las filas llegan como diccionarios (`fila["nombre"]`), igual que las de SQLite.
Las fotos viajan en base64 y aca se devuelven a `bytes`, que es lo que esperan
las pantallas.

Las fechas van y vienen en **ISO UTC**: el telefono puede tener la zona mal
puesta y las comparaciones tienen que cerrar.
"""

import base64
import copy
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from backend import nube


class SinExistencia(Exception):
    """Se quiso vender mas de lo que hay. El mensaje es para mostrarlo."""


class PagoNoCuadra(Exception):
    """El reparto entre metodos no suma el total. El mensaje es para mostrarlo."""


# La pista (`hint`) con que `privado.fallar` marca cada error en Supabase.
_ERRORES = {"SinExistencia": SinExistencia, "PagoNoCuadra": PagoNoCuadra}


# Las funciones que solo leen. Se pueden pedir de a varias en un viaje
# (`lote`) y reintentar si se corta la conexion; las demas, no.
LECTURAS = frozenset({
    "leer_config", "listar_productos", "contar_productos", "obtener_producto",
    "movimientos", "listar_fotos", "obtener_foto", "listar_clientes",
    "obtener_cliente", "listar_metodos", "obtener_metodo", "obtener_venta",
    "pagos_de_venta", "desglose_de_pagos", "listar_ventas", "contar_ventas",
    "resumen_ventas", "facturas_pendientes", "clientes_con_saldo",
    "total_por_cobrar", "abonos_de_cliente", "listar_gastos",
    "categorias_de_gasto", "metricas", "top_productos", "gastos_por_categoria",
    "ventas_para_serie", "resumen_inventario", "productos_del_catalogo", "lote",
})

# **Lo ya leido, para no volver a viajar.** Ver "Leer una vez" mas abajo.
_listo = {}
VIGENCIA = 120      # segundos


def olvidar_lo_leido():
    """Descarta todo lo guardado. Al cerrar sesion o al entrar con otra cuenta,
    o cuando algo cambia los datos por fuera de la app (las pruebas)."""
    _listo.clear()


def _guardado(funcion, datos):
    item = _listo.get(_clave(funcion, datos))
    if item is None or time.monotonic() - item[0] >= VIGENCIA:
        return False, None
    # Copia: varias funciones de abajo retocan lo que devuelven (las fotos pasan
    # de texto a bytes), y lo guardado tiene que quedar como vino.
    return True, copy.deepcopy(item[1])


def _guardar(funcion, datos, resultado):
    _listo[_clave(funcion, datos)] = (time.monotonic(), copy.deepcopy(resultado))


def _clave(funcion, datos):
    return funcion + json.dumps(datos, sort_keys=True, default=str)


def _rpc(funcion, /, **datos):
    """Llama a la funcion gemela y traduce sus errores a los de siempre.

    Un error de negocio (`P0001`: sin existencia, no cuadra, ya anulada...) trae
    un texto escrito para la pantalla y sale tal cual. Cualquier otro es un fallo
    que nadie previo: se muestra con su detalle para poder diagnosticarlo.

    Una lectura que ya se hizo hace poco no viaja: se devuelve la guardada.
    """
    lectura = funcion in LECTURAS
    if lectura:
        hay, valor = _guardado(funcion, datos)
        if hay:
            return valor
    else:
        # Algo se escribe: lo leido antes puede haber quedado viejo.
        _listo.clear()
    try:
        resultado = nube.llamar(funcion, datos, lectura=lectura)
    except nube.ErrorRemoto as ex:
        if ex.codigo == "P0001":
            raise _ERRORES.get(ex.pista, ValueError)(ex.mensaje) from None
        raise ValueError(f"No se pudo completar. ({ex.mensaje})") from None
    if lectura:
        _guardar(funcion, datos, resultado)
    return resultado


def _a_bytes(texto):
    return base64.b64decode(texto) if texto else None


def _a_texto(datos):
    return base64.b64encode(datos).decode("ascii") if datos else None


def ahora():
    """Momento actual en ISO UTC, **con milisegundos**."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def nuevo_id():
    return str(uuid.uuid4())


def preparar_cuenta():
    """Deja la cuenta lista para vender: siembra los metodos de pago la primera
    vez. Se llama al entrar; despues de la primera vez no hace nada."""
    olvidar_lo_leido()      # lo de otra cuenta, si la hubo, no sirve
    _rpc("preparar_cuenta")


# --------------------------------------------------------------------------
# Leer una vez, y todo junto
# --------------------------------------------------------------------------
#
# Cada viaje a Supabase desde Venezuela tarda de 0,4 a 0,6 segundos (medido: la
# mitad es la distancia hasta el servidor). Inicio pedia doce cosas al abrirse,
# una por una: seis segundos mirando la pantalla quieta. Y aun con un viaje por
# pantalla, cambiar de pestana se sentia.
#
# Dos cosas lo resuelven:
#
# 1. **Lo leido se guarda** (`_listo`) y se reusa durante `VIGENCIA`. Volver a
#    una pestana ya vista no viaja.
# 2. **Se pide todo junto**: `precargar_*` manda en un solo viaje (`lote`) las
#    lecturas de una pantalla que falten, y `precargar_todo`, al entrar, las de
#    todas.
#
# **Nunca se muestra un dato viejo despues de un cambio:** cualquier escritura
# (una venta, un gasto, la tasa) descarta todo lo guardado, y lo siguiente que
# se muestre se vuelve a pedir. Lo unico que puede tardar hasta `VIGENCIA` en
# verse es lo que se cargue **desde otro aparato** al mismo tiempo.
#
# Los argumentos de cada llamada tienen que ser **exactamente** los que usa la
# funcion de abajo; si no coinciden, no pasa nada malo, solo se viaja igual.
# `probar_botones.py` cuenta los viajes de cada pantalla para que no pase sin
# que se note.

def _de_un_viaje(*llamadas):
    """Pide en un solo viaje lo que todavia no este guardado."""
    faltan = []
    for funcion, datos in llamadas:
        if not _guardado(funcion, datos)[0] and (funcion, datos) not in faltan:
            faltan.append((funcion, datos))
    if not faltan:
        return
    try:
        resultados = nube.llamar(
            "lote", {"llamadas": [{"f": f, "p": d} for f, d in faltan]},
            lectura=True)
    except (nube.ErrorRemoto, nube.ErrorDeNube):
        return      # si falla, cada pantalla pide lo suyo como antes
    for (funcion, datos), resultado in zip(faltan, resultados):
        _guardar(funcion, datos, resultado)


def _hoy_local():
    return datetime.now().astimezone().date().isoformat()


def precargar_puerta():
    """La pantalla del PIN: si la cuenta ya tiene PIN, y el nombre para saludar."""
    _de_un_viaje(
        ("leer_config", {"clave": "pin"}),
        ("leer_config", {"clave": "nombre_usuario"}),
    )


def _lecturas_de_inicio():
    sp_desde, sp_hasta, _ = rango("semana_pasada")
    return [
        ("leer_config", {"clave": "nombre_usuario"}),
        ("leer_config", {"clave": "tasa_bcv"}),
        ("leer_config", {"clave": "tasa_actualizada_en"}),
        ("leer_config", {"clave": "resumen_ultima_semana"}),
        ("resumen_inventario", {}),
        ("resumen_ventas", {"desde": _inicio_del_dia_utc(), "hasta": None}),
        ("resumen_ventas", {"desde": sp_desde, "hasta": sp_hasta}),
        ("clientes_con_saldo", {}),
    ]


def _lecturas_de_venta():
    return [
        ("leer_config", {"clave": "tasa_bcv"}),
        ("listar_metodos", {"incluir_inactivos": False}),
        ("resumen_ventas", {"desde": _inicio_del_dia_utc(), "hasta": None}),
    ]


def _lecturas_de_inventario(busqueda, tope):
    return [
        ("listar_productos", {"busqueda": busqueda.strip(), "limite": tope}),
        ("contar_productos", {"busqueda": busqueda.strip()}),
        ("resumen_inventario", {}),
    ]


def precargar_inicio():
    _de_un_viaje(*_lecturas_de_inicio())


def precargar_venta():
    _de_un_viaje(*_lecturas_de_venta())


def precargar_inventario(busqueda, tope):
    _de_un_viaje(*_lecturas_de_inventario(busqueda, tope))


def _lecturas_del_periodo(desde, hasta):
    return [
        ("metricas", {"desde": desde, "hasta": hasta}),
        ("top_productos", {"desde": desde, "hasta": hasta, "limite": 5}),
        ("ventas_para_serie", {"desde": desde, "hasta": hasta}),
        ("total_por_cobrar", {"hoy": _hoy_local()}),
    ]


def precargar_gestion(periodo):
    desde, hasta, _ = rango(periodo)
    _de_un_viaje(*_lecturas_del_periodo(desde, hasta))


def precargar_todo(tope_inventario):
    """Al entrar: lo de todas las pestanas en un solo viaje. Despues, cambiar de
    pestana no viaja hasta que algo se escriba."""
    desde, hasta, _ = rango("semana")
    _de_un_viaje(*_lecturas_de_inicio(), *_lecturas_de_venta(),
                 *_lecturas_de_inventario("", tope_inventario),
                 *_lecturas_del_periodo(desde, hasta))


def precargar_semana(desde, hasta):
    """Todo lo que lleva el resumen semanal (ver `resumen_semanal.datos`)."""
    _de_un_viaje(*_lecturas_del_periodo(desde, hasta),
                 ("desglose_de_pagos", {"desde": desde, "hasta": hasta}),
                 ("gastos_por_categoria", {"desde": desde, "hasta": hasta}))


def cerrar():
    """Ya no hay conexion que cerrar: cada llamada es un pedido suelto. Queda
    para quien la llamaba al terminar."""


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

def leer_config(clave, por_defecto=None):
    valor = _rpc("leer_config", clave=clave)
    return por_defecto if valor is None else valor


def escribir_config(clave, valor):
    _rpc("escribir_config", clave=clave, valor=str(valor))


# --------------------------------------------------------------------------
# Productos
# --------------------------------------------------------------------------

def listar_productos(busqueda="", limite=None):
    """Los activos, ordenados por nombre, con su miniatura."""
    filas = _rpc("listar_productos", busqueda=busqueda.strip(), limite=limite)
    for f in filas:
        f["miniatura"] = _a_bytes(f.get("miniatura"))
    return filas


def contar_productos(busqueda=""):
    return _rpc("contar_productos", busqueda=busqueda.strip())


def obtener_producto(producto_id):
    return _rpc("obtener_producto", id=producto_id)


def crear_producto(nombre, descripcion, costo_usd, precio_usd, stock_inicial=0,
                   en_catalogo=True):
    return _rpc("crear_producto", nombre=nombre.strip(),
                descripcion=descripcion.strip(), costo_usd=float(costo_usd),
                precio_usd=float(precio_usd),
                stock_inicial=float(stock_inicial or 0),
                en_catalogo=bool(en_catalogo))


def actualizar_producto(producto_id, nombre, descripcion, costo_usd, precio_usd,
                        en_catalogo):
    """No toca el stock. El stock solo cambia por un movimiento, nunca escribiendo
    un total: ver `ajustar_stock` y `reabastecer`."""
    _rpc("actualizar_producto", id=producto_id, nombre=nombre.strip(),
         descripcion=descripcion.strip(), costo_usd=float(costo_usd),
         precio_usd=float(precio_usd), en_catalogo=bool(en_catalogo))


def eliminar_producto(producto_id):
    """Borrado logico. Las fotos y los movimientos quedan: son el historial de las
    ventas que ya se hicieron con ese producto."""
    _rpc("eliminar_producto", id=producto_id)


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------

def reabastecer(producto_id, cantidad, costo_usd=None, nota=""):
    """Entrada de mercancia. Si viene un costo nuevo, reemplaza al anterior.

    Ojo: esto **no** es un gasto. El costo de la mercancia ya se cuenta al vender,
    a traves del `costo_unit_usd` congelado en la linea de venta. Registrarlo
    ademas como gasto lo contaria dos veces.
    """
    if cantidad <= 0:
        raise ValueError("La cantidad que entra debe ser mayor que cero.")
    _rpc("reabastecer", producto_id=producto_id, cantidad=float(cantidad),
         costo_usd=None if costo_usd is None else float(costo_usd), nota=nota)


def ajustar_stock(producto_id, nuevo_total, nota=""):
    """"Conte y hay 7, no 5". Se guarda la diferencia, no el total.

    Es obligatorio tenerlo: como no se puede vender sin existencia, el dia que el
    numero real no coincida con el del sistema la app bloquea una venta que si se
    puede hacer. Sin una salida rapida, la gente termina vendiendo por fuera.
    """
    return _rpc("ajustar_stock", producto_id=producto_id,
                nuevo_total=float(nuevo_total),
                nota=nota or f"Conteo manual: {nuevo_total}")


def recalcular_stock(producto_id):
    """Reconstruye el resumen desde los movimientos. La red de seguridad si alguna
    vez el resumen y la verdad se separan."""
    return _rpc("recalcular_stock", producto_id=producto_id)


def movimientos(producto_id, limite=50):
    return _rpc("movimientos", producto_id=producto_id, limite=limite)


# --------------------------------------------------------------------------
# Fotos
# --------------------------------------------------------------------------

TAMANOS = ("miniatura", "catalogo", "completa")


def listar_fotos(producto_id, con_datos=False):
    filas = _rpc("listar_fotos", producto_id=producto_id, con_datos=con_datos)
    for f in filas:
        for tamano in TAMANOS:
            if tamano in f:
                f[tamano] = _a_bytes(f[tamano])
    return filas


def obtener_foto(foto_id, tamano="completa"):
    if tamano not in TAMANOS:
        raise ValueError("Tamaño de foto desconocido.")
    return _a_bytes(_rpc("obtener_foto", id=foto_id, tamano=tamano))


def guardar_foto(producto_id, tamanos):
    """`tamanos` es lo que devuelve `fotos.preparar`. La primera foto de un
    producto queda en el orden 1, y esa es la principal."""
    return _rpc("guardar_foto", producto_id=producto_id,
                **{t: _a_texto(tamanos[t]) for t in TAMANOS})


def eliminar_foto(foto_id):
    """Un borrado de verdad: una foto no es historia contable. Si se borra la
    principal, la siguiente ocupa su lugar."""
    _rpc("eliminar_foto", id=foto_id)


def hacer_principal(foto_id):
    """Intercambia esta foto con la que este en el orden 1."""
    _rpc("hacer_principal", id=foto_id)


# --------------------------------------------------------------------------
# Tasa del dia
# --------------------------------------------------------------------------

# Tope de cordura: atrapa el dedazo tipo "5500" cuando se quiso escribir "55,00".
# No pretende ser un limite real, solo que un error de tipeo no pase inadvertido.
TASA_MAXIMA = 1_000_000


def leer_tasa():
    valor = leer_config("tasa_bcv")
    try:
        return float(valor) if valor else 0.0
    except ValueError:
        return 0.0


def tasa_actualizada_en():
    """Cuando se guardo por ultima vez, en ISO UTC. `None` si nunca se cargo."""
    return leer_config("tasa_actualizada_en")


def guardar_tasa(valor):
    """La tasa entra en el precio en bolivares de cada venta y en el vuelto, asi
    que un error aca descuadra la caja del dia entero."""
    v = float(valor)
    if v <= 0:
        raise ValueError("La tasa debe ser mayor que cero.")
    if v > TASA_MAXIMA:
        raise ValueError(f"Esa tasa parece un error de tipeo "
                         f"(el tope es {TASA_MAXIMA:,.0f}).")
    escribir_config("tasa_bcv", repr(v))
    escribir_config("tasa_actualizada_en", ahora())
    return v


# --------------------------------------------------------------------------
# Clientes
# --------------------------------------------------------------------------

def listar_clientes(busqueda="", limite=None):
    return _rpc("listar_clientes", busqueda=busqueda.strip(), limite=limite)


def obtener_cliente(cliente_id):
    return _rpc("obtener_cliente", id=cliente_id)


def crear_cliente(nombre, telefono="", notas=""):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El cliente necesita un nombre.")
    return _rpc("crear_cliente", nombre=nombre, telefono=(telefono or "").strip(),
                notas=(notas or "").strip())


def actualizar_cliente(cliente_id, nombre, telefono="", notas=""):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El cliente necesita un nombre.")
    _rpc("actualizar_cliente", id=cliente_id, nombre=nombre,
         telefono=(telefono or "").strip(), notas=(notas or "").strip())


def eliminar_cliente(cliente_id):
    """Borrado logico, y solo si no debe nada: si desapareciera con saldo, esa
    deuda quedaria fuera de los cobros sin que nadie se entere."""
    _rpc("eliminar_cliente", id=cliente_id)


# --------------------------------------------------------------------------
# Metodos de pago
# --------------------------------------------------------------------------

MONEDAS = ("USD", "Bs")


def _validar_metodo(nombre, moneda):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El método necesita un nombre.")
    if moneda not in MONEDAS:
        raise ValueError("La moneda debe ser dólares o bolívares.")
    return nombre


def listar_metodos(incluir_inactivos=False):
    return _rpc("listar_metodos", incluir_inactivos=incluir_inactivos)


def obtener_metodo(metodo_id):
    return _rpc("obtener_metodo", id=metodo_id)


def crear_metodo(nombre, moneda):
    """No admite dos con el mismo nombre sin distinguir mayusculas: si no,
    "Zelle" y "zelle" serian dos metodos distintos en las metricas."""
    return _rpc("crear_metodo", nombre=_validar_metodo(nombre, moneda),
                moneda=moneda)


def actualizar_metodo(metodo_id, nombre, moneda):
    _rpc("actualizar_metodo", id=metodo_id,
         nombre=_validar_metodo(nombre, moneda), moneda=moneda)


def desactivar_metodo(metodo_id):
    """Borrado logico: las ventas viejas lo siguieron usando y su nombre quedo
    congelado en `venta_pagos`, asi que el historial no se toca."""
    _rpc("desactivar_metodo", id=metodo_id)


# --------------------------------------------------------------------------
# Ventas
# --------------------------------------------------------------------------

def registrar_venta(items, tasa_usada, tipo="contado", cliente_id=None,
                    fecha_pago_prevista=None, pagos=None):
    """Registra una venta completa. Entra entera o no entra.

    `items` es una lista de `{"producto_id": ..., "cantidad": ...}`, y `pagos`
    una de `{"metodo_id": ..., "monto": ...}`.

    Lo de adentro —comprobar el stock con la fila bloqueada, cuadrar los pagos,
    numerar, escribir lineas y movimientos— pasa en Supabase, en una sola
    transaccion: ver `registrar_venta` en `02_funciones.sql`. Ahi tambien se
    explica por que el precio, el costo, el nombre y la tasa se congelan.
    """
    if not items:
        raise ValueError("No hay nada en el carrito.")
    if float(tasa_usada) <= 0:
        raise ValueError("Falta cargar la tasa del día para poder vender.")
    if tipo not in ("contado", "credito"):
        raise ValueError("Tipo de venta desconocido.")
    if tipo == "credito" and not cliente_id:
        raise ValueError("Una venta a crédito necesita un cliente.")

    # Si el mismo producto entra dos veces, se suman: si no, cada linea validaria
    # el stock por su cuenta y entre las dos podrian pasarse del disponible.
    juntos = {}
    for it in items:
        cantidad = float(it["cantidad"])
        if cantidad <= 0:
            raise ValueError("Las cantidades tienen que ser mayores que cero.")
        juntos[it["producto_id"]] = juntos.get(it["producto_id"], 0) + cantidad

    venta = _rpc(
        "registrar_venta",
        items=[{"producto_id": p, "cantidad": c} for p, c in juntos.items()],
        tasa_usada=float(tasa_usada), tipo=tipo, cliente_id=cliente_id,
        fecha_pago_prevista=(fecha_pago_prevista.isoformat()
                             if isinstance(fecha_pago_prevista, date)
                             else fecha_pago_prevista),
        pagos=[{"metodo_id": p["metodo_id"], "monto": float(p["monto"])}
               for p in (pagos or [])])
    venta["total_usd"] = float(venta["total_usd"])
    venta["tasa_usada"] = float(venta["tasa_usada"])
    return venta


def anular_venta(venta_id):
    """Marca la venta como anulada y devuelve la mercancia al inventario con
    movimientos nuevos en sentido contrario. No se puede si ya tiene abonos."""
    _rpc("anular_venta", id=venta_id)


def obtener_venta(venta_id):
    resultado = _rpc("obtener_venta", id=venta_id)
    if not resultado:
        return None, []
    return resultado["venta"], resultado["lineas"]


def pagos_de_venta(venta_id):
    return _rpc("pagos_de_venta", venta_id=venta_id)


def desglose_de_hoy():
    return desglose_de_pagos(_inicio_del_dia_utc(), None)


def desglose_de_pagos(desde, hasta=None):
    """Cuanto entro por cada metodo. Es lo que hace falta para cuadrar la caja: el
    efectivo se cuenta contra el efectivo y el pago movil contra el banco.

    Cada moneda se suma en la suya, sin convertir; `monto_usd` va aparte para poder
    comparar entre metodos.
    """
    return _rpc("desglose_de_pagos", desde=desde, hasta=hasta)


def listar_ventas(desde=None, hasta=None, limite=40):
    """El historial, de la mas nueva a la mas vieja. Las fechas van en UTC: quien
    llama convierte primero el dia local con `rango()` o `_inicio_del_dia_utc()`."""
    return _rpc("listar_ventas", desde=desde, hasta=hasta, limite=limite)


def contar_ventas(desde=None, hasta=None):
    return _rpc("contar_ventas", desde=desde, hasta=hasta)


def resumen_ventas(desde=None, hasta=None):
    """Cuantas y cuanto, contando solo las activas: una venta anulada no ingreso."""
    return _rpc("resumen_ventas", desde=desde, hasta=hasta)


def ventas_de_hoy(limite=50):
    return listar_ventas(_inicio_del_dia_utc(), None, limite)


def resumen_de_hoy():
    return resumen_ventas(_inicio_del_dia_utc(), None)


# --------------------------------------------------------------------------
# Cuentas por cobrar
# --------------------------------------------------------------------------

# Por debajo de medio centavo se considera saldada: dividir bolivares entre la tasa
# deja restos minusculos, y sin este margen quedarian facturas "abiertas" por
# 0,003 dolares que nadie puede terminar de pagar. Es el mismo margen que usa
# `privado.pendientes` en Supabase.
CENTAVO = 0.005


def facturas_pendientes(cliente_id):
    """Las facturas abiertas de un cliente, **de la mas vieja a la mas nueva**.
    Ese orden es el que usa el reparto del abono."""
    return _rpc("facturas_pendientes", cliente_id=cliente_id)


def saldo_cliente(cliente_id):
    return round(sum(float(f["restante"]) for f in facturas_pendientes(cliente_id)), 2)


def clientes_con_saldo():
    """Quien debe, cuanto, y cual es su vencimiento mas proximo.

    Ordenados por vencimiento: primero lo vencido, despues lo que vence pronto, y
    al final lo que no tiene fecha puesta.
    """
    return _rpc("clientes_con_saldo")


def total_por_cobrar():
    """El credito que esta en la calle: facturado y todavia no cobrado.

    **No depende del periodo.** Las demas metricas miden un tramo de tiempo (lo
    vendido esta semana, los gastos de este mes); esto es una foto del momento: lo
    que se debe hoy, sin importar cuando se vendio. Hay que decirlo en la pantalla o
    se lee como si fuera del periodo elegido.

    Se separa lo vencido porque no es lo mismo tener $500 en la calle todos al dia
    que tener $500 de los cuales $300 ya se pasaron de fecha.
    """
    fila = _rpc("total_por_cobrar", hoy=_hoy_local())
    return {"total": float(fila["total"]), "vencido": float(fila["vencido"]),
            "clientes": fila["clientes"], "facturas": fila["facturas"]}


def registrar_abono(cliente_id, monto_recibido, moneda="USD", tasa=None,
                    metodo_id=None, nota=""):
    """Abona al **saldo del cliente**, saldando la factura mas vieja primero.

    No se abona contra una factura elegida a mano: el cliente paga y el sistema
    reparte. Pero **queda escrito a que factura fue cada pedazo** en
    `abono_aplicaciones`, que es lo que permite decirle "te quedo saldada la del 3
    de marzo" en vez de solo mostrarle un saldo que bajo.

    Las protecciones son las que se blindaron en SELL-B al exponer los abonos a la
    red: nada de montos en cero o negativos, nada de abonar sobre una cuenta ya
    saldada, y si el monto se pasa por centavos se ajusta al restante exacto en vez
    de dejar saldo negativo. Las dos ultimas miran el saldo, y por eso viven en
    `registrar_abono` de `02_funciones.sql`.
    """
    monto_recibido = float(monto_recibido)
    if monto_recibido <= 0:
        raise ValueError("El abono tiene que ser mayor que cero.")
    if moneda not in MONEDAS:
        raise ValueError("La moneda debe ser dólares o bolívares.")
    tasa = float(tasa or 0)
    if moneda == "Bs" and tasa <= 0:
        raise ValueError("Falta la tasa del día para recibir bolívares.")
    monto_usd = monto_recibido if moneda == "USD" else monto_recibido / tasa

    resultado = _rpc("registrar_abono", cliente_id=cliente_id,
                     monto_recibido=monto_recibido, moneda=moneda, tasa=tasa,
                     monto_usd=monto_usd, metodo_id=metodo_id,
                     nota=(nota or "").strip())
    resultado["monto_usd"] = float(resultado["monto_usd"])
    resultado["saldo_restante"] = float(resultado["saldo_restante"])
    for a in resultado["aplicadas"]:
        a["monto"] = float(a["monto"])
    return resultado


def abonos_de_cliente(cliente_id, limite=30):
    return _rpc("abonos_de_cliente", cliente_id=cliente_id, limite=limite)


def avisos_de_cobro(dias_aviso=7):
    """Lo vencido y lo que vence dentro de `dias_aviso`, para la pantalla de inicio.

    El corte se calcula con la fecha **local** del telefono, que es la que la
    persona tiene en la cabeza cuando piensa "vence el viernes".
    """
    hoy = datetime.now().astimezone().date()
    limite = (hoy + timedelta(days=dias_aviso)).isoformat()
    vencidos, proximos = [], []
    for fila in clientes_con_saldo():
        if not fila["vence"]:
            continue
        if fila["vence"] < hoy.isoformat():
            dias = (hoy - date.fromisoformat(fila["vence"])).days
            vencidos.append((fila, dias))
        elif fila["vence"] <= limite:
            dias = (date.fromisoformat(fila["vence"]) - hoy).days
            proximos.append((fila, dias))
    return vencidos, proximos


# --------------------------------------------------------------------------
# Gastos
# --------------------------------------------------------------------------

def crear_gasto(categoria, descripcion, monto_pagado, moneda="USD", tasa=None):
    """Un gasto **operativo**: delivery, empaques, publicidad, comisiones.

    La compra de mercancia **no va aca**: su costo ya se cuenta al vender, a traves
    del `costo_unit_usd` congelado en la linea de venta. Registrarla ademas como
    gasto la contaria dos veces y la ganancia saldria falsa hacia abajo. Para eso
    esta `reabastecer`, que suma stock sin tocar los gastos.
    """
    categoria = (categoria or "").strip()
    if not categoria:
        raise ValueError("El gasto necesita una categoría.")
    monto_pagado = float(monto_pagado)
    if monto_pagado <= 0:
        raise ValueError("El gasto tiene que ser mayor que cero.")
    if moneda not in MONEDAS:
        raise ValueError("La moneda debe ser dólares o bolívares.")
    tasa = float(tasa or 0)
    if moneda == "Bs" and tasa <= 0:
        raise ValueError("Falta la tasa del día para un gasto en bolívares.")
    monto_usd = monto_pagado if moneda == "USD" else monto_pagado / tasa
    return _rpc("crear_gasto", categoria=categoria,
                descripcion=(descripcion or "").strip(),
                monto_usd=round(monto_usd, 2), moneda=moneda,
                monto_pagado=monto_pagado, tasa=tasa)


def eliminar_gasto(gasto_id):
    _rpc("eliminar_gasto", id=gasto_id)


def listar_gastos(desde=None, hasta=None, limite=100):
    return _rpc("listar_gastos", desde=desde, hasta=hasta, limite=limite)


def categorias_de_gasto():
    """Las que ya se usaron, de la mas usada a la menos.

    La categoria es texto libre, pero el campo sugiere lo ya escrito: sin eso, las
    metricas terminan contando "Delivery", "delivery" y "deliveri" como tres cosas
    distintas.
    """
    return _rpc("categorias_de_gasto")


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------

PERIODOS = ("hoy", "semana", "mes")
PERIODOS_TODOS = PERIODOS + ("semana_pasada",)


def rango(periodo):
    """Devuelve `(desde, hasta, etiqueta)` en ISO UTC.

    El rango se calcula con la fecha **local**, que es la que la persona tiene en la
    cabeza: "esta semana" empieza el lunes de su lunes, no el de UTC. Por eso se
    arma aca y no en Supabase, que no sabe en que zona esta el telefono.
    """
    hoy = datetime.now().astimezone().date()
    if periodo == "hoy":
        inicio, fin, etiqueta = hoy, hoy + timedelta(days=1), "Hoy"
    elif periodo == "semana":
        inicio = hoy - timedelta(days=hoy.weekday())
        fin, etiqueta = hoy + timedelta(days=1), "Esta semana"
    elif periodo == "mes":
        inicio = hoy.replace(day=1)
        fin, etiqueta = hoy + timedelta(days=1), "Este mes"
    elif periodo == "semana_pasada":
        # Lunes a domingo completos de la semana anterior. Es la unica que termina
        # antes de hoy: las demas llegan hasta el final del dia en curso.
        lunes = hoy - timedelta(days=hoy.weekday())
        inicio, fin = lunes - timedelta(days=7), lunes
        etiqueta = "La semana pasada"
    else:
        raise ValueError("Periodo desconocido.")
    return _a_utc(inicio), _a_utc(fin), etiqueta


def _a_utc(dia):
    local = datetime.combine(dia, datetime.min.time()).astimezone()
    return local.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def metricas(periodo="semana", desde=None, hasta=None, etiqueta=None):
    """La cascada completa, de lo vendido a la ganancia neta.

    **Se cuenta por venta, no por cobro**: una venta a credito entra el dia que se
    hizo, igual que su costo. Si se contara al cobrar, la ganancia de un mes
    dependeria de cuando pague el cliente y no de lo que se vendio.

    Por eso ademas se devuelve `entro_en_caja`: lo que de verdad entro en el
    periodo. Un negocio puede tener buena ganancia y nada de dinero en la mano si
    vendio todo a credito, y eso hay que poder verlo.
    """
    if desde is None or hasta is None:
        desde, hasta, etiqueta = rango(periodo)
    s = _rpc("metricas", desde=desde, hasta=hasta)

    vendido = float(s["vendido"])
    costo = float(s["costo"])
    gastos = float(s["gastos"])
    bruta = vendido - costo
    neta = bruta - gastos
    return {
        "periodo": periodo,
        "etiqueta": etiqueta,
        "desde": desde,
        "hasta": hasta,
        "ventas": s["ventas"],
        "vendido": round(vendido, 2),
        "costo": round(costo, 2),
        "bruta": round(bruta, 2),
        "gastos": round(gastos, 2),
        "neta": round(neta, 2),
        "margen": round(neta / vendido * 100, 1) if vendido else 0.0,
        "entro_en_caja": round(float(s["cobrado_ventas"])
                               + float(s["cobrado_abonos"]), 2),
        # Sin el costo cargado, el margen de ese producto sale inflado: la ganancia
        # que muestra la pantalla seria mayor que la real.
        "sin_costo": s["sin_costo"],
    }


def top_productos(periodo="semana", limite=5, desde=None, hasta=None):
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    return _rpc("top_productos", desde=desde, hasta=hasta, limite=limite)


def gastos_por_categoria(periodo="semana", desde=None, hasta=None):
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    return _rpc("gastos_por_categoria", desde=desde, hasta=hasta)


def serie_diaria(periodo="semana", desde=None, hasta=None):
    """Un punto por dia del periodo, **incluidos los dias sin ventas**.

    Rellenar los vacios aca y no en la pantalla evita que el grafico invente un dia
    de mas o se salte uno: la lista que sale ya tiene exactamente los dias que hay
    que dibujar.
    """
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    filas = _rpc("ventas_para_serie", desde=desde, hasta=hasta)

    # **El agrupado se hace en Python, no en SQL.** Agrupar alla daria el dia UTC,
    # y las fechas se guardan en UTC: en Venezuela (UTC-4) todo lo vendido
    # despues de las 20:00 cae en el dia UTC siguiente. Agrupar asi y despues
    # buscar por dia local hacia desaparecer del grafico las ventas de la tarde.
    por_dia = {}
    for f in filas:
        dia = datetime.fromisoformat(f["fecha"]).astimezone().date().isoformat()
        acumulado = por_dia.setdefault(dia, {"vendido": 0.0, "costo": 0.0})
        acumulado["vendido"] += float(f["total_usd"] or 0)
        acumulado["costo"] += float(f["costo"] or 0)

    primero = datetime.fromisoformat(desde).astimezone().date()
    # El ultimo dia del rango, o el de hoy si el rango sigue abierto.
    tope = datetime.fromisoformat(hasta).astimezone().date() - timedelta(days=1)
    ultimo = min(tope, datetime.now().astimezone().date())
    serie = []
    dia = primero
    while dia <= ultimo:
        datos = por_dia.get(dia.isoformat(), {"vendido": 0.0, "costo": 0.0})
        serie.append({
            "dia": dia,
            "vendido": round(datos["vendido"], 2),
            "costo": round(datos["costo"], 2),
            "ganancia": round(datos["vendido"] - datos["costo"], 2),
        })
        dia += timedelta(days=1)
    return serie


def _inicio_del_dia_utc():
    ahora_local = datetime.now().astimezone()
    inicio = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return inicio.astimezone(timezone.utc).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------
# Resumen y catalogo
# --------------------------------------------------------------------------

def resumen_inventario():
    return _rpc("resumen_inventario")


def productos_del_catalogo(incluir_sin_stock=True):
    """Los marcados para el catalogo, con la foto de catalogo de su principal."""
    filas = _rpc("productos_del_catalogo", incluir_sin_stock=incluir_sin_stock)
    for f in filas:
        f["foto"] = _a_bytes(f.get("foto"))
    return filas
