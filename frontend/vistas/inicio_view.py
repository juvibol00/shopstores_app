"""Inicio: lo primero que se ve al abrir la aplicación.

El orden no es decorativo, es de urgencia:

1. **La marca y el saludo** — dónde estoy.
2. **La tasa del día** — lo que más se consulta, y lo que más caro sale si queda
   vieja: una tasa de ayer no da ningún error, simplemente cobra mal en bolívares
   toda la jornada.
3. **Lo que reclama acción** — el resumen semanal sin enviar, quién debe.
4. **Cómo va el negocio** — las cifras del día y el estado del inventario.

Lo que reclama acción va en franjas de color (esquina recta, línea a la izquierda) y
lo que solo informa va en tarjetas redondeadas. Esa diferencia de forma es la que
hace que un aviso se note sin tener que gritarlo con color.
"""

from datetime import datetime, timezone

import flet as ft

from backend import almacenamiento
from backend import basedatos
from backend import correo
from frontend import dialogos
from frontend import estilo
from backend import formato
from frontend import marca
from frontend import paleta
from backend import resumen_semanal


def _antiguedad(iso, ahora=None):
    """Cuántos días pasaron desde que se guardó la tasa, y cómo decirlo.

    **Los dos lados de la resta van en hora local.** Antes se restaba el día en
    UTC menos el día local, y en Venezuela (UTC−4) eso adelanta el día a partir de
    las ocho de la noche: una tasa guardada a las 22:30 se leía «actualizada
    ayer» al instante, y la tarjeta se pintaba como vieja. Es el mismo error que
    ya había borrado las ventas de la noche del gráfico.
    """
    if not iso:
        return None, "sin cargar"
    try:
        cuando = datetime.fromisoformat(iso)
    except ValueError:
        return None, "sin cargar"
    if cuando.tzinfo is None:
        cuando = cuando.replace(tzinfo=timezone.utc)
    ahora = ahora or datetime.now().astimezone()
    dias = (ahora.astimezone().date() - cuando.astimezone().date()).days
    if dias <= 0:
        return 0, "actualizada hoy"
    if dias == 1:
        return 1, "actualizada ayer"
    return dias, f"actualizada hace {dias} días"


def _encabezado(nombre, funcion_configuracion):
    """El logo y el saludo. No usa `estilo.encabezado` porque es el único de la
    aplicación con logo: es la portada, no una pantalla más."""
    return ft.Container(
        content=ft.Column([
            ft.Row([
                marca.logo(46),
                ft.Column([
                    ft.Text("ShopStore's", size=19, weight=estilo.FUERTE,
                            color=paleta.MARCA),
                    estilo.apunte("Gestión de ventas"),
                ], spacing=0, tight=True, expand=True),
                ft.IconButton(icon=ft.Icons.SETTINGS, icon_color=paleta.MARCA,
                              tooltip="Configuración",
                              on_click=lambda e: funcion_configuracion()),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(height=2),
            estilo.dato(f"Hola, {nombre}" if nombre else "Hola", size=15),
        ], spacing=6, tight=True),
        bgcolor=paleta.LILA_CLARO,
        padding=ft.Padding(16, 14, 10, 16),
    )


def _tarjeta_tasa(page, al_cambiar):
    tasa = basedatos.leer_tasa()
    dias, texto_edad = _antiguedad(basedatos.tasa_actualizada_en())
    vieja = tasa <= 0 or (dias is not None and dias >= 1)

    def actualizar(e):
        anterior = basedatos.leer_tasa()

        def confirmar_y_guardar(valor):
            def guardar():
                try:
                    basedatos.guardar_tasa(valor)
                except ValueError as ex:
                    dialogos.error(page, str(ex))
                    return
                dialogos.exito(page, f"Tasa actualizada a {formato.bolivares(valor)}.")
                al_cambiar()

            if anterior <= 0:
                guardar()
                return
            # Siempre se muestra de qué valor a qué valor va: la tasa entra en el
            # precio en bolívares de cada venta, así que un dedazo descuadra la caja.
            dialogos.confirmar(
                page, "Confirmar la tasa",
                f"Va a pasar de {formato.bolivares(anterior)} a "
                f"{formato.bolivares(valor)} por dólar. Con esta tasa se calculan "
                f"los cobros en bolívares y el "
                f"vuelto de todas las ventas de hoy.",
                "Cambiar la tasa", guardar)

        dialogos.pedir_numero(
            page, "Tasa del día",
            "Cuántos bolívares vale un dólar hoy.",
            "Bolívares por dólar",
            f"{tasa:g}" if tasa > 0 else "",
            confirmar_y_guardar,
            texto_vivo=lambda v: (
                f"$ 1 = {formato.bolivares(v)}   ·   "
                f"$ 10 = {formato.bolivares(v * 10)}") if v > 0 else "")

    if tasa > 0:
        valor = estilo.cifra(formato.bolivares(tasa), size=26)
        detalle = ft.Text(f"por dólar · {texto_edad}", size=12,
                          weight=estilo.NORMAL,
                          color=paleta.AVISO if vieja else paleta.TEXTO_SUAVE)
    else:
        valor = estilo.cifra("Sin cargar", size=22, color=paleta.AVISO)
        detalle = estilo.apunte("Hace falta para cobrar en bolívares", size=12)

    return estilo.tarjeta(
        ft.Row([
            ft.Column([
                estilo.seccion("Tasa del día"),
                valor,
                detalle,
            ], spacing=2, tight=True, expand=True),
            estilo.boton("Actualizar", actualizar, principal=vieja),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        color_borde=paleta.AVISO if vieja else None,
    )


def _tarjeta_dato(etiqueta, valor, color=None):
    """Va dentro de una fila, así que necesita `expand`: sin él se encoge al ancho
    de su contenido y «Ventas: 0» queda mucho más angosta que «Valor a costo»."""
    return estilo.tarjeta(
        ft.Column([
            estilo.seccion(etiqueta),
            ft.Text(valor, size=22, weight=estilo.FUERTE,
                    color=color or paleta.TEXTO),
        ], spacing=4, tight=True),
        padding=(16, 14, 16, 16), expand=True)


def _franja(titulo, detalle, color, accion=None, al_tocar=None):
    """Lo que reclama atención: franja de color, esquina recta."""
    fila = [ft.Column([
        estilo.dato(titulo, size=13, color=color if accion is None else paleta.TEXTO),
        estilo.apunte(detalle),
    ], spacing=2, tight=True, expand=True)]
    if accion is not None:
        fila.append(accion)
    return estilo.tarjeta(ft.Row(fila, spacing=8), padding=(12, 10, 8, 10),
                          color_borde=color, al_tocar=al_tocar)


def _aviso_resumen(page, al_terminar):
    """El resumen de la semana pasada, cuando todavía no se mandó.

    No se manda solo: en el teléfono no hay servicio en segundo plano, y disparar un
    correo por datos móviles sin avisar es más intrusivo que en una computadora
    encendida todo el día. Pero **tampoco se pierde la semana**: el aviso sigue ahí
    hasta que se toque, sea lunes o jueves. Es la corrección de un error que en
    SELL-B costó semanas enteras sin reporte.
    """
    try:
        if not resumen_semanal.hay_pendiente() or not correo.configurado():
            return []
    except Exception:
        # Un fallo calculando el resumen no puede impedir que Inicio abra.
        return []

    d = resumen_semanal.datos()

    def enviar(e):
        def mandar():
            # Igual que el catálogo: el correo tarda, así que va a otro hilo.
            def trabajo():
                resumen_semanal.enviar()
                return True, "Resumen de la semana enviado."

            dialogos.en_segundo_plano(page, trabajo, al_terminar)

        dialogos.confirmar(
            page, "Enviar el resumen",
            f"Semana del {d['titulo']}. "
            f"Ganancia neta {formato.dinero(d['metricas']['neta'])} en "
            f"{d['metricas']['ventas']} venta(s).",
            "Enviármelo", mandar)

    return [_franja(
        "Resumen de la semana pasada",
        f"{d['titulo']} · listo para enviar",
        paleta.MARCA_CLARA,
        accion=ft.TextButton(content="Enviármelo", on_click=enviar,
                             style=ft.ButtonStyle(color=paleta.MARCA)))]


def _avisos_de_cobro(funcion_navegar):
    """Quién venció y quién vence esta semana, lo primero al abrir la aplicación.

    Es el recordatorio del que hablamos: no suena una notificación con la aplicación
    cerrada, pero apenas se abre está arriba y ordenado por urgencia. La lógica de
    vencimientos vive en `basedatos.avisos_de_cobro`, así que el día que se quiera
    la notificación de Android se enchufa encima sin rehacer nada.
    """
    vencidos, proximos = basedatos.avisos_de_cobro(dias_aviso=7)
    if not vencidos and not proximos:
        return []

    def tarjeta(fila, texto, color):
        return estilo.tarjeta(
            ft.Row([
                ft.Column([
                    estilo.dato(fila["nombre"], lineas=1),
                    estilo.apunte(texto, color=color),
                ], spacing=1, tight=True, expand=True),
                estilo.cifra(formato.dinero(fila["saldo"]), size=16),
            ], spacing=8),
            padding=(12, 10, 12, 10), color_borde=color,
            al_tocar=lambda e: funcion_navegar("cobros"))

    bloques = [ft.Row([
        estilo.seccion("Por cobrar"),
        ft.Container(expand=True),
        ft.TextButton(content="Ver todo",
                      on_click=lambda e: funcion_navegar("cobros"),
                      style=ft.ButtonStyle(color=paleta.MARCA)),
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    for fila, dias in vencidos:
        bloques.append(tarjeta(
            fila, f"venció hace {dias} día{'s' if dias != 1 else ''}",
            paleta.ERROR))
    for fila, dias in proximos:
        cuando = ("vence hoy" if dias == 0 else
                  "vence mañana" if dias == 1 else f"vence en {dias} días")
        bloques.append(tarjeta(fila, cuando, paleta.AVISO))
    return bloques


def _avisos(resumen):
    pendientes = []
    # Las dos cosas que hacen mentir a las métricas, dichas donde se ven al entrar.
    if resumen["sin_costo"]:
        pendientes.append((f"{resumen['sin_costo']} producto(s) sin costo cargado",
                           "Sin el costo, la ganancia sale inflada.", paleta.AVISO))
    if resumen["bajo_costo"]:
        pendientes.append((f"{resumen['bajo_costo']} producto(s) por debajo del costo",
                           "Cada venta de esos pierde dinero.", paleta.ERROR))
    if resumen["sin_stock"]:
        pendientes.append((f"{resumen['sin_stock']} producto(s) sin existencia",
                           "No se pueden vender hasta reponer.", paleta.TEXTO_SUAVE))
    if not pendientes:
        return []
    return [estilo.seccion("Atención")] + [
        _franja(titulo, detalle, color) for titulo, detalle, color in pendientes
    ]


def crear_vista_inicio(page, funcion_navegar, funcion_configuracion):
    nombre = almacenamiento.obtener("nombre_usuario", "")
    resumen = basedatos.resumen_inventario()
    hoy = basedatos.resumen_de_hoy()

    contenedor = ft.Container(expand=True)

    def refrescar():
        contenedor.content = crear_vista_inicio(
            page, funcion_navegar, funcion_configuracion).content
        page.update()

    contenedor.content = ft.Column([
        _encabezado(nombre, funcion_configuracion),
        ft.Container(content=ft.Column([
            _tarjeta_tasa(page, refrescar),
            *_aviso_resumen(page, refrescar),
            *_avisos_de_cobro(funcion_navegar),
            estilo.seccion("Hoy"),
            ft.Row([
                _tarjeta_dato("Ventas", str(hoy["ventas"])),
                _tarjeta_dato("Ingreso", formato.dinero(hoy["ingreso"]),
                              color=paleta.MARCA),
            ], spacing=10),
            estilo.seccion("Inventario"),
            ft.Row([
                _tarjeta_dato("Productos", str(resumen["productos"])),
                _tarjeta_dato("Valor a costo", formato.dinero(resumen["valor_costo"])),
            ], spacing=10),
            *_avisos(resumen),
            ft.Container(height=4),
            ft.Row([
                estilo.boton("Vender", lambda e: funcion_navegar("venta"),
                             expand=True, alto=46),
                estilo.boton("Inventario",
                             lambda e: funcion_navegar("inventario"),
                             principal=False, expand=True, alto=46),
            ], spacing=10),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)

    return contenedor