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

Por ahora solo se baja: no hay boton para restaurar. Si algun dia hace falta, el
archivo tiene todo lo necesario, con los mismos ids.
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


def leer(contenido):
    """Lo que hay adentro de un respaldo, como diccionario. Para revisarlo."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        return json.loads(z.read("datos.json").decode("utf-8"))


def marcar_hecho():
    basedatos.escribir_config("respaldo_ultimo", basedatos.ahora())


def ultimo():
    """Cuando se bajo el ultimo, en ISO UTC, o `None`."""
    return basedatos.leer_config("respaldo_ultimo") or None
