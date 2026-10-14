"""Inventario: la lista de productos y la ficha de cada uno.

La ficha no es un dialogo sino una sub-vista que se muestra en el mismo lugar, con
flecha para volver. Es el patron que en SELL-B se uso para Reportes y Configuracion,
y en un telefono se lee mucho mejor que un formulario largo metido en una ventanita
— ademas de esquivar el apilado de dialogos que dio problemas alli.

La lista trae **40 productos por tanda** con un boton "Ver mas". Nadie recorre mil
productos con el dedo: se busca. El filtro se hace en SQL, que para eso esta el
indice.
"""

import flet as ft

from backend import basedatos
from frontend import dialogos
from frontend import estilo
from backend import fotos
from backend import formato
from frontend import paleta
from frontend import pantalla
from frontend import selector

POR_TANDA = 40


def crear_vista_inventario(page):
    contenedor = ft.Container(expand=True)

    def mostrar_lista():
        contenedor.content = _lista(page, mostrar_ficha)
        page.update()

    def mostrar_ficha(producto_id):
        contenedor.content = _ficha(page, producto_id, mostrar_lista)
        page.update()

    contenedor.content = _lista(page, mostrar_ficha)
    return contenedor


# ==========================================================================
# Lista
# ==========================================================================

def _lista(page, al_abrir):
    estado = {"busqueda": "", "tope": POR_TANDA}

    filas = ft.Column(spacing=8, tight=True)
    resumen = estilo.apunte("", size=12)
    ver_mas = ft.TextButton(content="", visible=False)

    buscador = ft.TextField(
        hint_text="Buscar producto",
        dense=True,
        border_color=paleta.LILA,
        focused_border_color=paleta.MARCA,
        bgcolor=paleta.TARJETA, border_radius=10,
        prefix_icon=ft.Icons.SEARCH,
    )

    def tarjeta(fila):
        margen = float(fila["precio_usd"]) - float(fila["costo_usd"])
        sin_stock = float(fila["stock"]) <= 0

        if fila["miniatura"]:
            imagen = ft.Image(src=fila["miniatura"], width=56, height=56,
                              fit=ft.BoxFit.COVER, border_radius=8)
        else:
            imagen = ft.Container(width=56, height=56, bgcolor=paleta.LILA,
                                  border_radius=8,
                                  content=ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED,
                                                  color=paleta.MARCA_CLARA, size=22),
                                  alignment=ft.Alignment.CENTER)

        return estilo.tarjeta(
            ft.Row([
                imagen,
                ft.Column([
                    estilo.dato(fila["nombre"], size=15, lineas=1),
                    ft.Row([
                        estilo.dato(formato.dinero(fila["precio_usd"]), size=13,
                                    color=paleta.MARCA),
                        estilo.apunte(f"margen {formato.dinero(margen)}", size=12,
                                      color=paleta.ERROR if margen < 0 else None),
                    ], spacing=10),
                ], spacing=2, tight=True, expand=True),
                ft.Container(
                    content=ft.Text(
                        "sin stock" if sin_stock else formato.cantidad(fila["stock"]),
                        size=12, weight=estilo.MEDIO,
                        color=paleta.ERROR if sin_stock else paleta.TEXTO),
                    bgcolor=paleta.LILA_CLARO, border_radius=8,
                    padding=ft.Padding(9, 4, 9, 4)),
            ], spacing=12),
            padding=(10, 10, 10, 10),
            al_tocar=lambda e, pid=fila["id"]: al_abrir(pid))

    def repintar():
        # La lista, el total y el resumen de abajo: un solo viaje a Supabase.
        basedatos.precargar_inventario(estado["busqueda"], estado["tope"])
        productos = basedatos.listar_productos(estado["busqueda"], estado["tope"])
        total = basedatos.contar_productos(estado["busqueda"])

        filas.controls.clear()
        filas.controls.extend(tarjeta(f) for f in productos)

        if not productos:
            filas.controls.append(estilo.vacio(
                ft.Icons.INVENTORY_2_OUTLINED,
                "No hay productos todavía."
                if not estado["busqueda"]
                else f"Nada coincide con «{estado['busqueda']}».",
                "Toca + para agregar el primero."
                if not estado["busqueda"] else None))

        faltan = total - len(productos)
        ver_mas.visible = faltan > 0
        ver_mas.content = f"Ver mas ({faltan} sin mostrar)"

        r = basedatos.resumen_inventario()
        partes = [f"{r['productos']} productos",
                  f"valor a costo {formato.dinero(r['valor_costo'])}"]
        # Se avisan las dos cosas que hacen mentir a las metricas: sin costo, el
        # margen sale inflado; por debajo del costo, se pierde dinero en cada venta.
        if r["sin_costo"]:
            partes.append(f"{r['sin_costo']} sin costo cargado")
        if r["bajo_costo"]:
            partes.append(f"{r['bajo_costo']} por debajo del costo")
        resumen.value = " · ".join(partes)
        page.update()

    def buscar(e):
        estado["busqueda"] = buscador.value or ""
        estado["tope"] = POR_TANDA
        repintar()

    def mas(e):
        estado["tope"] += POR_TANDA
        repintar()

    buscador.on_change = buscar
    ver_mas.on_click = mas

    def nuevo(e):
        _formulario_producto(page, None, repintar)

    encabezado = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Column([
                    estilo.titulo("Inventario", size=20),
                    resumen,
                ], spacing=1, tight=True, expand=True),
                ft.IconButton(icon=ft.Icons.ADD, icon_color=paleta.FONDO,
                              bgcolor=paleta.MARCA, on_click=nuevo,
                              tooltip="Agregar producto"),
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            buscador,
        ], spacing=12, tight=True),
        bgcolor=paleta.LILA_CLARO,
        padding=ft.Padding(16, 14, 12, 14),
    )

    repintar()

    return ft.Column([
        encabezado,
        ft.Container(
            content=ft.Column([filas, ver_mas], spacing=10, tight=True,
                              scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)


# ==========================================================================
# Ficha
# ==========================================================================

def _ficha(page, producto_id, al_volver):
    return pantalla.repintable(
        page, lambda repintar: _cuerpo_ficha(page, producto_id, al_volver,
                                             repintar))


def _cuerpo_ficha(page, producto_id, al_volver, recargar):
    """El contenido de la ficha. `recargar` es el de la pantalla montada: hay que
    usar **ese** y no armar uno propio (ver `frontend/pantalla.py`)."""
    producto = basedatos.obtener_producto(producto_id)
    if producto is None:
        al_volver()
        return ft.Container()

    galeria = ft.Row(spacing=8, wrap=True)

    def pintar_galeria():
        galeria.controls.clear()
        lista = basedatos.listar_fotos(producto_id)
        for f in lista:
            galeria.controls.append(_miniatura(page, f, refrescar_fotos))
        if len(lista) < fotos.MAXIMO_POR_PRODUCTO:
            galeria.controls.append(
                _boton_agregar_foto(page, producto_id, refrescar_fotos))

    def refrescar_fotos():
        """Repinta **solo la tira de fotos**, sobre la fila que ya esta en pantalla.

        Cambiar el contenido de un contenedor por otro nuevo no llegaba a verse: la
        foto recien agregada no aparecia hasta salir del producto y volver a entrar.
        Tocar los hijos de un control ya montado —lo mismo que hacen el carrito y la
        busqueda de Venta— si se repinta.
        """
        pintar_galeria()
        page.update()

    pintar_galeria()

    stock = float(producto["stock"])
    costo = float(producto["costo_usd"])
    precio = float(producto["precio_usd"])
    margen = precio - costo

    def entrada(e):
        dialogos.pedir_numero(
            page, "Entrada de mercancía",
            "Cuántas unidades entraron. Se suma al stock actual.",
            "Cantidad", 0,
            lambda v: _reabastecer(page, producto_id, v, recargar),
            texto_vivo=lambda v: f"Nuevo total: {formato.cantidad(stock + v)}")

    def ajustar(e):
        dialogos.pedir_numero(
            page, "Ajustar stock",
            "El total que contaste. Se guarda la diferencia, no el total.",
            "Total contado", formato.cantidad(stock),
            lambda v: _ajustar(page, producto_id, v, recargar),
            texto_vivo=lambda v: (f"Diferencia: {'+' if v - stock >= 0 else ''}"
                                  f"{formato.cantidad(v - stock)}"))

    def borrar(e):
        dialogos.confirmar(
            page, "Borrar producto",
            f"«{producto['nombre']}» deja de aparecer en el inventario y en la "
            "venta. Las ventas que ya se hicieron con él no se tocan.",
            "Borrar", lambda: _borrar(page, producto_id, al_volver), peligro=True)

    return ft.Column([
        estilo.encabezado(
            producto["nombre"],
            f"{formato.dinero(precio)} · {formato.cantidad(stock)} en existencia",
            al_volver=al_volver,
            acciones=[ft.IconButton(icon=ft.Icons.EDIT, icon_color=paleta.MARCA,
                                    tooltip="Editar datos",
                                    on_click=lambda e: _formulario_producto(
                                        page, producto_id, recargar))]),

        ft.Container(content=ft.Column([
            estilo.seccion("Fotos"),
            galeria,

            estilo.tarjeta(ft.Column([
                _bloque("Precio de venta", formato.dinero(precio)),
                _bloque("Costo de compra",
                        formato.dinero(costo) if costo > 0 else "sin cargar",
                        color=paleta.AVISO if costo <= 0 else None),
                ft.Divider(height=10, color=paleta.LILA),
                _bloque("Margen", formato.dinero(margen),
                        color=paleta.ERROR if margen < 0 else paleta.OK,
                        tamano=16),
            ], spacing=8, tight=True)),

            estilo.tarjeta(ft.Column([
                _bloque("En existencia", formato.cantidad(stock),
                        color=paleta.ERROR if stock <= 0 else None, tamano=16),
                ft.Row([
                    estilo.boton("Entrada de mercancía", entrada, expand=True),
                    estilo.boton("Ajustar stock", ajustar, principal=False,
                                 expand=True),
                ], spacing=8),
                estilo.apunte("Una entrada de mercancía no es un gasto: su costo "
                              "ya se cuenta al vender."),
            ], spacing=10, tight=True)),

            _movimientos(producto_id),

            ft.Container(height=10),
            ft.TextButton(content="Borrar producto", on_click=borrar,
                          style=ft.ButtonStyle(color=paleta.ERROR)),
        ], spacing=12, tight=True, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 14, 14, 24), expand=True),
    ], spacing=0, expand=True)


def _bloque(etiqueta, valor, color=None, tamano=15):
    return ft.Row([
        estilo.seccion(etiqueta),
        ft.Container(expand=True),
        ft.Text(valor, size=tamano, weight=estilo.FUERTE,
                color=color or paleta.TEXTO),
    ])


def _movimientos(producto_id):
    filas = basedatos.movimientos(producto_id, limite=15)
    if not filas:
        return ft.Container()
    NOMBRES = {"alta": "Registro inicial", "compra": "Entrada",
               "ajuste": "Ajuste", "venta": "Venta"}
    controles = [estilo.seccion("Últimos movimientos")]
    for m in filas:
        delta = float(m["delta"])
        controles.append(ft.Row([
            estilo.dato(NOMBRES.get(m["motivo"], m["motivo"]), size=12),
            ft.Container(expand=True),
            estilo.apunte(m["fecha"][:10]),
            estilo.dato(f"{'+' if delta >= 0 else ''}"
                        f"{formato.cantidad(delta)}", size=12,
                        color=paleta.OK if delta >= 0 else paleta.ERROR),
        ], spacing=8))
    return estilo.tarjeta(ft.Column(controles, spacing=8, tight=True))


# ==========================================================================
# Fotos
# ==========================================================================

def _miniatura(page, fila, recargar):
    def opciones(e):
        def hacer_principal():
            basedatos.hacer_principal(fila["id"])
            recargar()

        def eliminar():
            basedatos.eliminar_foto(fila["id"])
            recargar()

        dialogos.confirmar(
            page,
            "Foto principal" if fila["orden"] != 1 else "Borrar foto",
            ("Esta foto pasa a ser la principal: la que se ve en la lista y en la "
             "venta." if fila["orden"] != 1 else
             "La foto se borra del teléfono y no se puede recuperar."),
            "Hacerla principal" if fila["orden"] != 1 else "Borrar",
            hacer_principal if fila["orden"] != 1 else eliminar,
            peligro=fila["orden"] == 1)

    marco = ft.Container(
        content=ft.Image(src=fila["miniatura"], width=76, height=76,
                         fit=ft.BoxFit.COVER, border_radius=8),
        on_click=opciones,
    )
    if fila["orden"] == 1:
        return ft.Column([
            marco,
            ft.Text("principal", size=10, weight=estilo.MEDIO,
                    color=paleta.MARCA),
        ], spacing=2, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Column([marco, ft.Text(" ", size=10)], spacing=2, tight=True)


def _boton_agregar_foto(page, producto_id, recargar):
    def guardar(archivos):
        try:
            basedatos.guardar_foto(producto_id, fotos.preparar(archivos[0].bytes))
        except ValueError as ex:
            dialogos.error(page, str(ex))
            return
        except Exception as ex:
            dialogos.error(page, f"Esa imagen no se pudo procesar: {ex}")
            return
        recargar()

    # Como abrir la galeria depende de la version de Flet: en el iPhone tiene
    # que hacerlo la pantalla misma, dentro del toque (ver `selector`).
    return ft.Container(
        content=ft.Icon(ft.Icons.ADD_A_PHOTO, color=paleta.MARCA, size=24),
        width=76, height=76, bgcolor=paleta.LILA_CLARO, border_radius=8,
        alignment=ft.Alignment.CENTER,
        **selector.elegir_imagen(
            page, guardar, "Elige una foto del producto",
            al_fallar=lambda ex: dialogos.error(
                page, f"No se pudo abrir la galería: {ex}")),
    )


# ==========================================================================
# Formulario de alta y edicion
# ==========================================================================

def _formulario_producto(page, producto_id, al_terminar):
    existente = basedatos.obtener_producto(producto_id) if producto_id else None

    nombre = ft.TextField(label="Nombre", value=existente["nombre"] if existente else "",
                          border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    descripcion = ft.TextField(
        label="Descripción",
        value=existente["descripcion"] if existente else "",
        border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    costo = ft.TextField(label="Costo de compra ($)",
                         value=f"{float(existente['costo_usd']):g}" if existente else "",
                         keyboard_type=ft.KeyboardType.NUMBER,
                         border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    precio = ft.TextField(label="Precio de venta ($)",
                          value=f"{float(existente['precio_usd']):g}" if existente else "",
                          keyboard_type=ft.KeyboardType.NUMBER,
                          border_color=paleta.LILA, focused_border_color=paleta.MARCA)
    stock_inicial = ft.TextField(label="Existencia inicial", value="0",
                                 keyboard_type=ft.KeyboardType.NUMBER,
                                 border_color=paleta.LILA,
                                 focused_border_color=paleta.MARCA)
    margen_vivo = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.TEXTO_SUAVE)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def numero(campo):
        return float((campo.value or "0").replace(",", ".").strip() or 0)

    def recalcular(e):
        # El margen se ve **antes** de guardar. En SELL-B, vender por debajo del
        # costo paso inadvertido justamente por no mostrarlo a tiempo.
        try:
            m = numero(precio) - numero(costo)
        except ValueError:
            margen_vivo.value = ""
            page.update()
            return
        margen_vivo.value = f"Margen: {formato.dinero(m)}"
        margen_vivo.color = paleta.ERROR if m < 0 else paleta.OK
        page.update()

    costo.on_change = recalcular
    precio.on_change = recalcular
    recalcular(None)

    def guardar(e):
        problema.value = ""
        if not (nombre.value or "").strip():
            problema.value = "El nombre no puede quedar vacío."
            page.update()
            return
        try:
            c, p = numero(costo), numero(precio)
            s = numero(stock_inicial) if existente is None else 0
        except ValueError:
            problema.value = "El costo, el precio y la existencia deben ser números."
            page.update()
            return
        if c < 0 or p < 0 or s < 0:
            problema.value = "No puede haber números negativos."
            page.update()
            return

        if existente is None:
            basedatos.crear_producto(nombre.value, descripcion.value, c, p, s)
        else:
            basedatos.actualizar_producto(producto_id, nombre.value,
                                          descripcion.value, c, p)
        dialogos.cerrar(page, dialogo)
        dialogos.exito(page, "Producto guardado.")
        al_terminar()

    campos = [nombre, descripcion, costo, precio]
    if existente is None:
        campos.append(stock_inicial)
    campos += [margen_vivo, problema]

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato("Nuevo producto" if existente is None
                          else "Editar producto", size=16),
        content=ft.Column(campos, spacing=12, tight=True, width=320,
                          scroll=ft.ScrollMode.AUTO),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Guardar", guardar),
        ],
        bgcolor=paleta.TARJETA,
    )
    dialogos.abrir(page, dialogo)


# ==========================================================================

def _reabastecer(page, producto_id, cantidad, recargar):
    try:
        basedatos.reabastecer(producto_id, cantidad)
    except ValueError as ex:
        dialogos.error(page, str(ex))
        return
    dialogos.exito(page, f"Entraron {formato.cantidad(cantidad)} unidades.")
    recargar()


def _ajustar(page, producto_id, total, recargar):
    if total < 0:
        dialogos.error(page, "El stock no puede quedar negativo.")
        return
    delta = basedatos.ajustar_stock(producto_id, total)
    if delta == 0:
        dialogos.aviso(page, "El conteo coincide: no se cambió nada.")
    else:
        dialogos.exito(page, f"Ajustado en {'+' if delta > 0 else ''}"
                             f"{formato.cantidad(delta)}.")
    recargar()


def _borrar(page, producto_id, al_volver):
    basedatos.eliminar_producto(producto_id)
    dialogos.exito(page, "Producto borrado.")
    al_volver()
