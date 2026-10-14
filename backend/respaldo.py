"""El respaldo: toda la base en un archivo, sin nube y sin cuentas.

**Por que un archivo y no un servidor.** La copia en Neon se saco a proposito: el
telefono es el unico dueno de los datos, y un respaldo que depende de una cuenta,
de internet y de que alguien pague el hospedaje es un respaldo que el dia malo no
esta. Un archivo se manda por correo, se guarda en el computador, se copia a un
pendrive. Si el telefono se pierde, se reinstala la aplicacion, se abre el archivo
y todo vuelve.

**Que lleva adentro.** La base entera: productos, fotos, ventas, clientes, abonos,
gastos y la configuracion de la tienda. Las fotos viven dentro de la base, asi que
no hay nada suelto que se pueda olvidar.

**Que NO lleva.** El PIN ni la clave del correo. Estan cifradas con una llave que
sale del PIN de *este* telefono, asi que en otro no servirian de nada; al restaurar
se vuelven a escribir una vez. Eso tambien significa que **el archivo no sirve para
entrar a la aplicacion de nadie**: sin el PIN no abre.

**La copia se hace con el motor, no copiando el archivo a mano.** La base trabaja
en modo WAL: lo ultimo escrito puede estar todavia en un archivo aparte, y copiar
solo el principal da una copia a la que le faltan las ultimas ventas. `backup()` de
sqlite3 resuelve justo eso —espera a que la base este consistente y la escribe
entera—, ademas de no romperse si alguien guarda algo mientras tanto.
"""

import os
import sqlite3
import tempfile
from datetime import datetime

from backend import almacenamiento
from backend import basedatos

# Lo que tiene que estar adentro para considerarlo un respaldo de esta aplicacion.
# Si falta una sola, el archivo es de otro programa o esta roto.
TABLAS = ("productos", "ventas", "venta_lineas", "clientes", "gastos",
          "metodos_pago", "configuracion")


class ErrorDeRespaldo(Exception):
    """Fallo al armar o al restaurar. El mensaje esta escrito para mostrarlo."""


def nombre_sugerido(cuando=None):
    """`respaldo-shopstores-2026-10-10.db`. La fecha va primero en anio-mes-dia
    para que los respaldos se ordenen solos en cualquier carpeta."""
    cuando = cuando or datetime.now().astimezone()
    return f"respaldo-shopstores-{cuando.strftime('%Y-%m-%d')}.db"


def armar():
    """Devuelve los bytes de una copia consistente de la base."""
    destino = os.path.join(tempfile.mkdtemp(prefix="respaldo_"), "copia.db")
    try:
        copia = sqlite3.connect(destino)
        try:
            basedatos.conexion().backup(copia)
        finally:
            copia.close()
        with open(destino, "rb") as archivo:
            return archivo.read()
    except sqlite3.Error as ex:
        raise ErrorDeRespaldo(f"No se pudo armar el respaldo: {ex}")
    finally:
        try:
            os.remove(destino)
            os.rmdir(os.path.dirname(destino))
        except OSError:
            pass


def revisar(datos):
    """Comprueba que los bytes sean una base de esta aplicacion.

    Se mira **antes** de tocar nada. Restaurar reemplaza todo lo que hay en el
    telefono: hacerlo con un archivo equivocado no se deshace.

    Devuelve un resumen para poder decir que trae, que es lo que permite a la
    persona darse cuenta de que eligio el archivo que no era.
    """
    if not datos or datos[:16] != b"SQLite format 3\x00":
        raise ErrorDeRespaldo("Ese archivo no es un respaldo de la aplicacion.")

    carpeta = tempfile.mkdtemp(prefix="revisar_")
    ruta = os.path.join(carpeta, "copia.db")
    try:
        with open(ruta, "wb") as archivo:
            archivo.write(datos)
        c = sqlite3.connect(ruta)
        c.row_factory = sqlite3.Row
        try:
            hay = {f["name"] for f in c.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            faltan = [t for t in TABLAS if t not in hay]
            if faltan:
                raise ErrorDeRespaldo(
                    "Ese archivo no es un respaldo de la aplicacion.")
            return {
                "productos": c.execute(
                    "SELECT COUNT(*) FROM productos WHERE activo = 1"
                ).fetchone()[0],
                "ventas": c.execute("SELECT COUNT(*) FROM ventas").fetchone()[0],
                "clientes": c.execute(
                    "SELECT COUNT(*) FROM clientes WHERE activo = 1"
                ).fetchone()[0],
            }
        finally:
            c.close()
    except sqlite3.Error:
        raise ErrorDeRespaldo("Ese archivo no se puede leer: esta danado.")
    finally:
        for sobra in (ruta, carpeta):
            try:
                os.remove(sobra) if os.path.isfile(sobra) else os.rmdir(sobra)
            except OSError:
                pass


def restaurar(datos):
    """Reemplaza la base del telefono por la del archivo. No se deshace.

    Se revisa primero, se guarda la base actual al lado con el nombre terminado en
    `.anterior` —por si el archivo elegido resulta ser viejo— y recien ahi se
    escribe la nueva.
    """
    resumen = revisar(datos)

    basedatos.cerrar()
    ruta = almacenamiento.RUTA_BASE_DATOS
    anterior = ruta + ".anterior"
    try:
        if os.path.exists(ruta):
            if os.path.exists(anterior):
                os.remove(anterior)
            os.replace(ruta, anterior)
        with open(ruta, "wb") as archivo:
            archivo.write(datos)
        # Los archivos del modo WAL son de la base vieja: si se quedan, el motor
        # intenta aplicarlos encima de la nueva.
        for sobra in (ruta + "-wal", ruta + "-shm"):
            if os.path.exists(sobra):
                os.remove(sobra)
    except OSError as ex:
        raise ErrorDeRespaldo(f"No se pudo escribir la base restaurada: {ex}")

    # Se vuelve a abrir aca mismo: si el archivo estuviera roto, es mejor saberlo
    # ahora y no cuando la persona toque la primera pantalla.
    try:
        basedatos.conexion()
    except sqlite3.Error as ex:
        raise ErrorDeRespaldo(f"La base restaurada no abre: {ex}")
    return resumen
