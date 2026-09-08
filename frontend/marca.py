"""El logo, en un solo lugar.

Se dibuja desde `assets/icon.png`, que es el mismo archivo que toma `flet build`
para el icono del telefono: asi el logo de adentro y el de la pantalla de inicio de
Android no pueden separarse.

Si por lo que sea la imagen no carga, `error_content` pone la V dibujada a mano en
su lugar. Un encabezado con un hueco se ve roto; con la letra, no se nota.
"""

import flet as ft

from frontend import paleta


def logo(lado=44, radio=None):
    radio = radio if radio is not None else max(8, round(lado * 0.23))
    respaldo = ft.Container(
        content=ft.Text("V", size=round(lado * 0.5), color=paleta.FONDO,
                        text_align=ft.TextAlign.CENTER),
        width=lado, height=lado, bgcolor=paleta.MARCA, border_radius=radio,
        alignment=ft.Alignment.CENTER,
    )
    return ft.Image(src="icon.png", width=lado, height=lado,
                    border_radius=radio, fit=ft.BoxFit.COVER,
                    error_content=respaldo)
