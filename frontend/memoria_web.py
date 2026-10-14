"""Que la version web recuerde la sesion y el PIN entre una visita y otra.

En el navegador, Python escribe en un disco de mentira que vive en la memoria de
la pestana: al recargar la pagina, `config.json` desaparece, y con el la sesion
—habria que escribir el correo y la contrasena cada vez— y la huella del PIN.

Lo que si dura es la memoria propia del navegador, a la que Flet llega con
`SharedPreferences`. Aca se copia ahi todo `config.json`, entero, cada vez que
algo cambia, y al abrir se devuelve antes de que nadie lo lea.

Solo en el navegador. En Android y en la computadora el archivo dura y esto no
hace nada.

**Que queda guardado en el navegador:** el *refresh token* de la sesion (no la
contrasena), la huella del PIN (no el PIN) y el nombre. Es lo mismo que guarda
cualquier pagina que te deja la sesion abierta.
"""

import asyncio
import json

import flet as ft

from backend import almacenamiento

CLAVE = "shopstores_config"


async def recuperar(page):
    """Trae lo guardado y deja enganchada la copia automatica. Va al arrancar,
    antes de mirar si hay sesion o PIN."""
    if not page.web:
        return
    memoria = ft.SharedPreferences()
    try:
        guardado = await memoria.get(CLAVE)
    except Exception:
        guardado = None
    if guardado:
        try:
            almacenamiento.cargar(json.loads(guardado))
        except ValueError:
            pass        # algo ilegible: se empieza de cero, como un config roto

    def copiar(datos):
        texto = json.dumps(datos, ensure_ascii=False)
        # Quien guarda es codigo comun, no `async`: la copia se encarga como
        # tarea y corre apenas el manejador del boton termina.
        try:
            asyncio.get_running_loop().create_task(memoria.set(CLAVE, texto))
        except RuntimeError:
            page.run_task(memoria.set, CLAVE, texto)

    almacenamiento.al_cambiar = copiar
