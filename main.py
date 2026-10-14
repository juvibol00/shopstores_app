"""ShopStore's — app movil de gestion de ventas. El arranque.

El codigo esta partido en dos, igual que SELL-B:

    backend/    la base de datos, el cifrado, los generadores de PDF, el correo y
                el respaldo en archivo. **Nada de aca importa flet.**
    frontend/   las pantallas (`vistas/`), el estilo, la paleta y los dialogos.
    main.py     esto: el unico archivo de la raiz, porque es el que abre `flet`.

Se llama del frontend al backend y nunca al reves. Este archivo solo arma la
navegacion y decide que pantalla se ve.

La navegacion es **por nombre y no por indice**. En SELL-B, navegar por numero causo
un error al insertar una pestana en el medio, porque todos los indices se corren.
"""

import traceback

import flet as ft

# **Arriba del archivo solo va lo que no puede fallar.** Todo lo de la aplicacion
# se importa dentro de `_armar`, que esta protegida por `main`.
#
# Antes estaba todo aca arriba, y eso dejaba ciega a la red de errores de `main`:
# un import que fallaba mataba a Python **antes** de que existiera la pantalla, y
# la app quedaba en blanco sin decir nada. Asi paso en la version web, cinco veces
# seguidas, con un error distinto cada vez y ninguno visible sin abrir la consola
# del navegador. Con los imports adentro, cualquier fallo de arranque se ve
# escrito en la pantalla del telefono.

SECCIONES = {
    "inicio":     (ft.Icons.HOME, "Inicio"),
    "venta":      (ft.Icons.SHOPPING_CART, "Venta"),
    "inventario": (ft.Icons.INVENTORY_2, "Inventario"),
    "cobros":     (ft.Icons.ACCOUNT_BALANCE_WALLET, "Cobros"),
    "metricas":   (ft.Icons.BAR_CHART, "Gestión"),
}
ORDEN = ["inicio", "venta", "inventario", "cobros", "metricas"]

async def _armar(page: ft.Page):
    # Ver la nota de arriba: estos imports viven aca para que un fallo se vea.
    from backend import basedatos
    from backend import nube
    from frontend import memoria_web
    from frontend import paleta
    from frontend import selector
    from frontend.vistas.cobros_view import crear_vista_cobros
    from frontend.vistas.configuracion_view import crear_vista_configuracion
    from frontend.vistas.gestion_view import crear_vista_gestion
    from frontend.vistas.inicio_view import crear_vista_inicio
    from frontend.vistas.inventario_view import POR_TANDA, crear_vista_inventario
    from frontend.vistas.pin_view import crear_vista_pin
    from frontend.vistas.sesion_view import (crear_vista_sesion,
                                             crear_vista_sin_conexion)
    from frontend.vistas.ventas_view import crear_vista_ventas

    page.title = "ShopStore's"
    page.bgcolor = paleta.FONDO
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    page.window.width = 380
    page.window.height = 780

    # En el navegador, la sesion y el PIN se guardan en la memoria del navegador:
    # hay que traerlos antes de preguntar si estan.
    await memoria_web.recuperar(page)

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
            page, funcion_volver=lambda: navegar("inicio"),
            al_cerrar_sesion=puerta)
        page.update()

    def cambiar(e):
        indice = e.control.selected_index
        if 0 <= indice < len(ORDEN):
            navegar(ORDEN[indice])

    def entrar():
        basedatos.preparar_cuenta()       # la primera vez siembra los metodos
        # Lo de todas las pestanas en un solo viaje: despues, cambiar de pestana
        # no espera a internet hasta que algo se registre.
        basedatos.precargar_todo(POR_TANDA)
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

    def mostrar(vista):
        caja_barra.content = None
        barra["control"] = None
        cuerpo.content = vista
        page.update()

    def puerta():
        """Las dos cerraduras, en orden. **Afuera**, la sesion de Supabase: sin
        ella no se puede leer ni guardar nada. **Adentro**, el PIN: que quien
        agarre el telefono no entre directo a las ventas."""
        try:
            con_sesion = nube.hay_sesion() or nube.reanudar()
        except nube.SinConexion:
            mostrar(crear_vista_sin_conexion(page, puerta))
            return
        if con_sesion:
            mostrar(crear_vista_pin(page, entrar))
        else:
            mostrar(crear_vista_sesion(page, puerta))

    # El selector de fotos, listo antes de que nadie lo toque: en el iPhone, si
    # se crea al tocar, la galeria no se abre (ver `frontend/selector.py`).
    selector.preparar(page)

    page.add(ft.SafeArea(
        ft.Column([cuerpo, caja_barra], spacing=0, expand=True),
        expand=True,
        # Arriba tambien: sin esto, la hora y el nivel de bateria se dibujan sobre
        # el encabezado beige.
        avoid_intrusions_top=True,
        avoid_intrusions_bottom=True,
    ))
    puerta()


async def main(page: ft.Page):
    """Un error de arranque tiene que verse en la pantalla del telefono. Sin esto,
    un fallo al importar deja la app en blanco y sin explicacion.

    La pantalla de error **no usa nada de la aplicacion**, ni siquiera la paleta:
    si lo que fallo es justo un import, la paleta tampoco estaria, y el aviso del
    error reventaria a su vez. Solo `flet` y colores escritos a mano.
    """
    try:
        await _armar(page)
    except Exception:
        page.controls.clear()
        page.bgcolor = "#FFFFFF"
        page.padding = 16
        page.scroll = ft.ScrollMode.AUTO
        page.add(
            ft.Text("No se pudo arrancar", size=20, weight=ft.FontWeight.W_600,
                    color="#B4534B"),
            ft.Text("Mándale una captura de esto a quien te instaló la app.",
                    size=13, color="#6E6679"),
            ft.Container(height=8),
            ft.Text(traceback.format_exc(), size=11, selectable=True,
                    font_family="monospace", color="#27222E"),
        )
        page.update()


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
