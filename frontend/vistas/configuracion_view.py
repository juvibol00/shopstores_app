"""Configuración: un menú de tarjetas y sub-vistas que se muestran en su lugar.

No gasta una pestaña de la barra: se abre con el engranaje de Inicio y vuelve ahí.
Se consulta poco, y una pestaña permanente para algo que se toca una vez al mes le
quita lugar a lo que sí se usa todos los días.

Es el mismo patrón que en SELL-B: menú de tarjetas y sub-vistas, en vez de amontonar
todos los controles en una pantalla larga.
"""

import flet as ft

from backend import basedatos
from backend import correo
from backend import formato
from backend import nube
from backend import seguridad
from backend import respaldo
from frontend import dialogos
from frontend import estilo
from frontend import paleta
from frontend import pantalla
from frontend import selector


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
        elif cual == "correo":
            contenedor.content = _correo(page, menu)
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
            # El respaldo copiaba el archivo de SQLite del telefono, que ya no
            # existe: los datos estan en Supabase. Vuelve cuando se rehaga como
            # una exportacion de la cuenta.
            _tarjeta("Respaldo", "Se está adaptando a la nube",
                     pendiente="pronto"),
            _tarjeta("Correo",
                     "Configurado" if correo.configurado()
                     else "Sin configurar",
                     lambda e: abrir("correo")),
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
# El correo por donde sale el resumen semanal
# ==========================================================================

def _correo(page, al_volver):
    """La clave de aplicación se guarda **cifrada con el PIN**, así que solo se
    puede leer con la sesión abierta. Si venía de otro teléfono no se descifra, y
    entonces el campo aparece vacío pidiendo que se escriba de nuevo."""
    actual = correo.leer_configuracion()

    remitente = ft.TextField(
        label="Tu correo de Gmail", value=actual["remitente"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    clave = ft.TextField(
        label="Clave de aplicación", value=actual["clave"] or "",
        password=True, can_reveal_password=True,
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    destino = ft.TextField(
        label="Destinatario habitual (opcional)", value=actual["destino"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    aviso = []
    if actual["remitente"] and actual["clave"] is None:
        aviso.append(ft.Text(
            "La clave guardada no se pudo leer con este PIN. Escríbela de nuevo.",
            size=12, color=paleta.AVISO))

    def guardar(e):
        problema.value = ""
        try:
            correo.guardar_configuracion(remitente.value, clave.value,
                                         destino.value)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.exito(page, "Correo configurado.")
        al_volver()

    def olvidar(e):
        def borrar():
            correo.olvidar_configuracion()
            dialogos.exito(page, "Datos del correo borrados.")
            al_volver()

        dialogos.confirmar(
            page, "Olvidar el correo",
            "Se borran el remitente y la clave de aplicación de este teléfono. "
            "El resumen semanal ya no se podrá enviar.",
            "Olvidar", borrar, peligro=True)

    acciones = [estilo.boton("Guardar", guardar, ancho=400, alto=46)]
    if correo.configurado():
        acciones.append(ft.TextButton(content="Olvidar estos datos",
                                      on_click=olvidar,
                                      style=ft.ButtonStyle(color=paleta.ERROR)))

    return ft.Column([
        _cabecera("Correo", al_volver,
                  "Por aquí te llega el resumen semanal"),
        ft.Container(content=ft.Column(aviso + [
            remitente, clave, destino, problema, *acciones,
            ft.Container(height=6),
            estilo.apunte("Gmail no acepta la contraseña de la cuenta: hace "
                          "falta una clave de aplicación. Se genera en la "
                          "configuración de la cuenta de Google, en Seguridad, y "
                          "solo aparece la opción si tienes activada la "
                          "verificación en dos pasos."),
            estilo.apunte("La clave se guarda cifrada con tu PIN. Si cambias el "
                          "PIN, se vuelve a cifrar sola."),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 16, 14, 20), expand=True),
    ], spacing=0, expand=True)



# ==========================================================================
# El respaldo: toda la base en un archivo
# ==========================================================================

def _estado_respaldo():
    cuando = basedatos.leer_config("respaldo_ultimo", "")
    if not cuando:
        return "Nunca hecho"
    dia = formato.dia_local(cuando)
    return f"Último el {dia.strftime('%d/%m/%Y')}"


def _respaldo(page, al_volver):
    return pantalla.repintable(
        page, lambda repintar: _cuerpo_respaldo(page, al_volver, repintar))


def _cuerpo_respaldo(page, al_volver, recargar):
    """Guardar la base en un archivo y volver a traerla.

    Va por correo y no «guardar en el teléfono» porque la carpeta privada de la
    aplicación **no la ve WhatsApp ni el explorador de archivos**: un respaldo que
    no se puede sacar del teléfono no es un respaldo. Mandándotelo a ti misma
    queda en el correo, que se abre desde cualquier parte.
    """
    estado = {"trabajando": False}
    configurado = correo.configurado()
    destino = ft.TextField(
        label="Mandármelo a", dense=True,
        value=correo.leer_configuracion()["destino"]
              or correo.leer_configuracion()["remitente"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)

    def enviar(e):
        if estado["trabajando"]:
            return

        def mandar():
            estado["trabajando"] = True
            page.update()

            def trabajo():
                datos = respaldo.armar()
                nombre = respaldo.nombre_sugerido()
                correo.enviar_pdf(
                    destino.value.strip(), datos, tipo="octet-stream",
                    asunto=f"ShopStore's · Respaldo · {nombre[-13:-3]}",
                    cuerpo="Adjunto va el respaldo de la aplicación.\n\n"
                           "Guarda este correo: con ese archivo se recupera todo "
                           "en un teléfono nuevo.",
                    nombre_archivo=nombre)
                basedatos.escribir_config("respaldo_ultimo", basedatos.ahora())
                return True, f"Respaldo enviado a {destino.value.strip()}."

            dialogos.en_segundo_plano(page, trabajo, recargar)

        dialogos.confirmar(
            page, "Enviar el respaldo",
            "Va toda la base en un archivo: productos, fotos, ventas, clientes y "
            "gastos. No lleva el PIN ni la clave del correo.",
            "Enviar", mandar)

    async def elegir_archivo(e):
        try:
            archivos = await selector.de(page).pick_files(
                dialog_title="Elige el archivo del respaldo", with_data=True)
        except Exception as ex:
            dialogos.error(page, f"No se pudo abrir el explorador: {ex}")
            return
        if not archivos:
            return
        _confirmar_restauracion(page, archivos[0].bytes, recargar)

    bloques = [
        estilo.tarjeta(ft.Column([
            estilo.seccion("Lo que hay ahora"),
            estilo.dato(f"{basedatos.contar_productos()} producto(s) · "
                        f"{basedatos.contar_ventas()} venta(s)", size=14),
            estilo.apunte(_estado_respaldo().lower()),
        ], spacing=4, tight=True)),
    ]

    if configurado:
        bloques += [
            destino,
            estilo.boton("Enviar el respaldo por correo", enviar,
                         ancho=400, alto=46),
        ]
    else:
        bloques.append(estilo.tarjeta(
            ft.Column([
                estilo.dato("Falta configurar el correo", size=13,
                            color=paleta.AVISO),
                estilo.apunte("Es por donde sale el respaldo del teléfono."),
            ], spacing=2, tight=True),
            padding=(12, 10, 12, 10), color_borde=paleta.AVISO))

    bloques += [
        ft.Divider(height=16, color=paleta.LILA),
        estilo.seccion("Teléfono nuevo"),
        estilo.apunte("Restaurar trae el archivo y reemplaza todo lo que haya en "
                      "este teléfono. Es para empezar en un equipo nuevo, no para "
                      "mezclar."),
        ft.TextButton(content="Restaurar desde un archivo", on_click=elegir_archivo,
                      style=ft.ButtonStyle(color=paleta.ERROR)),
        ft.Container(height=4),
        estilo.apunte("El archivo no lleva el PIN ni la clave del correo: están "
                      "cifradas con una llave de este teléfono y en otro no "
                      "servirían. Se vuelven a escribir una vez."),
    ]

    return ft.Column([
        _cabecera("Respaldo", al_volver, "Toda la base en un archivo"),
        ft.Container(content=ft.Column(bloques, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 16, 14, 20), expand=True),
    ], spacing=0, expand=True)


def _confirmar_restauracion(page, datos, al_terminar):
    """Dice qué trae el archivo **antes** de reemplazar nada.

    Restaurar no se deshace, y el error típico no es elegir un archivo roto sino
    elegir uno viejo. Ver «12 productos, 3 ventas» cuando hoy tienes 40 es lo que
    hace que la persona se detenga a tiempo.
    """
    try:
        resumen = respaldo.revisar(datos)
    except respaldo.ErrorDeRespaldo as ex:
        dialogos.error(page, str(ex))
        return

    def hacerlo():
        try:
            respaldo.restaurar(datos)
        except respaldo.ErrorDeRespaldo as ex:
            dialogos.error(page, str(ex))
            return
        dialogos.exito(page, "Respaldo restaurado.")
        al_terminar()

    dialogos.confirmar(
        page, "Restaurar este respaldo",
        f"El archivo trae {resumen['productos']} producto(s), "
        f"{resumen['ventas']} venta(s) y {resumen['clientes']} cliente(s). "
        f"Todo lo que hay hoy en el teléfono se reemplaza por eso.",
        "Restaurar", hacerlo, peligro=True)
