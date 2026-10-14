"""Donde vive todo en el disco, y la configuracion suelta.

En Android la unica ruta escribible es la que Flet inyecta en
`FLET_APP_STORAGE_DATA`. En Windows no existe esa variable, asi que se usa una
carpeta `datos/` al lado del programa. Todo lo que escriba la app tiene que pasar
por aca: si alguna vez se escribe en el directorio actual, en el telefono falla.
"""

import json
import os

# `..` porque este archivo vive en `backend/` y la carpeta de datos va al lado
# del programa, no dentro del backend.
BASE = os.environ.get("FLET_APP_STORAGE_DATA") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")

os.makedirs(BASE, exist_ok=True)

RUTA_BASE_DATOS = os.path.join(BASE, "shopstores.db")
RUTA_CONFIG = os.path.join(BASE, "config.json")

# El nombre que tenia la base antes de que la aplicacion se llamara ShopStore's.
_NOMBRE_ANTERIOR = os.path.join(BASE, "vanesstore.db")


def _heredar_la_base_vieja():
    """Si queda una base con el nombre anterior, se adopta.

    Nace de un error de verdad: al renombrar la aplicacion se cambio tambien el
    nombre del archivo, y la siguiente vez que abrio **no encontro nada y empezo
    de cero**. Los datos no se habian perdido —el archivo viejo seguia ahi al
    lado— pero en pantalla se veia exactamente igual que perderlos.

    Solo actua si **no hay** base con el nombre nuevo: si ya existe una, aunque
    este vacia, es la que manda. Pisar algo que la persona ya empezo a usar seria
    peor que no hacer nada.
    """
    if os.path.exists(RUTA_BASE_DATOS) or not os.path.exists(_NOMBRE_ANTERIOR):
        return
    try:
        os.replace(_NOMBRE_ANTERIOR, RUTA_BASE_DATOS)
        # Los archivos del modo WAL acompanan a la base; sin ellos se perderia lo
        # ultimo que se escribio antes de cerrar.
        for sufijo in ("-wal", "-shm"):
            viejo = _NOMBRE_ANTERIOR + sufijo
            if os.path.exists(viejo):
                os.replace(viejo, RUTA_BASE_DATOS + sufijo)
    except OSError:
        # Si no se puede mover, la aplicacion abre igual con una base nueva. El
        # archivo viejo se queda donde esta y no se pierde nada.
        pass


_heredar_la_base_vieja()


def _leer():
    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        # Un config corrupto o inexistente no puede impedir que la app abra: se
        # empieza de cero y el primer guardado lo reescribe.
        return {}


def _escribir(datos):
    tmp = RUTA_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)
    # Reemplazo atomico: si el telefono se apaga a mitad de la escritura, queda el
    # archivo viejo entero en vez de uno a medias.
    os.replace(tmp, RUTA_CONFIG)
    if al_cambiar is not None:
        al_cambiar(datos)


# **En el navegador, el disco no dura.** Lo que Python escribe ahi vive en la
# memoria de la pestana: al recargar, `config.json` —con la sesion y el PIN—
# desaparece. Por eso, en la version web, el frontend pone aca una funcion que
# copia todo a la memoria propia del navegador cada vez que algo cambia, y al
# abrir lo devuelve con `cargar`. En Android y en la computadora queda en `None`:
# ahi el archivo si dura.
al_cambiar = None


def todo():
    return _leer()


def cargar(datos):
    """Reemplaza todo por `datos`. Solo para lo que recupera el navegador al abrir."""
    tmp = RUTA_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos or {}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, RUTA_CONFIG)


def obtener(clave, por_defecto=None):
    return _leer().get(clave, por_defecto)


def guardar(clave, valor):
    datos = _leer()
    datos[clave] = valor
    _escribir(datos)


def borrar(clave):
    datos = _leer()
    if clave in datos:
        del datos[clave]
        _escribir(datos)
