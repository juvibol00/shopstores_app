"""El selector de archivos: uno solo, listo desde que arranca la app.

**En el iPhone, la galeria solo se abre si la orden llega justo despues del
toque.** Safari exige que abrir un archivo sea respuesta directa a un gesto de la
persona, y si la orden llega tarde la descarta sin decir nada: el boton parece
muerto. Asi pasaba con «Agregar foto» en la version web.

Antes, cada toque creaba un selector nuevo, lo registraba en la pagina, esperaba a
que la pantalla se enterara y recien ahi pedia abrir la galeria. En el iPhone,
con Python corriendo en el navegador, ese ida y vuelta se pasaba del margen. Con
el selector ya creado y registrado al arrancar, el toque manda **una sola orden**
y llega a tiempo.

En Android y en la computadora no hacia falta, pero tampoco molesta.
"""

import flet as ft

_por_pagina = {}


def preparar(page):
    """Crea el selector y lo registra. Va al arrancar, antes del primer dibujo."""
    if id(page) not in _por_pagina:
        selector = ft.FilePicker()
        page.services.append(selector)
        _por_pagina[id(page)] = selector
    return _por_pagina[id(page)]


def de(page):
    """El selector de esta pagina. Si nadie lo preparo (las pruebas), lo crea."""
    return preparar(page)
