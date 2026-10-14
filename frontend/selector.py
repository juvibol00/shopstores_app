"""El selector de archivos: uno solo, listo desde que arranca la app.

**En el iPhone, la galeria solo se abre si la orden sale dentro del toque.**
Safari exige que abrir un archivo sea respuesta directa a un gesto de la persona,
y si la orden llega tarde la descarta sin decir nada: el boton parece muerto. Asi
pasaba con «Agregar foto» en la version web.

Con `pick_files()` la orden no puede salir a tiempo: el toque viaja a Python y la
respuesta vuelve a la pantalla, y en el iPhone ese ida y vuelta siempre se pasa.
Ni siquiera dejar el selector creado de antemano alcanzo (se probo).

**Flet 1.0 lo resuelve con `PickFiles`**: una accion que el boton lleva puesta y
que la pantalla ejecuta **ella misma, dentro del toque**, sin preguntarle a
Python. Lo elegido llega despues a `on_result`. La version web se compila con
Flet 1.0 por eso.

El APK sigue con Flet 0.85.3 hasta probarlo aparte, y ahi `PickFiles` no existe:
`elegir_imagen` usa la accion si esta y, si no, el `pick_files()` de siempre, que
en Android y en la computadora funciona.
"""

import flet as ft

# Flet 1.0 o mas nuevo: la pantalla puede abrir la galeria sin pasar por Python.
ABRE_LA_PANTALLA = hasattr(ft, "PickFiles")

_por_pagina = {}


def preparar(page):
    """Crea el selector y lo registra. Va al arrancar, antes del primer dibujo."""
    if id(page) not in _por_pagina:
        estado = {"destino": None}

        def al_resultado(e):
            # Llega cuando la persona eligio (o cancelo) en la galeria que abrio
            # `PickFiles`. Va a quien toco el boton, una sola vez.
            destino, estado["destino"] = estado["destino"], None
            if destino and e.files:
                destino(e.files)

        opciones = {"on_result": al_resultado} if ABRE_LA_PANTALLA else {}
        estado["selector"] = ft.FilePicker(**opciones)
        page.services.append(estado["selector"])
        _por_pagina[id(page)] = estado
    return _por_pagina[id(page)]


def de(page):
    """El selector de esta pagina. Si nadie lo preparo (las pruebas), lo crea."""
    return preparar(page)["selector"]


def elegir_imagen(page, al_elegir, titulo, al_fallar=None):
    """Lo que hay que ponerle al control que abre la galeria, como argumentos:
    `ft.Container(..., **elegir_imagen(...))`.

    `al_elegir(archivos)` recibe la lista elegida, con los bytes ya leidos.
    """
    estado = preparar(page)
    if ABRE_LA_PANTALLA:
        def anotar(e):
            # El clic llega a Python **despues** de que la pantalla abrio la
            # galeria, y antes de que la persona termine de elegir: alcanza para
            # dejar dicho a quien va la foto.
            estado["destino"] = al_elegir

        return {
            "action": ft.PickFiles(estado["selector"], dialog_title=titulo,
                                   file_type=ft.FilePickerFileType.IMAGE,
                                   with_data=True),
            "on_click": anotar,
        }

    async def abrir(e):
        try:
            archivos = await estado["selector"].pick_files(
                dialog_title=titulo, file_type=ft.FilePickerFileType.IMAGE,
                with_data=True)
        except Exception as ex:
            if al_fallar:
                al_fallar(ex)
            return
        if archivos:
            al_elegir(archivos)

    return {"on_click": abrir}
