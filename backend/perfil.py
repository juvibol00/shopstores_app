"""El perfil de la cuenta: el nombre con que saluda la app.

Vive en la cuenta (Supabase), igual que la huella del PIN (ver `seguridad.py`):
se crea una vez y aparece en cualquier aparato donde se entre con ese correo.
Antes vivia en `config.json` de cada aparato; `nombre` lo sube la primera vez.
"""

from backend import almacenamiento
from backend import basedatos

CLAVE = "nombre_usuario"


def nombre():
    valor = basedatos.leer_config(CLAVE)
    if valor is not None:
        return valor
    viejo = almacenamiento.obtener(CLAVE)
    if viejo:
        guardar_nombre(viejo)
        almacenamiento.borrar(CLAVE)
        return viejo
    return ""


def guardar_nombre(valor):
    basedatos.escribir_config(CLAVE, (valor or "").strip())
