"""SQLite: el esquema completo y las operaciones de inventario.

Esta base **es la verdad**. Neon (Fase 6) va a ser una copia empujada en una sola
direccion, y por eso el esquema ya nace con lo que esa copia necesita aunque hoy no
se use:

- **UUID como identidad**, no autonumericos: dos dispositivos pueden generar filas
  sin chocar.
- **`sincronizado_en`** en cada tabla es una columna muerta. Venia del respaldo
  en Neon, que se quito: ahora el respaldo es un archivo (ver `respaldo.py`) y la
  base del telefono es la unica que existe. **No se borraron las columnas a
  proposito**: sacarlas obliga a reescribir diez tablas en un telefono con datos
  reales, y a cambio no se gana nada. Quedan siempre en NULL y nadie las lee.

Las fechas se guardan en **ISO UTC**, no en hora local: el telefono puede tener la
zona mal puesta y las comparaciones entre dispositivos tienen que cerrar.
"""

import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

from backend import almacenamiento

_conexion = None
_candado = threading.RLock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id              TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    descripcion     TEXT NOT NULL DEFAULT '',
    costo_usd       REAL NOT NULL DEFAULT 0,
    precio_usd      REAL NOT NULL DEFAULT 0,
    stock           REAL NOT NULL DEFAULT 0,
    en_catalogo     INTEGER NOT NULL DEFAULT 1,
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS producto_fotos (
    id              TEXT PRIMARY KEY,
    producto_id     TEXT NOT NULL REFERENCES productos(id),
    orden           INTEGER NOT NULL,
    miniatura       BLOB NOT NULL,
    catalogo        BLOB NOT NULL,
    completa        BLOB NOT NULL,
    creado_en       TEXT NOT NULL,
    sincronizado_en TEXT,
    UNIQUE (producto_id, orden)
);

CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id              TEXT PRIMARY KEY,
    producto_id     TEXT NOT NULL REFERENCES productos(id),
    delta           REAL NOT NULL,
    motivo          TEXT NOT NULL,
    referencia_id   TEXT,
    nota            TEXT NOT NULL DEFAULT '',
    fecha           TEXT NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS clientes (
    id              TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    telefono        TEXT NOT NULL DEFAULT '',
    notas           TEXT NOT NULL DEFAULT '',
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS ventas (
    id                  TEXT PRIMARY KEY,
    correlativo         INTEGER NOT NULL,
    cliente_id          TEXT REFERENCES clientes(id),
    fecha               TEXT NOT NULL,
    tipo                TEXT NOT NULL,
    total_usd           REAL NOT NULL,
    tasa_usada          REAL NOT NULL,
    fecha_pago_prevista TEXT,
    estado              TEXT NOT NULL DEFAULT 'activa',
    sincronizado_en     TEXT
);

CREATE TABLE IF NOT EXISTS venta_lineas (
    id               TEXT PRIMARY KEY,
    venta_id         TEXT NOT NULL REFERENCES ventas(id),
    producto_id      TEXT NOT NULL REFERENCES productos(id),
    nombre_congelado TEXT NOT NULL,
    cantidad         REAL NOT NULL,
    precio_unit_usd  REAL NOT NULL,
    costo_unit_usd   REAL NOT NULL,
    sincronizado_en  TEXT
);

CREATE TABLE IF NOT EXISTS abonos (
    id              TEXT PRIMARY KEY,
    cliente_id      TEXT NOT NULL REFERENCES clientes(id),
    fecha           TEXT NOT NULL,
    monto_usd       REAL NOT NULL,
    moneda_recibida TEXT NOT NULL,
    monto_recibido  REAL NOT NULL,
    tasa_usada      REAL NOT NULL,
    metodo_id       TEXT,
    metodo_nombre   TEXT NOT NULL DEFAULT '',
    nota            TEXT NOT NULL DEFAULT '',
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS abono_aplicaciones (
    id              TEXT PRIMARY KEY,
    abono_id        TEXT NOT NULL REFERENCES abonos(id),
    venta_id        TEXT NOT NULL REFERENCES ventas(id),
    monto_usd       REAL NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS gastos (
    id              TEXT PRIMARY KEY,
    fecha           TEXT NOT NULL,
    categoria       TEXT NOT NULL,
    descripcion     TEXT NOT NULL DEFAULT '',
    monto_usd       REAL NOT NULL,
    moneda_pagada   TEXT NOT NULL,
    monto_pagado    REAL NOT NULL,
    tasa_usada      REAL NOT NULL,
    activo          INTEGER NOT NULL DEFAULT 1,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS metodos_pago (
    id              TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    moneda          TEXT NOT NULL,
    orden           INTEGER NOT NULL DEFAULT 0,
    activo          INTEGER NOT NULL DEFAULT 1,
    creado_en       TEXT NOT NULL,
    actualizado_en  TEXT NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS venta_pagos (
    id              TEXT PRIMARY KEY,
    venta_id        TEXT NOT NULL REFERENCES ventas(id),
    metodo_id       TEXT REFERENCES metodos_pago(id),
    metodo_nombre   TEXT NOT NULL,
    moneda          TEXT NOT NULL,
    monto           REAL NOT NULL,
    monto_usd       REAL NOT NULL,
    sincronizado_en TEXT
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pagos_venta      ON venta_pagos(venta_id);
CREATE INDEX IF NOT EXISTS idx_productos_activos ON productos(activo, nombre);
CREATE INDEX IF NOT EXISTS idx_fotos_producto    ON producto_fotos(producto_id, orden);
CREATE INDEX IF NOT EXISTS idx_movimientos_prod  ON movimientos_inventario(producto_id);
CREATE INDEX IF NOT EXISTS idx_ventas_cliente    ON ventas(cliente_id, estado);
"""


def ahora():
    """Momento actual en ISO UTC, **con milisegundos**.

    La precision no es capricho: con segundos, dos filas creadas seguidas
    empatan y cualquier "ordenar por fecha" queda a merced del motor.
    """
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def nuevo_id():
    return str(uuid.uuid4())


def conexion():
    global _conexion
    with _candado:
        if _conexion is None:
            # `check_same_thread=False` porque Flet atiende los eventos desde hilos
            # distintos. La seguridad la da `_candado`, que serializa todo acceso.
            _conexion = sqlite3.connect(almacenamiento.RUTA_BASE_DATOS,
                                        check_same_thread=False)
            _conexion.row_factory = sqlite3.Row
            _conexion.execute("PRAGMA foreign_keys = ON")
            # WAL: si el telefono se apaga a mitad de una escritura, la base no
            # queda corrupta y se recupera sola al abrir.
            _conexion.execute("PRAGMA journal_mode = WAL")
            _conexion.executescript(ESQUEMA)
            _migrar(_conexion)
            _sembrar_metodos(_conexion)
            _conexion.commit()
        return _conexion


# Columnas agregadas despues de que la base ya existia en algun telefono.
# `CREATE TABLE IF NOT EXISTS` no toca una tabla que ya esta, asi que agregar un
# campo al esquema no alcanza: hay que pedirlo aparte. Se aplican solo si faltan,
# asi que correrlas de nuevo no hace nada.
MIGRACIONES = [
    ("abonos", "metodo_id", "TEXT"),
    ("abonos", "metodo_nombre", "TEXT NOT NULL DEFAULT ''"),
    ("gastos", "activo", "INTEGER NOT NULL DEFAULT 1"),
]


def _migrar(c):
    for tabla, columna, definicion in MIGRACIONES:
        existentes = {f["name"] for f in c.execute(
            f"PRAGMA table_info({tabla})").fetchall()}
        if columna not in existentes:
            c.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")


# Los que usa cualquier vendedora en Venezuela. Son solo el punto de partida: la
# lista se edita desde Configuracion, asi que agregar Binance o quitar Zelle no
# necesita tocar el programa.
METODOS_INICIALES = [
    ("Efectivo en dólares", "USD"),
    ("Efectivo en bolívares", "Bs"),
    ("Pago móvil", "Bs"),
    ("Transferencia", "Bs"),
    ("Zelle", "USD"),
]


def _sembrar_metodos(c):
    """Solo si la tabla esta vacia. Si ella borro alguno, no vuelve a aparecer."""
    if c.execute("SELECT COUNT(*) AS n FROM metodos_pago").fetchone()["n"]:
        return
    momento = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    for orden, (nombre, moneda) in enumerate(METODOS_INICIALES):
        c.execute(
            "INSERT INTO metodos_pago (id, nombre, moneda, orden, activo, "
            "creado_en, actualizado_en) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (str(uuid.uuid4()), nombre, moneda, orden, momento, momento))


def cerrar():
    global _conexion
    with _candado:
        if _conexion is not None:
            _conexion.close()
            _conexion = None


# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

def leer_config(clave, por_defecto=None):
    with _candado:
        fila = conexion().execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
        return fila["valor"] if fila else por_defecto


def escribir_config(clave, valor):
    with _candado:
        c = conexion()
        c.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
                  "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                  (clave, str(valor)))
        c.commit()


# --------------------------------------------------------------------------
# Productos
# --------------------------------------------------------------------------

def listar_productos(busqueda="", limite=None):
    """Los activos, ordenados por nombre, con su miniatura.

    El filtro va en SQL y no en memoria: con SQLite en el propio telefono no hay
    viaje de red que ahorrar, y dejar que el indice trabaje es mas rapido que
    traerse todo y recorrerlo en Python.
    """
    sql = ["SELECT p.*, f.miniatura FROM productos p "
           "LEFT JOIN producto_fotos f ON f.producto_id = p.id AND f.orden = 1 "
           "WHERE p.activo = 1"]
    args = []
    if busqueda.strip():
        sql.append("AND (p.nombre LIKE ? OR p.descripcion LIKE ?)")
        patron = f"%{busqueda.strip()}%"
        args += [patron, patron]
    sql.append("ORDER BY p.nombre COLLATE NOCASE")
    if limite:
        sql.append("LIMIT ?")
        args.append(limite)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchall()


def contar_productos(busqueda=""):
    sql = ["SELECT COUNT(*) AS n FROM productos WHERE activo = 1"]
    args = []
    if busqueda.strip():
        sql.append("AND (nombre LIKE ? OR descripcion LIKE ?)")
        patron = f"%{busqueda.strip()}%"
        args += [patron, patron]
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchone()["n"]


def obtener_producto(producto_id):
    with _candado:
        return conexion().execute(
            "SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone()


def crear_producto(nombre, descripcion, costo_usd, precio_usd, stock_inicial=0,
                   en_catalogo=True):
    momento = ahora()
    producto_id = nuevo_id()
    with _candado:
        c = conexion()
        c.execute(
            "INSERT INTO productos (id, nombre, descripcion, costo_usd, precio_usd, "
            "stock, en_catalogo, activo, creado_en, actualizado_en) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, 1, ?, ?)",
            (producto_id, nombre.strip(), descripcion.strip(), float(costo_usd),
             float(precio_usd), 1 if en_catalogo else 0, momento, momento))
        if stock_inicial:
            _mover(c, producto_id, float(stock_inicial), "alta",
                   nota="Existencia al registrar el producto")
        c.commit()
    return producto_id


def actualizar_producto(producto_id, nombre, descripcion, costo_usd, precio_usd,
                        en_catalogo):
    """No toca el stock. El stock solo cambia por un movimiento, nunca escribiendo
    un total: ver `ajustar_stock` y `reabastecer`."""
    with _candado:
        c = conexion()
        c.execute(
            "UPDATE productos SET nombre = ?, descripcion = ?, costo_usd = ?, "
            "precio_usd = ?, en_catalogo = ?, actualizado_en = ?, "
            "sincronizado_en = NULL WHERE id = ?",
            (nombre.strip(), descripcion.strip(), float(costo_usd),
             float(precio_usd), 1 if en_catalogo else 0, ahora(), producto_id))
        c.commit()


def eliminar_producto(producto_id):
    """Borrado logico. Las fotos y los movimientos quedan: son el historial de las
    ventas que ya se hicieron con ese producto."""
    with _candado:
        c = conexion()
        c.execute("UPDATE productos SET activo = 0, actualizado_en = ?, "
                  "sincronizado_en = NULL WHERE id = ?", (ahora(), producto_id))
        c.commit()


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------

def _mover(c, producto_id, delta, motivo, referencia_id=None, nota=""):
    """Escribe el movimiento y actualiza el resumen. Siempre juntos.

    `productos.stock` es un resumen calculado: existe para que las listas no tengan
    que sumar movimientos en cada consulta. La verdad esta en la tabla de
    movimientos, y `recalcular_stock` puede reconstruirlo desde ahi.
    """
    c.execute(
        "INSERT INTO movimientos_inventario "
        "(id, producto_id, delta, motivo, referencia_id, nota, fecha) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (nuevo_id(), producto_id, float(delta), motivo, referencia_id, nota, ahora()))
    c.execute("UPDATE productos SET stock = stock + ?, actualizado_en = ?, "
              "sincronizado_en = NULL WHERE id = ?",
              (float(delta), ahora(), producto_id))


def reabastecer(producto_id, cantidad, costo_usd=None, nota=""):
    """Entrada de mercancia. Si viene un costo nuevo, reemplaza al anterior.

    Ojo: esto **no** es un gasto. El costo de la mercancia ya se cuenta al vender,
    a traves del `costo_unit_usd` congelado en la linea de venta. Registrarlo
    ademas como gasto lo contaria dos veces.
    """
    if cantidad <= 0:
        raise ValueError("La cantidad que entra debe ser mayor que cero.")
    with _candado:
        c = conexion()
        _mover(c, producto_id, float(cantidad), "compra", nota=nota)
        if costo_usd is not None:
            c.execute("UPDATE productos SET costo_usd = ?, actualizado_en = ?, "
                      "sincronizado_en = NULL WHERE id = ?",
                      (float(costo_usd), ahora(), producto_id))
        c.commit()


def ajustar_stock(producto_id, nuevo_total, nota=""):
    """"Conte y hay 7, no 5". Se guarda la diferencia, no el total.

    Es obligatorio tenerlo: como no se puede vender sin existencia, el dia que el
    numero real no coincida con el del sistema la app bloquea una venta que si se
    puede hacer. Sin una salida rapida, la gente termina vendiendo por fuera.
    """
    with _candado:
        c = conexion()
        fila = c.execute("SELECT stock FROM productos WHERE id = ?",
                         (producto_id,)).fetchone()
        if fila is None:
            raise ValueError("Ese producto no existe.")
        delta = float(nuevo_total) - float(fila["stock"])
        if delta == 0:
            return 0
        _mover(c, producto_id, delta, "ajuste",
               nota=nota or f"Conteo manual: {nuevo_total}")
        c.commit()
        return delta


def recalcular_stock(producto_id):
    """Reconstruye el resumen desde los movimientos. La red de seguridad si alguna
    vez el resumen y la verdad se separan."""
    with _candado:
        c = conexion()
        total = c.execute(
            "SELECT COALESCE(SUM(delta), 0) AS t FROM movimientos_inventario "
            "WHERE producto_id = ?", (producto_id,)).fetchone()["t"]
        c.execute("UPDATE productos SET stock = ? WHERE id = ?", (total, producto_id))
        c.commit()
        return total


def movimientos(producto_id, limite=50):
    with _candado:
        return conexion().execute(
            "SELECT * FROM movimientos_inventario WHERE producto_id = ? "
            "ORDER BY fecha DESC LIMIT ?", (producto_id, limite)).fetchall()


# --------------------------------------------------------------------------
# Fotos
# --------------------------------------------------------------------------

def listar_fotos(producto_id, con_datos=False):
    columnas = "id, producto_id, orden" + (
        ", miniatura, catalogo, completa" if con_datos else ", miniatura")
    with _candado:
        return conexion().execute(
            f"SELECT {columnas} FROM producto_fotos WHERE producto_id = ? "
            "ORDER BY orden", (producto_id,)).fetchall()


def obtener_foto(foto_id, tamano="completa"):
    if tamano not in ("miniatura", "catalogo", "completa"):
        raise ValueError("Tamaño de foto desconocido.")
    with _candado:
        fila = conexion().execute(
            f"SELECT {tamano} AS datos FROM producto_fotos WHERE id = ?",
            (foto_id,)).fetchone()
        return fila["datos"] if fila else None


def guardar_foto(producto_id, tamanos):
    """`tamanos` es lo que devuelve `fotos.preparar`. La primera foto de un
    producto queda en el orden 1, y esa es la principal."""
    with _candado:
        c = conexion()
        usados = [f["orden"] for f in c.execute(
            "SELECT orden FROM producto_fotos WHERE producto_id = ?",
            (producto_id,)).fetchall()]
        libre = next((n for n in (1, 2, 3) if n not in usados), None)
        if libre is None:
            raise ValueError("Ya tiene tres fotos. Borra una para agregar otra.")
        foto_id = nuevo_id()
        c.execute(
            "INSERT INTO producto_fotos (id, producto_id, orden, miniatura, "
            "catalogo, completa, creado_en) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (foto_id, producto_id, libre, tamanos["miniatura"],
             tamanos["catalogo"], tamanos["completa"], ahora()))
        c.commit()
        return foto_id


def eliminar_foto(foto_id):
    """Aca si es un borrado de verdad: una foto no es historia contable, y dejarla
    ocuparia espacio en el telefono y en el respaldo para siempre.

    Si se borra la principal, la siguiente ocupa su lugar: un producto sin foto
    principal no se veria en la lista ni en el catalogo.
    """
    with _candado:
        c = conexion()
        fila = c.execute("SELECT producto_id FROM producto_fotos WHERE id = ?",
                         (foto_id,)).fetchone()
        if fila is None:
            return
        c.execute("DELETE FROM producto_fotos WHERE id = ?", (foto_id,))
        restantes = c.execute(
            "SELECT id FROM producto_fotos WHERE producto_id = ? ORDER BY orden",
            (fila["producto_id"],)).fetchall()
        for nuevo_orden, f in enumerate(restantes, start=1):
            c.execute("UPDATE producto_fotos SET orden = ?, sincronizado_en = NULL "
                      "WHERE id = ?", (nuevo_orden, f["id"]))
        c.commit()


def hacer_principal(foto_id):
    """Intercambia esta foto con la que este en el orden 1."""
    with _candado:
        c = conexion()
        fila = c.execute("SELECT producto_id, orden FROM producto_fotos "
                         "WHERE id = ?", (foto_id,)).fetchone()
        if fila is None or fila["orden"] == 1:
            return
        principal = c.execute(
            "SELECT id FROM producto_fotos WHERE producto_id = ? AND orden = 1",
            (fila["producto_id"],)).fetchone()
        # Se pasa por un orden temporal porque (producto_id, orden) es unico y el
        # intercambio directo chocaria contra esa restriccion a mitad de camino.
        c.execute("UPDATE producto_fotos SET orden = 0 WHERE id = ?", (foto_id,))
        if principal:
            c.execute("UPDATE producto_fotos SET orden = ?, sincronizado_en = NULL "
                      "WHERE id = ?", (fila["orden"], principal["id"]))
        c.execute("UPDATE producto_fotos SET orden = 1, sincronizado_en = NULL "
                  "WHERE id = ?", (foto_id,))
        c.commit()


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
    sql = ["SELECT * FROM clientes WHERE activo = 1"]
    args = []
    if busqueda.strip():
        sql.append("AND (nombre LIKE ? OR telefono LIKE ?)")
        patron = f"%{busqueda.strip()}%"
        args += [patron, patron]
    sql.append("ORDER BY nombre COLLATE NOCASE")
    if limite:
        sql.append("LIMIT ?")
        args.append(limite)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchall()


def obtener_cliente(cliente_id):
    with _candado:
        return conexion().execute("SELECT * FROM clientes WHERE id = ?",
                                  (cliente_id,)).fetchone()


def crear_cliente(nombre, telefono="", notas=""):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El cliente necesita un nombre.")
    momento = ahora()
    cliente_id = nuevo_id()
    with _candado:
        c = conexion()
        c.execute(
            "INSERT INTO clientes (id, nombre, telefono, notas, activo, "
            "creado_en, actualizado_en) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (cliente_id, nombre, (telefono or "").strip(), (notas or "").strip(),
             momento, momento))
        c.commit()
    return cliente_id


def actualizar_cliente(cliente_id, nombre, telefono="", notas=""):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El cliente necesita un nombre.")
    with _candado:
        c = conexion()
        c.execute("UPDATE clientes SET nombre = ?, telefono = ?, notas = ?, "
                  "actualizado_en = ?, sincronizado_en = NULL WHERE id = ?",
                  (nombre, (telefono or "").strip(), (notas or "").strip(),
                   ahora(), cliente_id))
        c.commit()


def eliminar_cliente(cliente_id):
    """Borrado logico, y solo si no debe nada: si desapareciera con saldo, esa
    deuda quedaria fuera de los cobros sin que nadie se entere."""
    with _candado:
        if saldo_cliente(cliente_id) > 0.005:
            raise ValueError("No se puede borrar un cliente que todavía debe.")
        c = conexion()
        c.execute("UPDATE clientes SET activo = 0, actualizado_en = ?, "
                  "sincronizado_en = NULL WHERE id = ?", (ahora(), cliente_id))
        c.commit()


# --------------------------------------------------------------------------
# Metodos de pago
# --------------------------------------------------------------------------

MONEDAS = ("USD", "Bs")


def listar_metodos(incluir_inactivos=False):
    sql = "SELECT * FROM metodos_pago"
    if not incluir_inactivos:
        sql += " WHERE activo = 1"
    sql += " ORDER BY orden, nombre COLLATE NOCASE"
    with _candado:
        return conexion().execute(sql).fetchall()


def obtener_metodo(metodo_id):
    with _candado:
        return conexion().execute("SELECT * FROM metodos_pago WHERE id = ?",
                                  (metodo_id,)).fetchone()


def crear_metodo(nombre, moneda):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El método necesita un nombre.")
    if moneda not in MONEDAS:
        raise ValueError("La moneda debe ser dólares o bolívares.")
    momento = ahora()
    with _candado:
        c = conexion()
        # Se compara sin distinguir mayusculas para que no queden "Zelle" y "zelle"
        # como dos metodos distintos en las metricas.
        repetido = c.execute(
            "SELECT id FROM metodos_pago WHERE lower(nombre) = lower(?) "
            "AND activo = 1", (nombre,)).fetchone()
        if repetido:
            raise ValueError(f"Ya existe un método llamado «{nombre}».")
        siguiente = c.execute(
            "SELECT COALESCE(MAX(orden), -1) + 1 AS n FROM metodos_pago"
        ).fetchone()["n"]
        metodo_id = nuevo_id()
        c.execute(
            "INSERT INTO metodos_pago (id, nombre, moneda, orden, activo, "
            "creado_en, actualizado_en) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (metodo_id, nombre, moneda, siguiente, momento, momento))
        c.commit()
        return metodo_id


def actualizar_metodo(metodo_id, nombre, moneda):
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("El método necesita un nombre.")
    if moneda not in MONEDAS:
        raise ValueError("La moneda debe ser dólares o bolívares.")
    with _candado:
        c = conexion()
        repetido = c.execute(
            "SELECT id FROM metodos_pago WHERE lower(nombre) = lower(?) "
            "AND activo = 1 AND id <> ?", (nombre, metodo_id)).fetchone()
        if repetido:
            raise ValueError(f"Ya existe un método llamado «{nombre}».")
        c.execute("UPDATE metodos_pago SET nombre = ?, moneda = ?, "
                  "actualizado_en = ?, sincronizado_en = NULL WHERE id = ?",
                  (nombre, moneda, ahora(), metodo_id))
        c.commit()


def desactivar_metodo(metodo_id):
    """Borrado logico: las ventas viejas lo siguieron usando y su nombre quedo
    congelado en `venta_pagos`, asi que el historial no se toca."""
    with _candado:
        c = conexion()
        activos = c.execute(
            "SELECT COUNT(*) AS n FROM metodos_pago WHERE activo = 1"
        ).fetchone()["n"]
        if activos <= 1:
            raise ValueError("Tiene que quedar al menos un método de pago.")
        c.execute("UPDATE metodos_pago SET activo = 0, actualizado_en = ?, "
                  "sincronizado_en = NULL WHERE id = ?", (ahora(), metodo_id))
        c.commit()


# --------------------------------------------------------------------------
# Ventas
# --------------------------------------------------------------------------

class SinExistencia(Exception):
    """Se quiso vender mas de lo que hay. El mensaje es para mostrarlo."""


class PagoNoCuadra(Exception):
    """El reparto entre metodos no suma el total. El mensaje es para mostrarlo."""


def _preparar_pagos(c, pagos, total, tasa):
    """Pasa cada pago a dólares y comprueba que el reparto cuadre con el total.

    **La regla es estricta: si no cuadra, la venta no se registra.** Es la lección
    de SELL-B, donde un reparto que no cerraba se guardaba igual y después nadie
    sabía cuál de los dos números creer. Es preferible que la vendedora corrija un
    número en el momento a que el historial quede mintiendo.

    El redondeo del último pago absorbe el resto: dividir bolívares entre la tasa
    da fracciones de centavo, y sin este ajuste la suma de los pagos y el total de
    la factura diferirían en un centavo cada tanto.
    """
    if not pagos:
        return []

    preparados = []
    suma = 0.0
    for p in pagos:
        monto = float(p["monto"])
        if monto <= 0:
            raise PagoNoCuadra("Cada pago tiene que ser mayor que cero.")
        metodo = c.execute("SELECT * FROM metodos_pago WHERE id = ?",
                           (p["metodo_id"],)).fetchone()
        if metodo is None:
            raise PagoNoCuadra("Uno de los métodos de pago ya no existe.")
        monto_usd = monto if metodo["moneda"] == "USD" else monto / tasa
        suma += monto_usd
        preparados.append({
            "metodo_id": metodo["id"],
            "metodo_nombre": metodo["nombre"],
            "moneda": metodo["moneda"],
            "monto": monto,
            "monto_usd": round(monto_usd, 2),
        })

    tolerancia = 0.01 * max(1, len(preparados))
    if abs(suma - total) > tolerancia:
        falta = total - suma
        if falta > 0:
            raise PagoNoCuadra(f"Faltan $ {falta:,.2f} por repartir.")
        raise PagoNoCuadra(f"El pago se pasa por $ {-falta:,.2f}.")

    resto = round(total - sum(x["monto_usd"] for x in preparados), 2)
    if resto:
        preparados[-1]["monto_usd"] = round(preparados[-1]["monto_usd"] + resto, 2)
    return preparados


def registrar_venta(items, tasa_usada, tipo="contado", cliente_id=None,
                    fecha_pago_prevista=None, pagos=None):
    """Registra una venta completa. Entra entera o no entra.

    `items` es una lista de `{"producto_id": ..., "cantidad": ...}`.

    Toca tres tablas —`ventas`, `venta_lineas` y `movimientos_inventario`— y las
    tres tienen que quedar coherentes. Si algo falla a mitad de camino, se deshace
    todo: una venta con lineas pero sin descuento de stock dejaria el inventario
    mintiendo para siempre.

    **El precio, el costo y el nombre se copian a la linea.** Si el margen historico
    se calculara con el costo actual del producto, el dia que se recompre mas caro
    se reescribiria la ganancia de meses pasados.

    **La tasa tambien se congela.** Asi el total en bolivares de esta venta no se
    mueve nunca mas, aunque la tasa cambie manana.
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

    venta_id = nuevo_id()
    momento = ahora()

    with _candado:
        c = conexion()
        try:
            c.execute("BEGIN")

            lineas = []
            total = 0.0
            for producto_id, cantidad in juntos.items():
                p = c.execute(
                    "SELECT id, nombre, precio_usd, costo_usd, stock, activo "
                    "FROM productos WHERE id = ?", (producto_id,)).fetchone()
                if p is None or not p["activo"]:
                    raise ValueError("Uno de los productos ya no existe.")
                # La comprobacion va aca adentro y no en la pantalla: entre que se
                # arma el carrito y se confirma, el stock pudo cambiar.
                if float(p["stock"]) < cantidad:
                    raise SinExistencia(
                        f"«{p['nombre']}»: quedan {float(p['stock']):g} y se "
                        f"quieren vender {cantidad:g}.")
                subtotal = cantidad * float(p["precio_usd"])
                total += subtotal
                lineas.append((p, cantidad))

            total = round(total, 2)
            # El reparto se comprueba **antes** de escribir nada: si no cuadra, la
            # excepcion sale de aca y la transaccion no llego a tocar el stock.
            pagos_listos = _preparar_pagos(c, pagos, total, float(tasa_usada))

            correlativo = c.execute(
                "SELECT COALESCE(MAX(correlativo), 0) + 1 AS n FROM ventas"
            ).fetchone()["n"]

            c.execute(
                "INSERT INTO ventas (id, correlativo, cliente_id, fecha, tipo, "
                "total_usd, tasa_usada, fecha_pago_prevista, estado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'activa')",
                (venta_id, correlativo, cliente_id, momento, tipo, total,
                 float(tasa_usada), fecha_pago_prevista))

            for pago in pagos_listos:
                # El nombre del metodo se congela igual que el del producto: si
                # manana se renombra "Pago movil" a "Pago movil Banesco", las
                # ventas viejas tienen que seguir diciendo lo que decian.
                c.execute(
                    "INSERT INTO venta_pagos (id, venta_id, metodo_id, "
                    "metodo_nombre, moneda, monto, monto_usd) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (nuevo_id(), venta_id, pago["metodo_id"], pago["metodo_nombre"],
                     pago["moneda"], pago["monto"], pago["monto_usd"]))

            for p, cantidad in lineas:
                c.execute(
                    "INSERT INTO venta_lineas (id, venta_id, producto_id, "
                    "nombre_congelado, cantidad, precio_unit_usd, costo_unit_usd) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (nuevo_id(), venta_id, p["id"], p["nombre"], cantidad,
                     float(p["precio_usd"]), float(p["costo_usd"])))
                _mover(c, p["id"], -cantidad, "venta", referencia_id=venta_id)

            c.commit()
        except Exception:
            c.rollback()
            raise

    return {"id": venta_id, "correlativo": correlativo, "total_usd": total,
            "tasa_usada": float(tasa_usada)}


def anular_venta(venta_id):
    """Marca la venta como anulada y devuelve la mercancia al inventario.

    No se borra ni se edita: las ventas son append-only. La devolucion del stock se
    hace con **movimientos nuevos en sentido contrario**, no deshaciendo los
    viejos, para que el historial siga contando lo que de verdad paso.
    """
    with _candado:
        c = conexion()
        try:
            c.execute("BEGIN")
            v = c.execute("SELECT estado FROM ventas WHERE id = ?",
                          (venta_id,)).fetchone()
            if v is None:
                raise ValueError("Esa venta no existe.")
            if v["estado"] == "anulada":
                raise ValueError("Esa venta ya estaba anulada.")
            abonado = c.execute(
                "SELECT COALESCE(SUM(monto_usd), 0) AS n "
                "FROM abono_aplicaciones WHERE venta_id = ?",
                (venta_id,)).fetchone()["n"]
            if abonado:
                # Anularla dejaria abonos apuntando a una factura que ya no
                # cuenta, y el saldo del cliente quedaria mal para siempre.
                raise ValueError(
                    f"Esa venta ya tiene $ {abonado:,.2f} abonados. "
                    f"No se puede anular.")

            for linea in c.execute(
                    "SELECT producto_id, cantidad FROM venta_lineas "
                    "WHERE venta_id = ?", (venta_id,)).fetchall():
                _mover(c, linea["producto_id"], float(linea["cantidad"]),
                       "ajuste", referencia_id=venta_id,
                       nota="Devolución por venta anulada")

            c.execute("UPDATE ventas SET estado = 'anulada', "
                      "sincronizado_en = NULL WHERE id = ?", (venta_id,))
            c.commit()
        except Exception:
            c.rollback()
            raise


def obtener_venta(venta_id):
    with _candado:
        c = conexion()
        venta = c.execute("SELECT * FROM ventas WHERE id = ?",
                          (venta_id,)).fetchone()
        if venta is None:
            return None, []
        lineas = c.execute("SELECT * FROM venta_lineas WHERE venta_id = ?",
                           (venta_id,)).fetchall()
        return venta, lineas


def pagos_de_venta(venta_id):
    with _candado:
        return conexion().execute(
            "SELECT * FROM venta_pagos WHERE venta_id = ?", (venta_id,)).fetchall()


def desglose_de_hoy():
    return desglose_de_pagos(_inicio_del_dia_utc(), None)


def desglose_de_pagos(desde, hasta=None):
    """Cuanto entro por cada metodo. Es lo que hace falta para cuadrar la caja: el
    efectivo se cuenta contra el efectivo y el pago movil contra el banco.

    Cada moneda se suma en la suya, sin convertir; `monto_usd` va aparte para poder
    comparar entre metodos.
    """
    tope = hasta or "9999"
    with _candado:
        return conexion().execute(
            "SELECT p.metodo_nombre, p.moneda, "
            "       SUM(p.monto) AS monto, SUM(p.monto_usd) AS monto_usd, "
            "       COUNT(*) AS veces "
            "FROM venta_pagos p JOIN ventas v ON v.id = p.venta_id "
            "WHERE v.fecha >= ? AND v.fecha < ? AND v.estado = 'activa' "
            "GROUP BY p.metodo_nombre, p.moneda "
            "ORDER BY monto_usd DESC", (desde, tope)).fetchall()


def listar_ventas(desde=None, hasta=None, limite=40):
    """El historial, de la mas nueva a la mas vieja.

    Sin rango devuelve **todas**, que es lo que hace falta para el historial
    completo. Las fechas se guardan en UTC, asi que quien llama convierte primero
    el dia local con `rango()` o `_inicio_del_dia_utc()`.
    """
    sql = ["SELECT * FROM ventas WHERE 1 = 1"]
    args = []
    if desde:
        sql.append("AND fecha >= ?")
        args.append(desde)
    if hasta:
        sql.append("AND fecha < ?")
        args.append(hasta)
    # `correlativo` desempata: dos ventas del mismo milisegundo tienen que salir en
    # el orden en que se registraron.
    sql.append("ORDER BY fecha DESC, correlativo DESC LIMIT ?")
    args.append(limite)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchall()


def contar_ventas(desde=None, hasta=None):
    sql = ["SELECT COUNT(*) AS n FROM ventas WHERE 1 = 1"]
    args = []
    if desde:
        sql.append("AND fecha >= ?")
        args.append(desde)
    if hasta:
        sql.append("AND fecha < ?")
        args.append(hasta)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchone()["n"]


def resumen_ventas(desde=None, hasta=None):
    """Cuantas y cuanto, contando solo las activas: una venta anulada no ingreso."""
    sql = ["SELECT COUNT(*) AS ventas, COALESCE(SUM(total_usd), 0) AS ingreso "
           "FROM ventas WHERE estado = 'activa'"]
    args = []
    if desde:
        sql.append("AND fecha >= ?")
        args.append(desde)
    if hasta:
        sql.append("AND fecha < ?")
        args.append(hasta)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchone()


def ventas_de_hoy(limite=50):
    return listar_ventas(_inicio_del_dia_utc(), None, limite)


def resumen_de_hoy():
    return resumen_ventas(_inicio_del_dia_utc(), None)


# --------------------------------------------------------------------------
# Cuentas por cobrar
# --------------------------------------------------------------------------

# Por debajo de medio centavo se considera saldada: dividir bolivares entre la tasa
# deja restos minusculos, y sin este margen quedarian facturas "abiertas" por
# 0,003 dolares que nadie puede terminar de pagar.
CENTAVO = 0.005

_SQL_PENDIENTES = """
SELECT v.cliente_id, v.id, v.correlativo, v.fecha, v.fecha_pago_prevista,
       v.total_usd,
       COALESCE(SUM(a.monto_usd), 0) AS abonado,
       v.total_usd - COALESCE(SUM(a.monto_usd), 0) AS restante
FROM ventas v
LEFT JOIN abono_aplicaciones a ON a.venta_id = v.id
WHERE v.tipo = 'credito' AND v.estado = 'activa'
GROUP BY v.id
HAVING restante > :centavo
"""

# El orden es `fecha, correlativo`. La fecha se guarda hasta el segundo, asi
# que dos facturas cargadas seguidas empatan y el orden quedaria a merced del
# motor. El correlativo desempata porque siempre avanza.


def facturas_pendientes(cliente_id):
    """Las facturas abiertas de un cliente, **de la mas vieja a la mas nueva**.
    Ese orden es el que usa el reparto del abono."""
    with _candado:
        return conexion().execute(
            _SQL_PENDIENTES + " AND v.cliente_id = :cliente "
            "ORDER BY v.fecha, v.correlativo",
            {"centavo": CENTAVO, "cliente": cliente_id}).fetchall()


def saldo_cliente(cliente_id):
    return round(sum(float(f["restante"]) for f in facturas_pendientes(cliente_id)), 2)


def clientes_con_saldo():
    """Quien debe, cuanto, y cual es su vencimiento mas proximo.

    Ordenados por vencimiento: primero lo vencido, despues lo que vence pronto, y
    al final lo que no tiene fecha puesta.
    """
    with _candado:
        return conexion().execute(
            f"WITH pendientes AS ({_SQL_PENDIENTES}) "
            "SELECT c.id, c.nombre, c.telefono, "
            "       ROUND(SUM(p.restante), 2) AS saldo, "
            "       MIN(p.fecha_pago_prevista) AS vence, "
            "       COUNT(*) AS facturas "
            "FROM clientes c JOIN pendientes p ON p.cliente_id = c.id "
            "WHERE c.activo = 1 "
            "GROUP BY c.id "
            "ORDER BY vence IS NULL, vence, c.nombre COLLATE NOCASE",
            {"centavo": CENTAVO}).fetchall()


def total_por_cobrar():
    """El credito que esta en la calle: facturado y todavia no cobrado.

    **No depende del periodo.** Las demas metricas miden un tramo de tiempo (lo
    vendido esta semana, los gastos de este mes); esto es una foto del momento: lo
    que se debe hoy, sin importar cuando se vendio. Hay que decirlo en la pantalla o
    se lee como si fuera del periodo elegido.

    Se separa lo vencido porque no es lo mismo tener $500 en la calle todos al dia
    que tener $500 de los cuales $300 ya se pasaron de fecha.
    """
    hoy = datetime.now().astimezone().date().isoformat()
    with _candado:
        fila = conexion().execute(
            f"WITH pendientes AS ({_SQL_PENDIENTES}) "
            "SELECT COALESCE(ROUND(SUM(restante), 2), 0) AS total, "
            "       COALESCE(ROUND(SUM(CASE WHEN fecha_pago_prevista IS NOT NULL "
            "                     AND fecha_pago_prevista < :hoy THEN restante "
            "                     ELSE 0 END), 2), 0) AS vencido, "
            "       COUNT(DISTINCT cliente_id) AS clientes, "
            "       COUNT(*) AS facturas "
            "FROM pendientes", {"centavo": CENTAVO, "hoy": hoy}).fetchone()
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
    de dejar saldo negativo.
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

    with _candado:
        c = conexion()
        try:
            c.execute("BEGIN")

            pendientes = c.execute(
                _SQL_PENDIENTES + " AND v.cliente_id = :cliente "
            "ORDER BY v.fecha, v.correlativo",
                {"centavo": CENTAVO, "cliente": cliente_id}).fetchall()
            if not pendientes:
                raise ValueError("Ese cliente no tiene nada pendiente.")

            saldo = round(sum(float(f["restante"]) for f in pendientes), 2)
            if monto_usd - saldo > 0.01:
                raise ValueError(
                    f"El abono se pasa: debe $ {saldo:,.2f} y se están "
                    f"recibiendo $ {monto_usd:,.2f}.")
            # Diferencia de centavos: se ajusta al restante exacto para no dejar
            # saldo negativo por un redondeo.
            monto_usd = min(monto_usd, saldo)

            metodo = None
            if metodo_id:
                metodo = c.execute("SELECT * FROM metodos_pago WHERE id = ?",
                                   (metodo_id,)).fetchone()

            abono_id = nuevo_id()
            c.execute(
                "INSERT INTO abonos (id, cliente_id, fecha, monto_usd, "
                "moneda_recibida, monto_recibido, tasa_usada, metodo_id, "
                "metodo_nombre, nota) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (abono_id, cliente_id, ahora(), round(monto_usd, 2), moneda,
                 monto_recibido, tasa, metodo["id"] if metodo else None,
                 metodo["nombre"] if metodo else "", (nota or "").strip()))

            por_repartir = round(monto_usd, 2)
            aplicadas = []
            for factura in pendientes:
                if por_repartir <= CENTAVO:
                    break
                trozo = round(min(por_repartir, float(factura["restante"])), 2)
                c.execute(
                    "INSERT INTO abono_aplicaciones (id, abono_id, venta_id, "
                    "monto_usd) VALUES (?, ?, ?, ?)",
                    (nuevo_id(), abono_id, factura["id"], trozo))
                por_repartir = round(por_repartir - trozo, 2)
                aplicadas.append({
                    "correlativo": factura["correlativo"],
                    "monto": trozo,
                    "saldada": trozo >= float(factura["restante"]) - CENTAVO,
                })

            c.commit()
        except Exception:
            c.rollback()
            raise

    return {"id": abono_id, "monto_usd": round(monto_usd, 2),
            "aplicadas": aplicadas,
            "saldo_restante": round(saldo - monto_usd, 2)}


def abonos_de_cliente(cliente_id, limite=30):
    with _candado:
        return conexion().execute(
            # `rowid` desempata: dos abonos del mismo instante tienen que salir
            # en el orden en que se registraron, no en uno cualquiera.
            "SELECT * FROM abonos WHERE cliente_id = ? "
            "ORDER BY fecha DESC, rowid DESC LIMIT ?",
            (cliente_id, limite)).fetchall()


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

    gasto_id = nuevo_id()
    with _candado:
        c = conexion()
        c.execute(
            "INSERT INTO gastos (id, fecha, categoria, descripcion, monto_usd, "
            "moneda_pagada, monto_pagado, tasa_usada, activo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (gasto_id, ahora(), categoria, (descripcion or "").strip(),
             round(monto_usd, 2), moneda, monto_pagado, tasa))
        c.commit()
    return gasto_id


def eliminar_gasto(gasto_id):
    with _candado:
        c = conexion()
        c.execute("UPDATE gastos SET activo = 0, sincronizado_en = NULL "
                  "WHERE id = ?", (gasto_id,))
        c.commit()


def listar_gastos(desde=None, hasta=None, limite=100):
    sql = ["SELECT * FROM gastos WHERE activo = 1"]
    args = []
    if desde:
        sql.append("AND fecha >= ?")
        args.append(desde)
    if hasta:
        sql.append("AND fecha < ?")
        args.append(hasta)
    sql.append("ORDER BY fecha DESC, rowid DESC LIMIT ?")
    args.append(limite)
    with _candado:
        return conexion().execute(" ".join(sql), args).fetchall()


def categorias_de_gasto():
    """Las que ya se usaron, de la mas usada a la menos.

    La categoria es texto libre, pero el campo sugiere lo ya escrito: sin eso, las
    metricas terminan contando "Delivery", "delivery" y "deliveri" como tres cosas
    distintas.
    """
    with _candado:
        return [f["categoria"] for f in conexion().execute(
            "SELECT categoria, COUNT(*) AS veces FROM gastos WHERE activo = 1 "
            "GROUP BY categoria COLLATE NOCASE ORDER BY veces DESC, categoria"
        ).fetchall()]


# --------------------------------------------------------------------------
# Metricas
# --------------------------------------------------------------------------

PERIODOS = ("hoy", "semana", "mes")
PERIODOS_TODOS = PERIODOS + ("semana_pasada",)


def rango(periodo):
    """Devuelve `(desde, hasta, etiqueta)` en ISO UTC.

    El rango se calcula con la fecha **local**, que es la que la persona tiene en la
    cabeza: "esta semana" empieza el lunes de su lunes, no el de UTC.
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
    with _candado:
        c = conexion()
        venta = c.execute(
            "SELECT COUNT(*) AS ventas, COALESCE(SUM(total_usd), 0) AS vendido "
            "FROM ventas WHERE fecha >= ? AND fecha < ? AND estado = 'activa'",
            (desde, hasta)).fetchone()
        costo = c.execute(
            "SELECT COALESCE(SUM(l.cantidad * l.costo_unit_usd), 0) AS costo "
            "FROM venta_lineas l JOIN ventas v ON v.id = l.venta_id "
            "WHERE v.fecha >= ? AND v.fecha < ? AND v.estado = 'activa'",
            (desde, hasta)).fetchone()["costo"]
        gastos = c.execute(
            "SELECT COALESCE(SUM(monto_usd), 0) AS gastos FROM gastos "
            "WHERE fecha >= ? AND fecha < ? AND activo = 1",
            (desde, hasta)).fetchone()["gastos"]
        cobrado_ventas = c.execute(
            "SELECT COALESCE(SUM(p.monto_usd), 0) AS n FROM venta_pagos p "
            "JOIN ventas v ON v.id = p.venta_id "
            "WHERE v.fecha >= ? AND v.fecha < ? AND v.estado = 'activa'",
            (desde, hasta)).fetchone()["n"]
        cobrado_abonos = c.execute(
            "SELECT COALESCE(SUM(monto_usd), 0) AS n FROM abonos "
            "WHERE fecha >= ? AND fecha < ?", (desde, hasta)).fetchone()["n"]
        sin_costo = c.execute(
            "SELECT COUNT(*) AS n FROM productos "
            "WHERE activo = 1 AND costo_usd <= 0").fetchone()["n"]

    vendido = float(venta["vendido"])
    costo = float(costo)
    bruta = vendido - costo
    neta = bruta - float(gastos)
    return {
        "periodo": periodo,
        "etiqueta": etiqueta,
        "desde": desde,
        "hasta": hasta,
        "ventas": venta["ventas"],
        "vendido": round(vendido, 2),
        "costo": round(costo, 2),
        "bruta": round(bruta, 2),
        "gastos": round(float(gastos), 2),
        "neta": round(neta, 2),
        "margen": round(neta / vendido * 100, 1) if vendido else 0.0,
        "entro_en_caja": round(float(cobrado_ventas) + float(cobrado_abonos), 2),
        # Sin el costo cargado, el margen de ese producto sale inflado: la ganancia
        # que muestra la pantalla seria mayor que la real.
        "sin_costo": sin_costo,
    }


def top_productos(periodo="semana", limite=5, desde=None, hasta=None):
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    with _candado:
        return conexion().execute(
            "SELECT l.nombre_congelado AS nombre, "
            "       SUM(l.cantidad) AS unidades, "
            "       ROUND(SUM(l.cantidad * l.precio_unit_usd), 2) AS vendido, "
            "       ROUND(SUM(l.cantidad * (l.precio_unit_usd - l.costo_unit_usd)), 2)"
            "           AS ganancia "
            "FROM venta_lineas l JOIN ventas v ON v.id = l.venta_id "
            "WHERE v.fecha >= ? AND v.fecha < ? AND v.estado = 'activa' "
            "GROUP BY l.nombre_congelado "
            "ORDER BY vendido DESC LIMIT ?", (desde, hasta, limite)).fetchall()


def gastos_por_categoria(periodo="semana", desde=None, hasta=None):
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    with _candado:
        return conexion().execute(
            "SELECT categoria, COUNT(*) AS veces, "
            "       ROUND(SUM(monto_usd), 2) AS total "
            "FROM gastos WHERE fecha >= ? AND fecha < ? AND activo = 1 "
            "GROUP BY categoria COLLATE NOCASE ORDER BY total DESC",
            (desde, hasta)).fetchall()


def serie_diaria(periodo="semana", desde=None, hasta=None):
    """Un punto por dia del periodo, **incluidos los dias sin ventas**.

    Rellenar los vacios aca y no en la pantalla evita que el grafico invente un dia
    de mas o se salte uno: la lista que sale ya tiene exactamente los dias que hay
    que dibujar.
    """
    if desde is None or hasta is None:
        desde, hasta, _ = rango(periodo)
    with _candado:
        filas = conexion().execute(
            "SELECT v.fecha, v.total_usd, "
            "       (SELECT COALESCE(SUM(l.cantidad * l.costo_unit_usd), 0) "
            "        FROM venta_lineas l WHERE l.venta_id = v.id) AS costo "
            "FROM ventas v "
            "WHERE v.fecha >= ? AND v.fecha < ? AND v.estado = 'activa'",
            (desde, hasta)).fetchall()

    # **El agrupado se hace en Python, no en SQL.** `date(v.fecha)` daria el dia
    # UTC, y las fechas se guardan en UTC: en Venezuela (UTC-4) todo lo vendido
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
# Resumen
# --------------------------------------------------------------------------

def resumen_inventario():
    with _candado:
        return conexion().execute(
            "SELECT COUNT(*) AS productos, "
            "       COALESCE(SUM(stock), 0) AS unidades, "
            "       COALESCE(SUM(stock * costo_usd), 0) AS valor_costo, "
            "       SUM(CASE WHEN costo_usd <= 0 THEN 1 ELSE 0 END) AS sin_costo, "
            "       SUM(CASE WHEN stock <= 0 THEN 1 ELSE 0 END) AS sin_stock, "
            "       SUM(CASE WHEN precio_usd < costo_usd THEN 1 ELSE 0 END) "
            "           AS bajo_costo "
            "FROM productos WHERE activo = 1").fetchone()
