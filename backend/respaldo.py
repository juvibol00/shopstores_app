"""El respaldo: todo lo de la cuenta en un archivo que se guarda una misma.

Los datos viven en Supabase, pero el plan gratis no deja bajar copias. Este
archivo es lo que protege contra un borrado por error o contra perder la cuenta:
productos con sus fotos, clientes, ventas con sus pagos, abonos, gastos y los
metodos de pago, tal como estan.

Es un `.zip` con dos cosas adentro:

- `datos.json`: cada tabla como una lista, con las fotos en base64. Lo arma una
  sola funcion de Supabase (`exportar_respaldo`), en un solo viaje.
- `LEEME.txt`: que es el archivo y que hacer con el, para quien lo encuentre
  dentro de un año en la carpeta de descargas.

**No lleva la huella del PIN** (no sirve para recuperar nada y facilita
adivinarlo), ni la sesion, ni contrasenas.

**Restaurar reemplaza todo** lo de la cuenta por lo del archivo, no mezcla, y
conserva el perfil (nombre y PIN) de la cuenta donde se restaura. Antes de tocar
nada, `revisar` lee el archivo y dice que trae, para que se vea a tiempo si es el
equivocado.
"""

import io
import json
import zipfile
from datetime import datetime

from backend import basedatos

# Lo que se cuenta en la pantalla para decir que trae el archivo.
LO_QUE_SE_CUENTA = ("productos", "producto_fotos", "clientes", "ventas", "gastos")

NOMBRE_EN_LA_NUBE = "respaldo.zip"

LEEME = """ShopStore's - respaldo

Este archivo es una copia de todo lo que tenias en la aplicacion el dia que lo
bajaste: productos con sus fotos, clientes, ventas con sus pagos, abonos y gastos.

Guardalo en un lugar seguro (Google Drive, iCloud, tu correo). Quien lo tenga
puede ver tus ventas y tus clientes, asi que no lo compartas.

No lleva tu PIN ni tu contrasena.

Los datos estan en datos.json. Si algun dia hay que recuperarlos, ese archivo
tiene todo lo necesario.
"""


def nombre_sugerido(cuando=None):
    """`respaldo-shopstores-2026-10-14.zip`, con la fecha del telefono."""
    dia = (cuando or datetime.now().astimezone()).date().isoformat()
    return f"respaldo-shopstores-{dia}.zip"


def armar():
    """Devuelve `(bytes_del_zip, cuantos)`: el archivo y cuantas filas trae de
    cada cosa importante, para mostrarlo antes de bajarlo."""
    datos = basedatos.exportar_respaldo()
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("datos.json", json.dumps(datos, ensure_ascii=False, indent=1))
        z.writestr("LEEME.txt", LEEME)
    cuantos = {tabla: len(datos.get(tabla) or []) for tabla in LO_QUE_SE_CUENTA}
    return salida.getvalue(), cuantos


class ErrorDeRespaldo(Exception):
    """El archivo no sirve para restaurar. El mensaje es para mostrarlo."""


def leer(contenido):
    """Lo que hay adentro de un respaldo, como diccionario.

    Lanza `ErrorDeRespaldo` con un texto para la pantalla si el archivo no es un
    respaldo: se elige desde la carpeta de descargas, donde hay de todo.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(contenido or b"")) as z:
            datos = json.loads(z.read("datos.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError):
        raise ErrorDeRespaldo("Ese archivo no es un respaldo de ShopStore's. "
                              "Busca uno que se llame respaldo-shopstores-....zip."
                              ) from None
    if not isinstance(datos, dict) or datos.get("version") != 1:
        raise ErrorDeRespaldo("Ese respaldo es de una versión que esta app no "
                              "conoce.")
    return datos


def revisar(contenido):
    """Devuelve `(datos, cuantos, fecha)` sin tocar nada: lo que se va a
    restaurar, para mostrarlo y pedir confirmacion."""
    datos = leer(contenido)
    cuantos = {tabla: len(datos.get(tabla) or []) for tabla in LO_QUE_SE_CUENTA}
    fecha = None
    if datos.get("creado_en"):
        fecha = datetime.fromisoformat(datos["creado_en"]).astimezone().date()
    return datos, cuantos, fecha


def restaurar(datos):
    """Reemplaza todo lo de la cuenta por `datos` (lo que devolvio `revisar`)."""
    return basedatos.restaurar_respaldo(datos)


def marcar_hecho():
    basedatos.escribir_config("respaldo_ultimo", basedatos.ahora())


def ultimo():
    """Cuando se bajo el ultimo, en ISO UTC, o `None`."""
    return basedatos.leer_config("respaldo_ultimo") or None
