"""Configuración: un menú de tarjetas y sub-vistas que se muestran en su lugar.

No gasta una pestaña de la barra: se abre con el engranaje de Inicio y vuelve ahí.
Se consulta poco, y una pestaña permanente para algo que se toca una vez al mes le
quita lugar a lo que sí se usa todos los días.

Es el mismo patrón que en SELL-B: menú de tarjetas y sub-vistas, en vez de amontonar
todos los controles en una pantalla larga.
"""

import flet as ft

from backend import basedatos
from backend import formato
from backend import nube
from backend import seguridad
from backend import respaldo
from frontend import descargas
from frontend import dialogos
from frontend import estilo
from frontend import paleta
from frontend import pantalla


def crear_vista_configuracion(page, funcion_volver, al_cerrar_sesion=None):
    contenedor = ft.Container(expand=True)

    def menu():
        contenedor.content = _menu(page, funcion_volver, abrir)
        page.update()

    def abrir(cual):
        if cual == "metodos":
            contenedor.content = _metodos(page, menu)
        elif cual == "pin":
            contenedor.content = _cambiar_pin(page, menu)
        elif cual == "respaldo":
            contenedor.content = _respaldo(page, menu)
        elif cual == "cuenta":
            _cerrar_sesion(page, al_cerrar_sesion)
            return
        page.update()

    contenedor.content = _menu(page, funcion_volver, abrir)
    return contenedor


def _cabecera(titulo, al_volver, subtitulo=None):
    return estilo.encabezado(titulo, subtitulo, al_volver=al_volver)


def _tarjeta(titulo, detalle, al_tocar=None, pendiente=None):
    contenido = ft.Row([
        ft.Column([
            estilo.dato(titulo, size=15),
            estilo.apunte(detalle),
        ], spacing=2, tight=True, expand=True),
    ], spacing=8)
    if pendiente:
        contenido.controls.append(
            ft.Container(content=ft.Text(pendiente, size=11, weight=estilo.MEDIO,
                                         color=paleta.MARCA),
                         bgcolor=paleta.LILA_CLARO, border_radius=8,
                         padding=ft.Padding(9, 3, 9, 3)))
    else:
        contenido.controls.append(
            ft.Icon(ft.Icons.CHEVRON_RIGHT, color=paleta.MARCA_CLARA, size=20))
    return estilo.tarjeta(contenido, padding=(14, 12, 12, 12),
                          al_tocar=al_tocar)


# ==========================================================================

def _menu(page, funcion_volver, abrir):
    cuantos = len(basedatos.listar_metodos())
    return ft.Column([
        _cabecera("Configuración", funcion_volver),
        ft.Container(content=ft.Column([
            _tarjeta("Métodos de pago", f"{cuantos} activos",
                     lambda e: abrir("metodos")),
            _tarjeta("Cambiar el PIN", "Hace falta saber el actual",
                     lambda e: abrir("pin")),
            _tarjeta("Tasa del día", "Se carga desde la pantalla de inicio",
                     pendiente="en Inicio"),
            _tarjeta("Respaldo", _estado_respaldo(),
                     lambda e: abrir("respaldo")),
            _tarjeta("Cuenta", nube.correo() or "Sesión abierta",
                     lambda e: abrir("cuenta")),
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


def _cerrar_sesion(page, al_cerrar_sesion):
    """Cierra la sesion de Supabase en este telefono. Los datos no se tocan:
    quedan en la cuenta, y vuelven al entrar de nuevo con el correo."""
    def cerrar():
        nube.cerrar_sesion()
        basedatos.olvidar_lo_leido()
        if al_cerrar_sesion:
            al_cerrar_sesion()

    dialogos.confirmar(
        page, "Cerrar sesión",
        "Este teléfono deja de tener acceso hasta que vuelvas a entrar con tu "
        "correo y tu contraseña. Tus ventas y productos no se borran: quedan "
        "guardados en tu cuenta.",
        "Cerrar sesión", cerrar)


# ==========================================================================
# Métodos de pago
# ==========================================================================

def _metodos(page, al_volver):
    return pantalla.repintable(
        page, lambda repintar: _cuerpo_metodos(page, al_volver, repintar))


def _cuerpo_metodos(page, al_volver, recargar):
    """`recargar` es el de la pantalla montada: hay que usar **ese** y no armar uno
    propio (ver `frontend/pantalla.py`)."""
    filas = []
    for m in basedatos.listar_metodos():
        filas.append(estilo.tarjeta(
            ft.Row([
                ft.Column([
                    estilo.dato(m["nombre"], size=15),
                    estilo.apunte("en dólares" if m["moneda"] == "USD"
                                  else "en bolívares"),
                ], spacing=1, tight=True, expand=True),
                ft.IconButton(icon=ft.Icons.EDIT, icon_color=paleta.MARCA_CLARA,
                              icon_size=18, tooltip="Editar",
                              on_click=lambda e, f=m: _formulario_metodo(
                                  page, f, recargar)),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                              icon_color=paleta.ERROR, icon_size=18,
                              tooltip="Quitar",
                              on_click=lambda e, f=m: _quitar_metodo(
                                  page, f, recargar)),
            ], spacing=2),
            padding=(14, 8, 4, 8)))

    return ft.Column([
        _cabecera("Métodos de pago", al_volver,
                  "Los que aparecen al cobrar"),
        ft.Container(content=ft.Column(filas + [
            ft.Container(height=4),
            estilo.boton("Agregar un método",
                         lambda e: _formulario_metodo(page, None, recargar),
                         ancho=400, alto=46),
            ft.Container(height=8),
            estilo.apunte("La moneda dice en qué se escribe el monto al cobrar. "
                          "Un método en bolívares se convierte a dólares con la "
                          "tasa del día para las métricas."),
            estilo.apunte("Quitar un método no toca las ventas viejas: cada una "
                          "guardó el nombre con el que se cobró."),
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


def _formulario_metodo(page, existente, al_terminar):
    nombre = ft.TextField(
        label="Nombre", value=existente["nombre"] if existente else "",
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    moneda = ft.Dropdown(
        label="Moneda", value=existente["moneda"] if existente else "Bs",
        border_color=paleta.LILA, focused_border_color=paleta.MARCA,
        options=[ft.DropdownOption(key="USD", text="Dólares"),
                 ft.DropdownOption(key="Bs", text="Bolívares")])
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def guardar(e):
        try:
            if existente:
                basedatos.actualizar_metodo(existente["id"], nombre.value,
                                            moneda.value)
            else:
                basedatos.crear_metodo(nombre.value, moneda.value)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.cerrar(page, dialogo)
        dialogos.exito(page, "Método guardado.")
        al_terminar()

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato("Editar método" if existente else "Nuevo método",
                          size=16),
        content=ft.Column([nombre, moneda, problema], spacing=12, tight=True,
                          width=300),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Guardar", guardar),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)


def _quitar_metodo(page, metodo, al_terminar):
    def quitar():
        try:
            basedatos.desactivar_metodo(metodo["id"])
        except ValueError as ex:
            dialogos.error(page, str(ex))
            return
        dialogos.exito(page, f"«{metodo['nombre']}» ya no aparece al cobrar.")
        al_terminar()

    dialogos.confirmar(
        page, f"Quitar «{metodo['nombre']}»",
        "Deja de aparecer al cobrar. Las ventas que ya se cobraron con él no se "
        "tocan: cada una guardó el nombre con el que se pagó.",
        "Quitar", quitar, peligro=True)


# ==========================================================================
# Cambiar el PIN
# ==========================================================================

def _cambiar_pin(page, al_volver):
    def campo(etiqueta):
        return ft.TextField(label=etiqueta, password=True,
                            can_reveal_password=True,
                            keyboard_type=ft.KeyboardType.NUMBER,
                            border_color=paleta.LILA,
                            focused_border_color=paleta.MARCA)

    actual = campo("PIN actual")
    nuevo = campo("PIN nuevo")
    repetir = campo("Repetir el nuevo")
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)
    debilidad = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.AVISO)

    def revisar(e):
        motivo = seguridad.parece_debil(nuevo.value)
        debilidad.value = f"Se puede usar, pero: {motivo}" if motivo else ""
        page.update()

    nuevo.on_change = revisar

    def guardar(e):
        problema.value = ""
        try:
            seguridad.cambiar(actual.value, nuevo.value, repetir.value)
        except seguridad.PinInvalido as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.exito(page, "PIN cambiado.")
        al_volver()

    return ft.Column([
        _cabecera("Cambiar el PIN", al_volver),
        ft.Container(content=ft.Column([
            actual, nuevo, repetir, debilidad, problema,
            estilo.boton("Guardar el PIN nuevo", guardar, ancho=400, alto=46),
            ft.Container(height=6),
            estilo.apunte("Si olvidas el PIN no hay forma de recuperarlo: de él "
                          "solo se guarda una huella, no el número."),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 16, 14, 20), expand=True),
    ], spacing=0, expand=True)


# ==========================================================================
# El respaldo: todo lo de la cuenta en un archivo
# ==========================================================================

def _estado_respaldo():
    cuando = respaldo.ultimo()
    if not cuando:
        return "Nunca hecho"
    dia = formato.dia_local(cuando)
    return f"Último el {dia.strftime('%d/%m/%Y')}"


def _respaldo(page, al_volver):
    return pantalla.repintable(
        page, lambda repintar: _cuerpo_respaldo(page, al_volver, repintar))


def _cuerpo_respaldo(page, al_volver, recargar):
    """Bajar todo lo de la cuenta en un archivo (ver `backend/respaldo.py`).

    Se arma al tocar, no antes: con fotos son varios megas y no tiene sentido
    traerlos cada vez que se entra a Configuracion.
    """
    async def preparar(e):
        try:
            datos, cuantos = respaldo.armar()
        except ValueError as ex:
            dialogos.error(page, str(ex))
            return

        def bajado():
            respaldo.marcar_hecho()
            recargar()

        await descargas.ofrecer(
            page, datos, respaldo.nombre_sugerido(), respaldo.NOMBRE_EN_LA_NUBE,
            "application/zip", "Tu respaldo está listo",
            f"{cuantos['productos']} producto(s) con "
            f"{cuantos['producto_fotos']} foto(s), {cuantos['clientes']} "
            f"cliente(s), {cuantos['ventas']} venta(s) y {cuantos['gastos']} "
            "gasto(s). Guárdalo en un lugar seguro: Drive, iCloud o tu correo.",
            al_descargar=bajado)

    return ft.Column([
        _cabecera("Respaldo", al_volver, "Todo lo de tu cuenta en un archivo"),
        ft.Container(content=ft.Column([
            estilo.tarjeta(ft.Column([
                estilo.seccion("Último respaldo"),
                estilo.dato(_estado_respaldo(), size=15),
            ], spacing=4, tight=True)),
            estilo.boton("Preparar el respaldo", preparar, ancho=400, alto=46),
            estilo.apunte("Lleva tus productos con sus fotos, clientes, ventas, "
                          "abonos y gastos. No lleva tu PIN ni tu contraseña."),
            estilo.apunte("Quien tenga el archivo puede ver tus ventas y tus "
                          "clientes: guárdalo donde solo tú entres."),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 16, 14, 20), expand=True),
    ], spacing=0, expand=True)
