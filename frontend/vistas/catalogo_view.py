"""Catálogo: elegir qué entra, generarlo y mandarlo.

Cuelga de Inventario porque es una vista de los mismos productos: qué se muestra y
a qué precio. No gasta una pestaña propia — se arma cada tanto, no todos los días.

Antes de generar nada dice cuántos productos van a entrar y cuántos irán marcados
«A pedido». Generar un PDF para descubrir que salieron tres productos es perder el
viaje.
"""

import flet as ft

from backend import basedatos
from backend import catalogo
from backend import correo
from frontend import dialogos
from frontend import estilo
from frontend import paleta


def crear_vista_catalogo(page, al_volver, al_configurar_correo):
    contenedor = ft.Container(expand=True)
    estado = {"pdf": None, "productos": 0, "paginas": 0, "enviando": False}

    incluir = ft.Switch(
        label="Incluir productos sin existencia",
        value=basedatos.leer_config("catalogo_incluye_sin_stock", "1") == "1",
        active_color=paleta.MARCA)
    resumen = ft.Text("", size=13, weight=estilo.MEDIO,
                      color=paleta.TEXTO_SUAVE)
    aviso_foto = ft.Text("", size=11, weight=estilo.MEDIO, color=paleta.AVISO)
    estado_pdf = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.OK)
    destino = ft.TextField(
        label="Mandárselo a", dense=True,
        value=correo.leer_configuracion()["destino"],
        keyboard_type=ft.KeyboardType.EMAIL,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA)
    boton_enviar = ft.ElevatedButton(
        content="Enviar por correo", width=400, height=46, disabled=True,
        style=ft.ButtonStyle(bgcolor=paleta.MARCA, color=paleta.FONDO))

    def refrescar_conteo(e=None):
        # El interruptor se recuerda: se elige una vez y no en cada envío.
        basedatos.escribir_config("catalogo_incluye_sin_stock",
                                  "1" if incluir.value else "0")
        c = catalogo.cuantos_entran(incluir.value)
        partes = [f"{c['total']} producto{'s' if c['total'] != 1 else ''}"]
        if incluir.value and c["a_pedido"]:
            partes.append(f"{c['a_pedido']} marcado(s) «A pedido»")
        resumen.value = " · ".join(partes)
        aviso_foto.value = (f"{c['sin_foto']} sin foto: van con un recuadro vacío."
                            if c["sin_foto"] else "")
        # Cambiar lo que entra invalida el PDF ya armado.
        estado["pdf"] = None
        estado_pdf.value = ""
        boton_enviar.disabled = True
        page.update()

    incluir.on_change = refrescar_conteo

    def generar(e):
        try:
            pdf, productos, paginas = catalogo.armar(incluir.value)
        except catalogo.SinProductos as ex:
            dialogos.error(page, str(ex))
            return
        except Exception as ex:
            dialogos.error(page, f"No se pudo armar el catálogo: {ex}")
            return
        estado.update({"pdf": pdf, "productos": productos, "paginas": paginas,
                       "a_pedido": catalogo.cuantos_entran(
                           incluir.value)["a_pedido"] if incluir.value else 0})
        estado_pdf.value = (f"Listo: {productos} producto(s), {paginas} página(s), "
                            f"{len(pdf) / 1024:.0f} KB")
        boton_enviar.disabled = not correo.configurado()
        page.update()

    def enviar(e):
        if estado["enviando"]:
            return
        if not estado["pdf"]:
            dialogos.error(page, "Primero hay que generar el catálogo.")
            return

        def mandar():
            # Se bloquea el botón **antes** de empezar y el envío se va a otro
            # hilo. Hecho en el hilo de la interfaz, la pantalla se congelaba
            # varios segundos, parecía que no había pasado nada, y cada toque
            # extra encolaba otro envío.
            estado["enviando"] = True
            a_donde = destino.value.strip()
            boton_enviar.disabled = True
            boton_enviar.content = "Enviando…"
            page.update()

            def trabajo():
                a_pedido = estado.get("a_pedido", 0)
                correo.enviar_pdf(
                    a_donde, estado["pdf"], asunto="Catálogo",
                    cuerpo=catalogo.cuerpo_texto(a_pedido),
                    html=catalogo.cuerpo_html(a_pedido))
                basedatos.escribir_config("catalogo_ultimo_destino", a_donde)
                return True, f"Catálogo enviado a {a_donde}."

            def terminar():
                estado["enviando"] = False
                boton_enviar.disabled = False
                boton_enviar.content = "Enviar por correo"
                page.update()

            dialogos.en_segundo_plano(page, trabajo, terminar)

        dialogos.confirmar(
            page, "Enviar el catálogo",
            f"{estado['productos']} producto(s) en {estado['paginas']} página(s), "
            f"a {destino.value.strip()}.",
            "Enviar", mandar)

    boton_enviar.on_click = enviar

    cuerpo = [
        estilo.tarjeta(ft.Column([
            incluir,
            resumen,
            aviso_foto,
        ], spacing=6, tight=True), padding=(16, 12, 16, 12)),
        estilo.boton("Generar el catálogo", generar, ancho=400, alto=46),
        estado_pdf,
    ]

    if correo.configurado():
        cuerpo += [destino, boton_enviar]
    else:
        cuerpo.append(estilo.tarjeta(
            ft.Row([
                ft.Column([
                    estilo.dato("Falta configurar el correo", size=13,
                                color=paleta.AVISO),
                    estilo.apunte("Es por donde sale el catálogo del teléfono."),
                ], spacing=2, tight=True, expand=True),
                ft.TextButton(content="Configurar",
                              on_click=lambda e: al_configurar_correo(),
                              style=ft.ButtonStyle(color=paleta.MARCA)),
            ]),
            padding=(12, 10, 8, 10), color_borde=paleta.AVISO))

    cuerpo.append(estilo.apunte(
        "Mandártelo a ti misma también sirve: al abrirlo en el teléfono y "
        "descargar el adjunto, WhatsApp ya lo puede reenviar."))

    contenedor.content = ft.Column([
        estilo.encabezado(
            "Catálogo", "Se arma con los productos marcados para mostrar",
            al_volver=al_volver),
        ft.Container(content=ft.Column(cuerpo, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)

    refrescar_conteo()
    return contenedor
