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
from frontend import dialogos
from frontend import estilo
from backend import nube
from frontend import paleta
from backend import seguridad


def crear_vista_configuracion(page, funcion_volver):
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
        elif cual == "nube":
            contenedor.content = _nube(page, menu)
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
                         bgcolor=paleta.BEIGE_CLARO, border_radius=8,
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
            _tarjeta("Respaldo en la nube", _estado_nube(),
                     lambda e: abrir("nube")),
            _tarjeta("Correo del catálogo",
                     "Configurado" if correo.configurado()
                     else "Sin configurar",
                     lambda e: abrir("correo")),
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


# ==========================================================================
# Métodos de pago
# ==========================================================================

def _metodos(page, al_volver):
    contenedor = ft.Container(expand=True)

    def recargar():
        contenedor.content = _metodos(page, al_volver).content
        page.update()

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

    contenedor.content = ft.Column([
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

    return contenedor


def _formulario_metodo(page, existente, al_terminar):
    nombre = ft.TextField(
        label="Nombre", value=existente["nombre"] if existente else "",
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
    moneda = ft.Dropdown(
        label="Moneda", value=existente["moneda"] if existente else "Bs",
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA,
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
                            border_color=paleta.BEIGE,
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
# El correo por donde sale el catálogo
# ==========================================================================

def _correo(page, al_volver):
    """La clave de aplicación se guarda **cifrada con el PIN**, así que solo se
    puede leer con la sesión abierta. Si venía de otro teléfono no se descifra, y
    entonces el campo aparece vacío pidiendo que se escriba de nuevo."""
    actual = correo.leer_configuracion()

    remitente = ft.TextField(
        label="Tu correo de Gmail", value=actual["remitente"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
    clave = ft.TextField(
        label="Clave de aplicación", value=actual["clave"] or "",
        password=True, can_reveal_password=True,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
    destino = ft.TextField(
        label="Destinatario habitual (opcional)", value=actual["destino"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
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
            "El catálogo se seguirá pudiendo generar, pero no enviar.",
            "Olvidar", borrar, peligro=True)

    acciones = [estilo.boton("Guardar", guardar, ancho=400, alto=46)]
    if correo.configurado():
        acciones.append(ft.TextButton(content="Olvidar estos datos",
                                      on_click=olvidar,
                                      style=ft.ButtonStyle(color=paleta.ERROR)))

    return ft.Column([
        _cabecera("Correo del catálogo", al_volver,
                  "Por aquí sale el PDF del teléfono"),
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
# El respaldo en la nube
# ==========================================================================

def _estado_nube():
    if not nube.configurado():
        return "Sin configurar"
    faltan = nube.total_pendiente()
    ultimo = nube.ultimo_respaldo()
    cuando = f"ultimo el {ultimo[8:10]}/{ultimo[5:7]}" if ultimo else "nunca hecho"
    return f"{cuando} - {faltan} sin subir" if faltan else f"{cuando} - al dia"


def _nube(page, al_volver):
    """La copia que sobrevive al telefono.

    La pantalla dice siempre **cuanto falta por subir**: un respaldo del que no se
    sabe si esta al dia no tranquiliza a nadie.
    """
    contenedor = ft.Container(expand=True)
    estado = {"trabajando": False}

    def recargar():
        contenedor.content = _nube(page, al_volver).content
        page.update()

    cadena = ft.TextField(
        label="Cadena de conexion de Neon",
        hint_text="postgresql://usuario:clave@ep-xxx.neon.tech/basededatos",
        value=nube.leer_cadena() or "",
        password=True, can_reveal_password=True,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)
    avance = estilo.apunte("")

    def guardar(e):
        problema.value = ""
        try:
            nube.guardar_cadena(cadena.value)
        except nube.ErrorDeNube as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.exito(page, "Conexion guardada.")
        recargar()

    def probar(e):
        if estado["trabajando"]:
            return
        estado["trabajando"] = True
        avance.value = "Conectando..."
        page.update()

        def trabajo():
            version = nube.probar(cadena.value or None)
            return True, f"Conectado: {version}"

        def terminar():
            estado["trabajando"] = False
            avance.value = ""
            page.update()

        dialogos.en_segundo_plano(page, trabajo, terminar)

    def respaldar(e):
        if estado["trabajando"]:
            return

        def hacerlo():
            estado["trabajando"] = True
            avance.value = "Subiendo..."
            page.update()

            def informar(texto):
                avance.value = f"Subiendo... {texto}"
                page.update()

            def trabajo():
                subidas = nube.respaldar(informar)
                total = sum(subidas.values())
                return True, (f"Respaldo al dia: {total} fila(s) subidas."
                              if total else "Ya estaba todo respaldado.")

            def terminar():
                estado["trabajando"] = False
                recargar()

            dialogos.en_segundo_plano(page, trabajo, terminar)

        faltan = nube.total_pendiente()
        dialogos.confirmar(
            page, "Respaldar ahora",
            (f"Se suben {faltan} fila(s) a la copia de la nube. "
             f"Nada del telefono se modifica.") if faltan
            else "No hay nada pendiente; se comprobara igual.",
            "Respaldar", hacerlo)

    def restaurar(e):
        if estado["trabajando"]:
            return

        def paso_dos(conteo):
            arriba = sum(conteo.values())
            productos = basedatos.contar_productos()
            ventas = basedatos.contar_ventas()

            def hacerlo():
                estado["trabajando"] = True
                avance.value = "Bajando..."
                page.update()

                def informar(texto):
                    avance.value = f"Bajando... {texto}"
                    page.update()

                def trabajo():
                    traidas = nube.restaurar(informar)
                    return True, (f"Restaurado: {sum(traidas.values())} fila(s). "
                                  f"Cierra y vuelve a abrir la aplicacion.")

                def terminar():
                    estado["trabajando"] = False
                    recargar()

                dialogos.en_segundo_plano(page, trabajo, terminar)

            # Se dice exactamente que se pierde, con numeros. "Estas seguro?" no
            # alcanza para algo que borra el inventario y las ventas.
            dialogos.confirmar(
                page, "Reemplazar todo lo del telefono",
                f"Se BORRAN los {productos} producto(s) y las {ventas} venta(s) "
                f"que hay en este telefono, y se escriben las {arriba} fila(s) de "
                f"la copia. Esto no se puede deshacer.",
                "Si, reemplazar", hacerlo, peligro=True)

        estado["trabajando"] = True
        avance.value = "Mirando que hay en la copia..."
        page.update()

        resultado = {}

        def trabajo():
            resultado["conteo"] = nube.resumen_de_la_copia()
            return True, None      # sin aviso: el paso siguiente es el dialogo

        def terminar():
            estado["trabajando"] = False
            avance.value = ""
            page.update()
            if "conteo" in resultado:
                paso_dos(resultado["conteo"])

        dialogos.en_segundo_plano(page, trabajo, terminar)

    faltan = nube.pendientes()
    ultimo = nube.ultimo_respaldo()

    bloques = [cadena, problema,
               ft.Row([
                   estilo.boton("Guardar", guardar, expand=True),
                   estilo.boton("Probar conexion", probar, principal=False,
                                expand=True),
               ], spacing=8),
               avance]

    if nube.configurado():
        detalle = [estilo.seccion("Estado del respaldo"),
                   estilo.dato(f"Ultimo: {ultimo[:16].replace(chr(84), chr(32))}"
                               if ultimo else "Nunca se ha respaldado", size=13)]
        if faltan:
            detalle.append(estilo.apunte(
                " - ".join(f"{tabla}: {n}" for tabla, n in faltan.items())))
            detalle.append(estilo.dato(f"{sum(faltan.values())} fila(s) sin subir",
                                       size=13, color=paleta.AVISO))
        else:
            detalle.append(estilo.dato("Todo subido", size=13, color=paleta.OK))

        bloques += [
            estilo.tarjeta(ft.Column(detalle, spacing=4, tight=True),
                           color_borde=paleta.AVISO if faltan else None),
            estilo.boton("Respaldar ahora", respaldar, ancho=400, alto=46),
            ft.Divider(height=16, color=paleta.BEIGE),
            estilo.seccion("Telefono nuevo"),
            estilo.apunte("Restaurar trae la copia y reemplaza todo lo que haya "
                          "en este telefono. Es para empezar en un equipo nuevo, "
                          "no para mezclar."),
            ft.TextButton(content="Restaurar desde la nube", on_click=restaurar,
                          style=ft.ButtonStyle(color=paleta.ERROR)),
            ft.TextButton(content="Olvidar esta conexion",
                          on_click=lambda e: _olvidar_nube(page, recargar),
                          style=ft.ButtonStyle(color=paleta.TEXTO_SUAVE)),
        ]

    bloques.append(estilo.apunte(
        "La cadena lleva la contrasena adentro, asi que se guarda cifrada con tu "
        "PIN. La aplicacion funciona completa sin esto: el respaldo puede esperar, "
        "la venta no."))

    contenedor.content = ft.Column([
        _cabecera("Respaldo en la nube", al_volver,
                  nube.host_guardado() or "Copia de seguridad en Neon"),
        ft.Container(content=ft.Column(bloques, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 16, 14, 20), expand=True),
    ], spacing=0, expand=True)

    return contenedor


def _olvidar_nube(page, al_terminar):
    def borrar():
        nube.olvidar()
        dialogos.exito(page, "Conexion borrada de este telefono.")
        al_terminar()

    dialogos.confirmar(
        page, "Olvidar la conexion",
        "Se borra la cadena de este telefono. La copia que ya esta en la nube no "
        "se toca.",
        "Olvidar", borrar, peligro=True)
