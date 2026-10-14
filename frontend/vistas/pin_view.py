"""La puerta: configurar el acceso la primera vez, y desbloquear despues.

Ni el nombre ni el PIN estan escritos en el codigo. La primera vez que se abre la
app, el dueno los elige. Del PIN solo se guarda su huella (ver `seguridad.py`), asi
que ni siquiera esta app puede volver a leerlo.
"""

import flet as ft

from backend import almacenamiento
from frontend import estilo
from frontend import marca
from frontend import paleta
from backend import seguridad


def _campo_pin(etiqueta, al_enviar=None):
    return ft.TextField(
        label=etiqueta,
        password=True,
        can_reveal_password=True,
        keyboard_type=ft.KeyboardType.NUMBER,
        text_align=ft.TextAlign.CENTER,
        border_color=paleta.LILA,
        focused_border_color=paleta.MARCA,
        on_submit=al_enviar,
    )


def _marco(controles):
    return ft.Container(
        content=ft.Column(controles, spacing=14, tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=paleta.TARJETA,
        border_radius=12,
        padding=ft.Padding(24, 28, 24, 28),
        width=340,
    )


def crear_vista_pin(page, al_entrar):
    """Devuelve la pantalla que corresponda: configurar o desbloquear."""
    if seguridad.hay_pin():
        return _desbloquear(page, al_entrar)
    return _configurar(page, al_entrar)


# --------------------------------------------------------------------------

def _configurar(page, al_entrar):
    nombre = ft.TextField(label="Tu nombre", border_color=paleta.LILA,
                          focused_border_color=paleta.MARCA)
    pin = _campo_pin("PIN de 6 dígitos")
    repetir = _campo_pin("Repetir PIN")
    aviso = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR,
                    text_align=ft.TextAlign.CENTER)
    debilidad = ft.Text("", size=12, color=paleta.AVISO,
                        text_align=ft.TextAlign.CENTER)

    def revisar_fuerza(e):
        motivo = seguridad.parece_debil(pin.value)
        # Avisa, no bloquea: es la clave del dueno y la decision es suya.
        debilidad.value = f"Se puede usar, pero: {motivo}" if motivo else ""
        debilidad.update()

    pin.on_change = revisar_fuerza

    def crear(e):
        aviso.value = ""
        if not (nombre.value or "").strip():
            aviso.value = "Falta tu nombre."
            aviso.update()
            return
        try:
            seguridad.establecer(pin.value, repetir.value)
        except seguridad.PinInvalido as ex:
            aviso.value = str(ex)
            aviso.update()
            return
        almacenamiento.guardar("nombre_usuario", nombre.value.strip())
        al_entrar()

    return ft.Container(
        content=ft.Column([
            marca.logo(88),
            ft.Text("ShopStore's", size=24, weight=estilo.FUERTE,
                    color=paleta.MARCA),
            ft.Text("Primer arranque: elige cómo vas a entrar.",
                    size=13, color=paleta.TEXTO_SUAVE,
                    text_align=ft.TextAlign.CENTER),
            _marco([
                nombre, pin, repetir, debilidad, aviso,
                estilo.boton("Crear acceso", crear, ancho=260, alto=46),
                ft.Text("El PIN no se guarda en ningún lado: se guarda una huella "
                        "con la que se puede comprobar, pero no reconstruirlo. "
                        "Si lo olvidas, no hay forma de recuperarlo.",
                        size=11, color=paleta.TEXTO_SUAVE,
                        text_align=ft.TextAlign.CENTER),
            ]),
        ], spacing=16, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )


# --------------------------------------------------------------------------

def _desbloquear(page, al_entrar):
    aviso = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR,
                    text_align=ft.TextAlign.CENTER)
    nombre = almacenamiento.obtener("nombre_usuario", "")

    def entrar(e):
        if seguridad.verificar(pin.value):
            al_entrar()
        else:
            aviso.value = "PIN incorrecto."
            aviso.update()
            pin.value = ""
            pin.update()

    pin = _campo_pin("PIN", al_enviar=entrar)

    return ft.Container(
        content=ft.Column([
            marca.logo(88),
            ft.Text(f"Hola, {nombre}" if nombre else "ShopStore's",
                    size=22, weight=estilo.FUERTE, color=paleta.MARCA),
            _marco([
                pin, aviso,
                estilo.boton("Entrar", entrar, ancho=260, alto=46),
            ]),
        ], spacing=16, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )
