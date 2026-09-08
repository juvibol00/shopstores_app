"""El respaldo en Neon.

**La base del teléfono es la verdad. Esto es la copia que sobrevive al teléfono.**
Se empuja en una sola dirección; la bajada existe solo para restaurar en un teléfono
nuevo. Como escribe un solo dispositivo, no hay nada que reconciliar: no hay
conflictos, ni empates, ni stock que recalcular desde dos lados. Toda la complejidad
de la Fase 4 de SELL-B nacía de que las dos copias escribían.

Tres decisiones que conviene entender:

**El esquema de Postgres se genera leyendo el de SQLite.** No hay una segunda
definición escrita a mano que pueda quedar desfasada: si mañana se agrega una
columna, la copia la recoge sola. Es la misma idea de no tener dos implementaciones
de la misma regla.

**Las tablas de la copia no llevan claves foráneas.** Es un espejo, no una base
operativa: la integridad la garantiza el origen. Con restricciones, el orden de
empuje se volvería crítico y un lote a medias podría fallar entero por una fila que
todavía no subió.

**Lo pendiente es `sincronizado_en IS NULL`.** No hace falta una tabla de cola: cada
fila sabe si ya subió. Se marca **después** de que el lote confirma, así que un corte
de red deja las filas pendientes y el siguiente intento las vuelve a mandar.
"""

import ssl
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import pg8000.native

from backend import almacenamiento
from backend import basedatos
from backend import seguridad

# En orden de dependencia. No hace falta para escribir —no hay claves foráneas—
# pero deja la copia coherente en cualquier momento intermedio: nunca hay una
# venta arriba cuyo cliente todavía no subió.
TABLAS = [
    "configuracion",
    "metodos_pago",
    "productos",
    "producto_fotos",
    "movimientos_inventario",
    "clientes",
    "ventas",
    "venta_lineas",
    "venta_pagos",
    "abonos",
    "abono_aplicaciones",
    "gastos",
]

# `configuracion` no tiene `id` ni `sincronizado_en`: es una tabla de clave y valor.
SIN_SEGUIMIENTO = {"configuracion"}

TIPOS = {"TEXT": "TEXT", "REAL": "DOUBLE PRECISION", "INTEGER": "BIGINT",
         "BLOB": "BYTEA"}

# Las fotos pesan; en lotes chicos, un corte de red pierde poco y se reintenta.
LOTE = 25
LOTE_FOTOS = 3


class ErrorDeNube(Exception):
    """Falló el respaldo. El mensaje está escrito para mostrarlo tal cual."""


# --------------------------------------------------------------------------
# La credencial
# --------------------------------------------------------------------------

def configurado():
    return bool(almacenamiento.obtener("neon_cadena"))


def leer_cadena():
    """Descifrada, y solo con la sesión abierta."""
    return seguridad.descifrar(almacenamiento.obtener("neon_cadena"))


def guardar_cadena(cadena):
    piezas = partir_cadena(cadena)      # valida antes de guardar
    almacenamiento.guardar("neon_cadena", seguridad.cifrar(cadena.strip()))
    almacenamiento.guardar("neon_host", piezas["host"])


def olvidar():
    almacenamiento.borrar("neon_cadena")
    almacenamiento.borrar("neon_host")


def host_guardado():
    return almacenamiento.obtener("neon_host", "")


def partir_cadena(cadena):
    """Neon entrega un `postgresql://usuario:clave@host/base?...`.
    pg8000 no recibe URL: hay que darle las piezas por separado."""
    u = urlparse((cadena or "").strip())
    if u.scheme not in ("postgres", "postgresql"):
        raise ErrorDeNube("La cadena tiene que empezar con postgresql://")
    if not (u.hostname and u.username):
        raise ErrorDeNube("A la cadena le falta el host o el usuario.")
    return {
        "host": u.hostname,
        "port": u.port or 5432,
        "user": unquote(u.username),
        "password": unquote(u.password) if u.password else None,
        "database": (u.path or "/").lstrip("/") or u.username,
    }


def _conectar(cadena=None):
    cadena = cadena or leer_cadena()
    if not cadena:
        raise ErrorDeNube("No hay una conexión guardada, o el PIN no la pudo leer. "
                          "Escríbela de nuevo en Configuración.")
    piezas = partir_cadena(cadena)
    try:
        return pg8000.native.Connection(
            user=piezas["user"], password=piezas["password"],
            host=piezas["host"], port=piezas["port"],
            database=piezas["database"],
            ssl_context=ssl.create_default_context(),   # Neon exige TLS siempre
            timeout=30)
    except Exception as ex:
        raise ErrorDeNube(_explicar(ex))


def _explicar(ex):
    """Traduce el fallo a algo que la persona pueda hacer.

    Lo que importa distinguir son **dos situaciones que llevan a acciones
    distintas**: que no se llegue al servidor —revisar la conexión, probar otra
    red— o que el servidor conteste que no —revisar lo que se pegó en
    Configuración—. Todo lo demás sobra en pantalla.

    Nota para quien mantenga esto, **no para la pantalla**: cuando no llega nada y
    el TCP sí conecta, la causa casi siempre es un VPN o el proveedor de internet
    filtrando el puerto de la base. Está explicado en el documento de diseño; ahí
    sirve, y en un mensaje de error no.
    """
    texto = str(ex).lower()
    if "timed out" in texto or "forcib" in texto or "reset" in texto:
        return ("No se pudo conectar con el respaldo. Revisa tu conexión a "
                "internet, o prueba con otra red.")
    if "password" in texto or "authentication" in texto:
        return ("El servidor rechazó la conexión. Revisa lo que pegaste en "
                "Configuración.")
    if "does not exist" in texto:
        return ("Esa base de datos no existe. Revisa lo que pegaste en "
                "Configuración.")
    return "No se pudo conectar con el respaldo. Inténtalo de nuevo más tarde."


# --------------------------------------------------------------------------
# El esquema de la copia
# --------------------------------------------------------------------------

def _columnas(tabla):
    """Las del SQLite local. **Aquí está la única definición del esquema**: la
    copia se genera de esta, así que no pueden quedar desfasadas."""
    with basedatos._candado:
        return [(f["name"], f["type"].upper())
                for f in basedatos.conexion().execute(
                    f"PRAGMA table_info({tabla})").fetchall()]


def _crear_esquema(conexion_nube):
    for tabla in TABLAS:
        columnas = _columnas(tabla)
        clave = "clave" if tabla in SIN_SEGUIMIENTO else "id"
        definiciones = ", ".join(
            f'"{nombre}" {TIPOS.get(tipo, "TEXT")}'
            + (" PRIMARY KEY" if nombre == clave else "")
            for nombre, tipo in columnas)
        conexion_nube.run(f'CREATE TABLE IF NOT EXISTS "{tabla}" ({definiciones})')
        # Una columna agregada despues en el telefono se suma tambien arriba.
        for nombre, tipo in columnas:
            conexion_nube.run(
                f'ALTER TABLE "{tabla}" ADD COLUMN IF NOT EXISTS '
                f'"{nombre}" {TIPOS.get(tipo, "TEXT")}')


# --------------------------------------------------------------------------
# Qué falta subir
# --------------------------------------------------------------------------

def pendientes():
    """Cuántas filas faltan por subir, por tabla. Solo las que quedan."""
    faltan = {}
    with basedatos._candado:
        c = basedatos.conexion()
        for tabla in TABLAS:
            if tabla in SIN_SEGUIMIENTO:
                continue
            n = c.execute(f"SELECT COUNT(*) AS n FROM {tabla} "
                          f"WHERE sincronizado_en IS NULL").fetchone()["n"]
            if n:
                faltan[tabla] = n
    return faltan


def total_pendiente():
    return sum(pendientes().values())


def ultimo_respaldo():
    return basedatos.leer_config("nube_ultimo_respaldo")


# --------------------------------------------------------------------------
# Subir
# --------------------------------------------------------------------------

def respaldar(avisar=None):
    """Empuja todo lo pendiente. Devuelve cuántas filas subieron por tabla.

    `avisar(texto)` se llama entre lotes para poder mostrar el avance: con fotos
    de por medio esto puede tardar y quedarse mudo sería peor que tardar.
    """
    conexion_nube = _conectar()
    subidas = {}
    try:
        _crear_esquema(conexion_nube)

        # `configuracion` se reemplaza entera: son pocas filas y no lleva marca de
        # sincronización, así que no hay forma de saber cuál cambió.
        _volcar_configuracion(conexion_nube)

        for tabla in TABLAS:
            if tabla in SIN_SEGUIMIENTO:
                continue
            n = _subir_tabla(conexion_nube, tabla, avisar)
            if n:
                subidas[tabla] = n

        momento = datetime.now(timezone.utc).isoformat(timespec="seconds")
        basedatos.escribir_config("nube_ultimo_respaldo", momento)
    except ErrorDeNube:
        raise
    except Exception as ex:
        raise ErrorDeNube(_explicar(ex))
    finally:
        try:
            conexion_nube.close()
        except Exception:
            pass
    return subidas


def _volcar_configuracion(conexion_nube):
    with basedatos._candado:
        filas = basedatos.conexion().execute(
            "SELECT clave, valor FROM configuracion").fetchall()
    for f in filas:
        # Los parametros se llaman como las columnas a proposito: con nombres
        # sueltos (`:c`, `:v`) cualquiera que lea esto tiene que ir a buscar cual
        # es cual.
        conexion_nube.run(
            'INSERT INTO "configuracion" ("clave", "valor") '
            'VALUES (:clave, :valor) '
            'ON CONFLICT ("clave") DO UPDATE SET "valor" = EXCLUDED."valor"',
            clave=f["clave"], valor=f["valor"])


def _subir_tabla(conexion_nube, tabla, avisar=None):
    columnas = [n for n, _ in _columnas(tabla)]
    lista = ", ".join(f'"{c}"' for c in columnas)
    valores = ", ".join(f":{c}" for c in columnas)
    actualiza = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in columnas
                          if c != "id")
    sql = (f'INSERT INTO "{tabla}" ({lista}) VALUES ({valores}) '
           f'ON CONFLICT ("id") DO UPDATE SET {actualiza}')

    lote = LOTE_FOTOS if tabla == "producto_fotos" else LOTE
    subidas = 0
    while True:
        with basedatos._candado:
            filas = basedatos.conexion().execute(
                f"SELECT * FROM {tabla} WHERE sincronizado_en IS NULL "
                f"LIMIT {lote}").fetchall()
        if not filas:
            break

        momento = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for fila in filas:
            datos = {c: fila[c] for c in columnas}
            datos["sincronizado_en"] = momento
            conexion_nube.run(sql, **datos)

        # **Se marca después de que el servidor aceptó el lote.** Al revés, un
        # corte de red dejaría filas marcadas como subidas que nunca llegaron.
        with basedatos._candado:
            c = basedatos.conexion()
            c.executemany(
                f"UPDATE {tabla} SET sincronizado_en = ? WHERE id = ?",
                [(momento, f["id"]) for f in filas])
            c.commit()

        subidas += len(filas)
        if avisar:
            avisar(f"{tabla}: {subidas} fila(s)")
    return subidas


# --------------------------------------------------------------------------
# Bajar
# --------------------------------------------------------------------------

def resumen_de_la_copia():
    """Qué hay arriba, para poder decidir antes de restaurar."""
    conexion_nube = _conectar()
    try:
        _crear_esquema(conexion_nube)
        conteo = {}
        for tabla in TABLAS:
            n = conexion_nube.run(f'SELECT COUNT(*) FROM "{tabla}"')[0][0]
            if n:
                conteo[tabla] = n
        return conteo
    except ErrorDeNube:
        raise
    except Exception as ex:
        raise ErrorDeNube(_explicar(ex))
    finally:
        try:
            conexion_nube.close()
        except Exception:
            pass


def restaurar(avisar=None):
    """Trae la copia y **reemplaza** lo que haya en el teléfono.

    Es para un teléfono nuevo o para recuperar uno perdido, no para mezclar: se
    borra lo local y se escribe lo de la nube. Por eso la pantalla lo pregunta dos
    veces y dice exactamente qué se va a perder.
    """
    conexion_nube = _conectar()
    traidas = {}
    try:
        _crear_esquema(conexion_nube)
        with basedatos._candado:
            c = basedatos.conexion()
            try:
                c.execute("BEGIN")
                # En orden inverso: primero lo que depende de otros.
                for tabla in reversed(TABLAS):
                    c.execute(f"DELETE FROM {tabla}")

                for tabla in TABLAS:
                    columnas = [n for n, _ in _columnas(tabla)]
                    lista = ", ".join(f'"{x}"' for x in columnas)
                    filas = conexion_nube.run(
                        f'SELECT {lista} FROM "{tabla}"')
                    if not filas:
                        continue
                    marcas = ", ".join("?" for _ in columnas)
                    c.executemany(
                        f"INSERT INTO {tabla} ({', '.join(columnas)}) "
                        f"VALUES ({marcas})", filas)
                    traidas[tabla] = len(filas)
                    if avisar:
                        avisar(f"{tabla}: {len(filas)} fila(s)")
                c.commit()
            except Exception:
                c.rollback()
                raise
    except ErrorDeNube:
        raise
    except Exception as ex:
        raise ErrorDeNube(f"No se pudo restaurar: {ex}")
    finally:
        try:
            conexion_nube.close()
        except Exception:
            pass
    return traidas


def probar(cadena=None):
    """Conecta y devuelve una línea con lo que respondió el servidor."""
    conexion_nube = _conectar(cadena)
    try:
        version = conexion_nube.run("select version()")[0][0]
        return version.split(" on ")[0]
    except Exception as ex:
        raise ErrorDeNube(_explicar(ex))
    finally:
        try:
            conexion_nube.close()
        except Exception:
            pass
