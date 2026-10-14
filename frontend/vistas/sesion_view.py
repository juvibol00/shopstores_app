"""La entrada con correo y contrasena, y el aviso de que no hay conexion.

Es la puerta de afuera. La cuenta la crea el dueno del proyecto desde el panel de
Supabase —el registro esta cerrado—, y aca solo se entra con ella. Se escribe una
vez por telefono: despues la sesion queda guardada (ver `nube.py`), y en cada
apertura lo unico que se pide es el PIN, que es el candado de adentro.

La contrasena no se guarda en ningun lado, ni en el telefono ni en la app.
"""

import flet as ft

from backend import nube
from frontend import estilo
from frontend import marca
from frontend import paleta
from frontend.vistas.pin_view import marco, sin_fallos_mudos


def crear_vista_sesion(page, al_entrar):
    aviso = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR,
                    text_align=ft.TextAlign.CENTER)
    correo = ft.TextField(label="Correo", value=nube.correo() or "",
                          keyboard_type=ft.KeyboardType.EMAIL,
                          border_color=paleta.LILA,
                          focused_border_color=paleta.MARCA)

    def entrar(e):
        aviso.value = ""
        try:
            nube.iniciar(correo.value, clave.value)
        except nube.ErrorDeNube as ex:
            aviso.value = str(ex)
            aviso.update()
            return
        clave.value = ""
        al_entrar()

    entrar = sin_fallos_mudos(aviso, entrar)
    clave = ft.TextField(label="Contraseña", password=True,
                         can_reveal_password=True, border_color=paleta.LILA,
                         focused_border_color=paleta.MARCA, on_submit=entrar)

    return ft.Container(
        content=ft.Column([
            marca.logo(88),
            ft.Text("ShopStore's", size=24, weight=estilo.FUERTE,
                    color=paleta.MARCA),
            ft.Text("Entra con la cuenta que te dieron.",
                    size=13, color=paleta.TEXTO_SUAVE,
                    text_align=ft.TextAlign.CENTER),
            marco([
                correo, clave, aviso,
                estilo.boton("Entrar", entrar, ancho=260, alto=46),
                ft.Text("Se pide una sola vez en este teléfono. Después solo "
                        "te pedirá el PIN.",
                        size=11, color=paleta.TEXTO_SUAVE,
                        text_align=ft.TextAlign.CENTER),
            ]),
        ], spacing=16, tight=True, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )


def crear_vista_sin_conexion(page, al_reintentar):
    """Cuando al abrir no se llega al servidor. No es lo mismo que una sesion
    vencida: aca la sesion esta bien y lo que falta es internet, asi que no se
    pide la contrasena de nuevo."""
    return ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.WIFI_OFF, size=56, color=paleta.MARCA_CLARA),
            ft.Text("Sin conexión", size=22, weight=estilo.FUERTE,
                    color=paleta.MARCA),
            ft.Text("Los datos de la tienda están en internet. Revisa la "
                    "conexión y vuelve a intentar.",
                    size=13, color=paleta.TEXTO_SUAVE,
                    text_align=ft.TextAlign.CENTER, width=280),
            estilo.boton("Reintentar", lambda e: al_reintentar(),
                         ancho=220, alto=46),
        ], spacing=16, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )
