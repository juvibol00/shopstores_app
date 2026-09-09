"""Pantallas que se vuelven a dibujar solas.

Nace de un fallo que aparecio en cuatro pantallas a la vez, y que se veia raro:
**la primera vez funcionaba y la segunda no**. En Gastos, tocar «Semana» cambiaba
el periodo; tocar «Mes» despues ya no hacia nada, y habia que salir y volver a
entrar para poder elegir otra vez.

La causa es siempre la misma. La pantalla se dibujaba asi:

    def _gastos(...):
        contenedor = ft.Container()

        def recargar():
            contenedor.content = _gastos(...).content   # <-- aca
            page.update()

Al recargar se construye una pantalla **nueva**, con su propio contenedor y su
propio `recargar`, y se le roba el contenido. Ese contenido queda colgando del
contenedor viejo —el unico que esta en pantalla—, pero sus botones llaman al
`recargar` de la pantalla nueva, que apunta a un contenedor que nunca se monto.
El primer toque se ve; del segundo en adelante se escribe en una pantalla que no
existe y no pasa nada.

`repintable` le da la vuelta: **hay un solo contenedor y un solo `repintar`**, y a
cada dibujado se le pasa ese mismo. No importa cuantas veces se repinte, siempre se
escribe donde la persona esta mirando.
"""

import flet as ft


def repintable(page, construir):
    """Un contenedor que se puede volver a dibujar desde adentro.

    `construir(repintar)` devuelve el contenido y recibe la funcion con la que
    pedir el proximo repintado. Los manejadores que la pantalla arme deben llamar
    a **esa**, no a una propia.
    """
    contenedor = ft.Container(expand=True)

    def repintar():
        contenedor.content = construir(repintar)
        page.update()

    repintar()
    return contenedor
