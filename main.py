"""ShopStore's — app movil de gestion de ventas. El arranque.

El codigo esta partido en dos, igual que SELL-B:

    backend/    la base de datos, el cifrado, los generadores de PDF, el correo y
                el respaldo en Neon. **Nada de aca importa flet.**
    frontend/   las pantallas (`vistas/`), el estilo, la paleta y los dialogos.
    main.py     esto: el unico archivo de la raiz, porque es el que abre `flet`.

Se llama del frontend al backend y nunca al reves. Este archivo solo arma la
navegacion y decide que pantalla se ve.

La navegacion es **por nombre y no por indice**. En SELL-B, navegar por numero causo
un error al insertar una pestana en el medio, porque todos los indices se corren.
"""

import traceback

import flet as ft

from backend import basedatos
from frontend import paleta
from frontend.vistas.cobros_view import crear_vista_cobros
from frontend.vistas.configuracion_view import crear_vista_configuracion
from frontend.vistas.inicio_view import crear_vista_inicio
from frontend.vistas.inventario_view import crear_vista_inventario
from frontend.vistas.gestion_view import crear_vista_gestion
from frontend.vistas.pin_view import crear_vista_pin
from frontend.vistas.ventas_view import crear_vista_ventas

SECCIONES = {
    "inicio":     (ft.Icons.HOME, "Inicio"),
    "venta":      (ft.Icons.SHOPPING_CART, "Venta"),
    "inventario": (ft.Icons.INVENTORY_2, "Inventario"),
    "cobros":     (ft.Icons.ACCOUNT_BALANCE_WALLET, "Cobros"),
    "metricas":   (ft.Icons.BAR_CHART, "Gestión"),
}
ORDEN = ["inicio", "venta", "inventario", "cobros", "metricas"]

def _armar(page: ft.Page):
    page.title = "ShopStore's"
    page.bgcolor = paleta.FONDO
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 380
    page.window.height = 780

    basedatos.conexion()          # crea el archivo y el esquema si no existen

    cuerpo = ft.Container(expand=True)
    barra = {"control": None}

    def navegar(nombre):
        if nombre not in ORDEN:
            nombre = "inicio"
        if barra["control"] is not None:
            barra["control"].selected_index = ORDEN.index(nombre)
        if nombre == "inicio":
            cuerpo.content = crear_vista_inicio(page, navegar, abrir_configuracion)
        elif nombre == "inventario":
            cuerpo.content = crear_vista_inventario(page, abrir_configuracion)
        elif nombre == "venta":
            cuerpo.content = crear_vista_ventas(page, navegar)
        elif nombre == "cobros":
            cuerpo.content = crear_vista_cobros(page)
        else:
            cuerpo.content = crear_vista_gestion(page)
        page.update()

    def abrir_configuracion():
        # Configuracion no gasta pestana: se muestra sobre Inicio y vuelve ahi.
        cuerpo.content = crear_vista_configuracion(
            page, funcion_volver=lambda: navegar("inicio"))
        page.update()

    def cambiar(e):
        indice = e.control.selected_index
        if 0 <= indice < len(ORDEN):
            navegar(ORDEN[indice])

    def entrar():
        barra["control"] = ft.NavigationBar(
            selected_index=0,
            bgcolor=paleta.TARJETA,
            indicator_color=paleta.LILA,
            destinations=[
                ft.NavigationBarDestination(icon=SECCIONES[n][0],
                                            label=SECCIONES[n][1])
                for n in ORDEN
            ],
            on_change=cambiar,
        )
        caja_barra.content = barra["control"]
        navegar("inicio")

    # La barra de secciones va **dentro** del contenido, no en `page.navigation_bar`.
    # Android dibuja la aplicacion de borde a borde y sus propios botones —o la
    # raya de gestos— quedan encima: la barra de la aplicacion aparecia pisada por
    # la del telefono. Metida aca, entra en el `SafeArea` de abajo y el sistema le
    # reserva su espacio.
    caja_barra = ft.Container()
    cuerpo.content = crear_vista_pin(page, entrar)

    page.add(ft.SafeArea(
        ft.Column([cuerpo, caja_barra], spacing=0, expand=True),
        expand=True,
        # Arriba tambien: sin esto, la hora y el nivel de bateria se dibujan sobre
        # el encabezado beige.
        avoid_intrusions_top=True,
        avoid_intrusions_bottom=True,
    ))


def main(page: ft.Page):
    """Un error de arranque tiene que verse en la pantalla del telefono. Sin esto,
    un fallo al importar deja la app en blanco y sin explicacion."""
    try:
        _armar(page)
    except Exception:
        page.controls.clear()
        page.bgcolor = paleta.FONDO
        page.add(
            ft.Text("Error al arrancar", size=20, color=paleta.ERROR),
            ft.Text(traceback.format_exc(), size=11, selectable=True,
                    font_family="monospace"),
        )
        page.update()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
