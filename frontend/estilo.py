"""Los ladrillos visuales compartidos: tipografía, tarjetas y encabezados.

Hasta ahora cada pantalla escribía `ft.Text(..., size=20, color=paleta.TEXTO)` a
mano y **ningún texto tenía peso**: todo salía en regular, incluidos los títulos y
las cifras. Por eso la interfaz se veía plana aunque los colores estuvieran bien.

La jerarquía la hacen tres cosas, en este orden de importancia:

1. **El peso**, no el tamaño. Un título en 20 px regular y un párrafo en 14 px
   regular se parecen más de lo que uno cree; el mismo título en 600 se despega.
2. **El color**: el marrón para lo que es dinero o acción, el gris para lo que
   acompaña.
3. **El tamaño**, al final, y con pocos escalones.

Poner esto en un solo lugar además evita que dos pantallas usen 19 y 20 px para lo
mismo, que es lo que ya estaba empezando a pasar.
"""

import flet as ft

from frontend import paleta

# Cuatro pesos y nada más. Con más escalones, la diferencia deja de leerse.
FUERTE = ft.FontWeight.W_600
MEDIO = ft.FontWeight.W_500
NORMAL = ft.FontWeight.W_400


def titulo(texto, size=22, color=None):
    """El nombre de la pantalla."""
    return ft.Text(texto, size=size, weight=FUERTE, color=color or paleta.TEXTO)


def subtitulo(texto, color=None):
    """La línea de contexto debajo del título."""
    return ft.Text(texto, size=12, weight=NORMAL,
                   color=color or paleta.TEXTO_SUAVE)


def seccion(texto):
    """El rótulo que abre un bloque: «Cómo paga», «Lo que más se vendió»."""
    return ft.Text(texto, size=12, weight=MEDIO, color=paleta.TEXTO_SUAVE)


def cifra(texto, size=26, color=None):
    """Un número que importa: un total, un saldo, una ganancia."""
    return ft.Text(texto, size=size, weight=FUERTE, color=color or paleta.MARCA)


def dato(texto, size=14, color=None, lineas=None):
    """Texto de contenido: el nombre de un producto, una fila de una lista."""
    return ft.Text(texto, size=size, weight=MEDIO, color=color or paleta.TEXTO,
                   max_lines=lineas,
                   overflow=ft.TextOverflow.ELLIPSIS if lineas else None)


def apunte(texto, size=11, color=None):
    """Lo que acompaña y no se lee salvo que haga falta."""
    return ft.Text(texto, size=size, weight=NORMAL,
                   color=color or paleta.TEXTO_SUAVE)


# --------------------------------------------------------------------------
# Contenedores
# --------------------------------------------------------------------------

def tarjeta(contenido, padding=(16, 14, 16, 14), color_borde=None, al_tocar=None,
            expand=None):
    """La superficie blanca sobre la que vive todo.

    Con `color_borde` se convierte en una franja: esquinas rectas y una línea de
    color a la izquierda. Se usa para lo que reclama atención —una tasa vieja, una
    deuda vencida— y por eso **no** lleva el redondeo de las tarjetas normales: la
    diferencia de forma es lo que hace que se noten sin gritar.

    `expand` hace falta cuando la tarjeta va **dentro de una fila**: sin él se
    encoge al ancho de su contenido, y dos tarjetas hermanas quedan de tamaños
    distintos según lo que digan.
    """
    return ft.Container(
        content=contenido,
        bgcolor=paleta.TARJETA,
        border_radius=0 if color_borde else 12,
        border=(ft.Border(left=ft.BorderSide(3, color_borde))
                if color_borde else None),
        padding=ft.Padding(*padding),
        on_click=al_tocar,
        expand=expand,
    )


def encabezado(titulo_texto, subtitulo_texto=None, al_volver=None, acciones=None,
               extra=None):
    """La franja beige de arriba. La misma en todas las pantallas.

    `acciones` son los controles de la derecha; `extra` va debajo del título, para
    lo que necesita más espacio (un selector de período, un buscador).
    """
    izquierda = []
    if al_volver:
        izquierda.append(ft.IconButton(icon=ft.Icons.ARROW_BACK,
                                       icon_color=paleta.MARCA,
                                       on_click=lambda e: al_volver()))
    columna = [titulo(titulo_texto, size=20)]
    if subtitulo_texto:
        columna.append(subtitulo(subtitulo_texto))
    izquierda.append(ft.Column(columna, spacing=1, tight=True, expand=True))

    filas = [ft.Row(izquierda + list(acciones or []), spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if extra:
        filas.append(extra)

    return ft.Container(
        content=ft.Column(filas, spacing=12, tight=True),
        bgcolor=paleta.LILA_CLARO,
        padding=ft.Padding(6 if al_volver else 16, 14, 12, 14),
    )


def vacio(icono, mensaje, detalle=None):
    """El estado sin datos. Con un icono en vez de una línea de texto suelta: una
    frase gris flotando en el fondo se lee como si la pantalla estuviera rota."""
    partes = [
        ft.Icon(icono, color=paleta.LILA, size=40),
        ft.Text(mensaje, size=13, weight=MEDIO, color=paleta.TEXTO_SUAVE,
                text_align=ft.TextAlign.CENTER),
    ]
    if detalle:
        partes.append(ft.Text(detalle, size=11, color=paleta.TEXTO_SUAVE,
                              text_align=ft.TextAlign.CENTER))
    return ft.Container(
        content=ft.Column(partes, spacing=8, tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(20, 30, 20, 30), alignment=ft.Alignment.CENTER,
    )


def boton(texto, al_click, principal=True, ancho=None, peligro=False,
          expand=None, alto=None):
    if peligro:
        estilo = ft.ButtonStyle(color=paleta.ERROR)
    elif principal:
        estilo = ft.ButtonStyle(bgcolor=paleta.MARCA, color=paleta.FONDO)
    else:
        estilo = ft.ButtonStyle(color=paleta.MARCA)
    # `expand` sirve para repartir el ancho entre dos botones de una fila; `ancho`
    # para el botón que ocupa la pantalla entera.
    return ft.ElevatedButton(content=texto, on_click=al_click, width=ancho,
                             height=alto, expand=expand, style=estilo)


def pastillas(opciones, elegida, al_elegir, sobre_beige=False):
    """Selector de pocas opciones, en fila. Sobre el encabezado beige la opción no
    elegida va hueca: una tarjeta blanca ahí compite con las tarjetas de datos."""
    def una(clave, etiqueta):
        activa = clave == elegida
        if activa:
            fondo, color, borde = paleta.MARCA, paleta.FONDO, None
        elif sobre_beige:
            fondo, color = None, paleta.MARCA
            lado = ft.BorderSide(1, paleta.LILA)
            borde = ft.Border(lado, lado, lado, lado)
        else:
            fondo, color, borde = paleta.TARJETA, paleta.MARCA, None
        return ft.Container(
            content=ft.Text(etiqueta, size=12, weight=MEDIO, color=color),
            bgcolor=fondo, border=borde, border_radius=20,
            padding=ft.Padding(12, 7, 12, 7), expand=True,
            alignment=ft.Alignment.CENTER,
            on_click=lambda e, c=clave: al_elegir(c))

    return ft.Row([una(c, e) for c, e in opciones], spacing=6)
