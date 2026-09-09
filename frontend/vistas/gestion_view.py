"""Gestión: de lo vendido a la ganancia neta, y los gastos que la determinan.

La cascada se muestra completa y en orden, porque cada resta explica la siguiente:

    Ingresos − Costo de lo vendido = Ganancia bruta
    Ganancia bruta − Gastos        = Ganancia neta

Sin la última línea, el número que se ve es el bruto y se siente como ganancia. Ese
es justamente el error que el módulo de gastos viene a corregir.

**Se cuenta por venta, no por cobro.** Una venta a crédito entra el día que se hizo,
igual que su costo. Por eso además se muestra «entró en caja»: un negocio puede
tener buena ganancia y nada de dinero en la mano si vendió todo a crédito.

El gráfico se dibuja con contenedores, no con una librería: son siete barras y no
justifica sumar una dependencia que después hay que empaquetar en el APK.
"""

from datetime import datetime, timedelta

import flet as ft

from backend import basedatos
from backend import correo
from frontend import dialogos
from frontend import estilo
from backend import formato
from frontend import paleta
from frontend import pantalla
from backend import resumen_semanal

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def crear_vista_gestion(page):
    contenedor = ft.Container(expand=True)
    estado = {"periodo": "semana"}

    def resumen():
        contenedor.content = _resumen(page, estado, resumen, gastos)
        page.update()

    def gastos():
        contenedor.content = _gastos(page, estado, resumen)
        page.update()

    contenedor.content = _resumen(page, estado, resumen, gastos)
    return contenedor


def _dia_corto(fecha):
    return f"{fecha.day} {formato.MESES_CORTOS[fecha.month - 1]}"


def _rango_legible(m):
    """«5 sep» o «31 ago – 5 sep»: qué días está mirando exactamente.

    Sin esto, «Esta semana» obliga a adivinar si el lunes entra o no, y si el mes
    va de corrido o desde el día 1.
    """
    desde = datetime.fromisoformat(m["desde"]).astimezone().date()
    hasta = datetime.fromisoformat(m["hasta"]).astimezone().date() - timedelta(days=1)
    if desde == hasta:
        return _dia_corto(hasta)
    return f"{_dia_corto(desde)} – {_dia_corto(hasta)}"


PERIODOS = [("hoy", "Hoy"), ("semana", "Semana"), ("mes", "Mes")]


def _encabezado(titulo, subtitulo, estado, al_cambiar, al_volver=None):
    """El selector vive **dentro** del encabezado, junto al rango de fechas que
    describe. Separado del cuerpo, parecía un control suelto sin dueño."""
    def elegir(periodo):
        estado["periodo"] = periodo
        al_cambiar()

    return estilo.encabezado(
        titulo, subtitulo, al_volver=al_volver,
        extra=estilo.pastillas(PERIODOS, estado["periodo"], elegir,
                               sobre_beige=True))


def _linea(etiqueta, valor, color=None, tamano=14, signo=""):
    return ft.Row([
        estilo.seccion(etiqueta),
        ft.Container(expand=True),
        ft.Text(f"{signo}{formato.dinero(valor)}", size=tamano, weight=estilo.FUERTE,
                color=color or paleta.TEXTO),
    ])


def _grafico(serie):
    """Barras apiladas: la ganancia arriba en verde, el costo abajo en beige.

    La escala sale del ingreso más alto y no de la ganancia, para que la porción de
    costo se vea en su proporción real. Es la misma lectura del reporte semanal de
    SELL-B.
    """
    if not serie or all(d["vendido"] <= 0 for d in serie):
        return ft.Container()

    tope = max(d["vendido"] for d in serie) or 1
    ALTO = 90

    columnas = []
    for d in serie:
        alto_total = round(ALTO * d["vendido"] / tope)
        alto_costo = round(alto_total * (d["costo"] / d["vendido"])) if d["vendido"] else 0
        alto_ganancia = max(0, alto_total - alto_costo)
        columnas.append(ft.Column([
            ft.Container(height=ALTO - alto_total),
            ft.Container(height=alto_ganancia, bgcolor=paleta.OK,
                         border_radius=3, width=18),
            ft.Container(height=alto_costo, bgcolor=paleta.BEIGE, width=18),
            estilo.apunte(DIAS[d["dia"].weekday()], size=10),
        ], spacing=0, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER))

    return estilo.tarjeta(
        ft.Column([
            ft.Row(columnas, spacing=6, wrap=False,
                   vertical_alignment=ft.CrossAxisAlignment.END,
                   scroll=ft.ScrollMode.AUTO),
            ft.Row([
                ft.Container(width=10, height=10, bgcolor=paleta.OK,
                             border_radius=2),
                estilo.apunte("ganancia", size=10),
                ft.Container(width=10, height=10, bgcolor=paleta.BEIGE,
                             border_radius=2),
                estilo.apunte("costo", size=10),
            ], spacing=5),
        ], spacing=8, tight=True),
        padding=(14, 14, 14, 10))


def _tarjeta_credito():
    """El crédito que está en la calle: facturado y todavía no cobrado.

    Va aparte y dice «al día de hoy» porque **no es una cifra del período**: las
    demás miden un tramo de tiempo, esta es una foto del momento. Sin esa aclaración
    se lee como si fuera de la semana elegida.
    """
    c = basedatos.total_por_cobrar()
    if c["total"] <= 0:
        return estilo.tarjeta(ft.Column([
            estilo.seccion("Crédito pendiente"),
            estilo.dato("Nada en la calle", size=16, color=paleta.OK),
        ], spacing=2, tight=True), padding=(16, 12, 16, 12))

    detalle = (f"{c['facturas']} factura{'s' if c['facturas'] != 1 else ''} de "
               f"{c['clientes']} cliente{'s' if c['clientes'] != 1 else ''}"
               f" · al día de hoy")

    lineas = [
        estilo.seccion("Crédito pendiente"),
        estilo.cifra(formato.dinero(c["total"]), size=22),
        estilo.apunte("facturado y no cobrado"),
    ]
    if c["vencido"] > 0:
        lineas.append(estilo.dato(f"{formato.dinero(c['vencido'])} ya vencido", size=12,
                                  color=paleta.ERROR))
    lineas.append(estilo.apunte(detalle))

    return estilo.tarjeta(
        ft.Column(lineas, spacing=2, tight=True), padding=(14, 12, 14, 12),
        color_borde=paleta.ERROR if c["vencido"] > 0 else paleta.MARCA_CLARA)


def _boton_resumen(page, al_terminar):
    """Manda el resumen de la semana pasada, se haya mandado ya o no.

    En Inicio aparece solo cuando está pendiente; aquí está siempre, para poder
    reenviarlo o mandárselo a otra dirección.
    """
    if not correo.configurado():
        return estilo.apunte("Configura el correo para poder enviarte el resumen "
                             "semanal.")

    # Sin ventas la semana pasada no hay nada que contar. Se dice en vez de dejar
    # un botón que manda un correo en ceros.
    d = resumen_semanal.datos()
    if d["metricas"]["ventas"] == 0:
        return estilo.apunte(f"Sin ventas del {d['titulo']}: no hay resumen "
                             f"semanal que enviar todavía.")

    ya = resumen_semanal.ultimo_enviado() == resumen_semanal.marcador()

    def enviar(e):
        d = resumen_semanal.datos()

        def mandar():
            def trabajo():
                resumen_semanal.enviar()
                return True, "Resumen enviado."

            dialogos.en_segundo_plano(page, trabajo, al_terminar)

        dialogos.confirmar(
            page, "Resumen de la semana pasada",
            f"Semana del {d['titulo']}. "
            f"Ganancia neta {formato.dinero(d['metricas']['neta'])} en "
            f"{d['metricas']['ventas']} venta(s).",
            "Enviar", mandar)

    return ft.TextButton(
        content=("Reenviar el resumen semanal" if ya
                 else "Enviarme el resumen semanal"),
        on_click=enviar, style=ft.ButtonStyle(color=paleta.MARCA))


def _resumen(page, estado, al_cambiar, al_ver_gastos):
    m = basedatos.metricas(estado["periodo"])
    top = basedatos.top_productos(estado["periodo"])
    serie = basedatos.serie_diaria(estado["periodo"])

    bloques = [
        estilo.tarjeta(ft.Column([
            estilo.seccion(m["etiqueta"]),
            estilo.cifra(formato.dinero(m["neta"]), size=32,
                         color=paleta.OK if m["neta"] >= 0 else paleta.ERROR),
            estilo.apunte(f"ganancia neta · margen {m['margen']:.1f} %", size=12),
        ], spacing=2, tight=True)),
    ]

    if m["sin_costo"]:
        # Sin costo cargado, ese producto aparenta ganancia pura y el margen de
        # arriba sale inflado. Decirlo acá es lo que evita creerle al número.
        bloques.append(estilo.tarjeta(ft.Column([
            estilo.dato(f"{m['sin_costo']} producto(s) sin costo cargado",
                        size=13, color=paleta.AVISO),
            estilo.apunte("Mientras no tengan costo, la ganancia sale inflada."),
        ], spacing=2, tight=True), padding=(12, 10, 12, 10),
            color_borde=paleta.AVISO))

    bloques.append(estilo.tarjeta(
        ft.Column([
            _linea("Ingresos", m["vendido"]),
            _linea("Costo de lo vendido", m["costo"], signo="− "),
            ft.Divider(height=10, color=paleta.BEIGE),
            _linea("Ganancia bruta", m["bruta"], color=paleta.TEXTO, tamano=15),
            _linea("Gastos", m["gastos"], signo="− "),
            ft.Divider(height=10, color=paleta.BEIGE),
            _linea("Ganancia neta", m["neta"],
                   color=paleta.OK if m["neta"] >= 0 else paleta.ERROR, tamano=17),
        ], spacing=8, tight=True)))

    bloques.append(estilo.tarjeta(ft.Column([
        estilo.seccion("Entró en caja"),
        estilo.cifra(formato.dinero(m["entro_en_caja"]), size=20),
        estilo.apunte(f"{m['ventas']} venta(s) en el período"),
    ], spacing=1, tight=True), padding=(16, 12, 16, 12)))

    bloques.append(_tarjeta_credito())

    grafico = _grafico(serie)
    if grafico.content is not None:
        bloques.append(grafico)

    if top:
        bloques.append(estilo.seccion("Lo que más se vendió"))
        for t in top:
            bloques.append(estilo.tarjeta(
                ft.Row([
                    ft.Column([
                        estilo.dato(t["nombre"], lineas=1),
                        estilo.apunte(f"{float(t['unidades']):g} unidades"),
                    ], spacing=1, tight=True, expand=True),
                    ft.Column([
                        estilo.dato(formato.dinero(t["vendido"]), size=13,
                                    color=paleta.MARCA),
                        estilo.apunte(f"gana {formato.dinero(t['ganancia'])}", size=10,
                                      color=paleta.OK),
                    ], spacing=0, tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.END),
                ], spacing=8),
                padding=(12, 8, 12, 8)))

    bloques += [
        ft.Container(height=4),
        estilo.boton("Gastos", lambda e: al_ver_gastos(), ancho=400, alto=46),
        _boton_resumen(page, al_cambiar),
    ]

    return ft.Column([
        _encabezado("Gestión", _rango_legible(m), estado, al_cambiar),
        ft.Container(content=ft.Column(bloques, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


# ==========================================================================
# Gastos
# ==========================================================================

def _gastos(page, estado, al_volver):
    return pantalla.repintable(
        page, lambda repintar: _cuerpo_gastos(page, estado, al_volver, repintar))


def _cuerpo_gastos(page, estado, al_volver, recargar):
    """El contenido de Gastos. `recargar` es el de la pantalla montada: hay que
    usar **ese** y no armar uno propio (ver `frontend/pantalla.py`)."""
    desde, hasta, etiqueta = basedatos.rango(estado["periodo"])
    lista = basedatos.listar_gastos(desde, hasta)
    por_categoria = basedatos.gastos_por_categoria(estado["periodo"])
    total = sum(float(g["total"]) for g in por_categoria)

    bloques = []

    if por_categoria:
        bloques.append(estilo.tarjeta(ft.Column(
            [ft.Row([
                estilo.dato(c["categoria"], size=13),
                ft.Container(expand=True),
                estilo.apunte(f"{c['veces']}×"),
                estilo.dato(formato.dinero(c["total"]), size=13, color=paleta.MARCA),
            ], spacing=8) for c in por_categoria]
            + [ft.Divider(height=10, color=paleta.BEIGE),
               ft.Row([
                   estilo.seccion("Total"),
                   ft.Container(expand=True),
                   estilo.cifra(formato.dinero(total), size=17, color=paleta.TEXTO),
               ])],
            spacing=8, tight=True)))

    bloques.append(estilo.boton(
        "Registrar un gasto", lambda e: _formulario_gasto(page, recargar),
        ancho=400, alto=46))

    if lista:
        bloques.append(estilo.seccion("Uno por uno"))
        for g in lista:
            pagado = (formato.dinero(g["monto_pagado"]) if g["moneda_pagada"] == "USD"
                      else formato.bolivares(g["monto_pagado"]))
            bloques.append(estilo.tarjeta(
                ft.Row([
                    ft.Column([
                        estilo.dato(g["categoria"]),
                        estilo.apunte(f"{g['fecha'][8:10]}/{g['fecha'][5:7]}"
                                      + (f" · {g['descripcion']}"
                                         if g["descripcion"] else "")),
                    ], spacing=1, tight=True, expand=True),
                    ft.Column([
                        estilo.dato(formato.dinero(g["monto_usd"]), size=13),
                        estilo.apunte(pagado if g["moneda_pagada"] == "Bs" else "",
                                      size=10),
                    ], spacing=0, tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.END),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                                  icon_color=paleta.ERROR, icon_size=18,
                                  tooltip="Borrar",
                                  on_click=lambda e, f=g: _borrar_gasto(
                                      page, f, recargar)),
                ], spacing=4),
                padding=(12, 8, 4, 8)))
    else:
        bloques.append(estilo.vacio(
            ft.Icons.RECEIPT_LONG,
            f"Sin gastos en «{etiqueta.lower()}»."))

    bloques.append(estilo.apunte(
        "La compra de mercancía no va aquí: su costo ya se cuenta al vender. "
        "Para eso está «Entrada de mercancía» en el inventario."))

    return ft.Column([
        _encabezado("Gastos", f"Operativos · {etiqueta.lower()}", estado,
                    recargar, al_volver),
        ft.Container(content=ft.Column(bloques, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


def _formulario_gasto(page, al_terminar):
    tasa = basedatos.leer_tasa()
    usadas = basedatos.categorias_de_gasto()

    categoria = ft.TextField(label="Categoría", border_color=paleta.BEIGE,
                             focused_border_color=paleta.MARCA)
    sugerencias = ft.Row(spacing=6, wrap=True)
    descripcion = ft.TextField(label="Descripción (opcional)", dense=True,
                               border_color=paleta.BEIGE,
                               focused_border_color=paleta.MARCA)
    # Sin `expand`, el campo del monto se estira más allá del diálogo y tapa el
    # desplegable de la moneda. Los dos reparten el ancho en proporción 3 a 2.
    monto = ft.TextField(label="Monto", dense=True, expand=3,
                         keyboard_type=ft.KeyboardType.NUMBER,
                         border_color=paleta.BEIGE,
                         focused_border_color=paleta.MARCA)
    moneda = ft.Dropdown(
        label="Moneda", value="USD", dense=True, expand=2,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA,
        options=[ft.DropdownOption(key="USD", text="Dólares"),
                 ft.DropdownOption(key="Bs", text="Bolívares")])
    equivalente = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.TEXTO_SUAVE)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def refrescar(e=None):
        # Lo que se guarda es lo que se pagó **y** su equivalente en dólares a la
        # tasa de hoy. Las métricas leen los dólares; el registro conserva los
        # bolívares que de verdad salieron.
        if moneda.value != "Bs":
            equivalente.value = ""
        elif tasa <= 0:
            equivalente.value = "Falta la tasa del día para convertir"
            equivalente.color = paleta.AVISO
        else:
            equivalente.value = (
                f"{formato.bolivares(formato.numero(monto.value))} = "
                f"{formato.dinero(formato.numero(monto.value) / tasa)} "
                f"a la tasa de hoy")
            equivalente.color = paleta.TEXTO_SUAVE
        page.update()

    monto.on_change = refrescar
    moneda.on_select = refrescar   # en Flet 0.85.3 el evento es on_select

    def poner(texto):
        categoria.value = texto
        page.update()

    # La categoría es texto libre, pero se ofrece lo ya escrito: sin esto, las
    # métricas terminan contando "Delivery", "delivery" y "deliveri" por separado.
    for nombre in usadas[:6]:
        sugerencias.controls.append(ft.Container(
            content=ft.Text(nombre, size=11, weight=estilo.MEDIO,
                            color=paleta.MARCA),
            bgcolor=paleta.BEIGE_CLARO, border_radius=12,
            padding=ft.Padding(10, 4, 10, 4),
            on_click=lambda e, n=nombre: poner(n)))

    def guardar(e):
        try:
            basedatos.crear_gasto(categoria.value, descripcion.value,
                                  formato.numero(monto.value), moneda.value, tasa)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.cerrar(page, dialogo)
        dialogos.exito(page, "Gasto registrado.")
        al_terminar()

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato("Nuevo gasto", size=16),
        content=ft.Column([categoria, sugerencias, descripcion,
                           ft.Row([monto, moneda], spacing=8),
                           equivalente, problema],
                          spacing=10, tight=True, width=320,
                          scroll=ft.ScrollMode.AUTO),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Guardar", guardar),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)


def _borrar_gasto(page, gasto, al_terminar):
    def borrar():
        basedatos.eliminar_gasto(gasto["id"])
        dialogos.exito(page, "Gasto borrado.")
        al_terminar()

    dialogos.confirmar(
        page, "Borrar el gasto",
        f"«{gasto['categoria']}» por {formato.dinero(gasto['monto_usd'])} deja de "
        f"restar en las métricas.",
        "Borrar", borrar, peligro=True)
