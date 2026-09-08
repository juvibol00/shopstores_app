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

RUTA_BASE_DATOS = os.path.join(BASE, "vanesstore.db")
RUTA_CONFIG = os.path.join(BASE, "config.json")


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
