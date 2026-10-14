"""Venta: buscar, armar el carrito, repartir el pago y cobrar.

Al contado o a crédito. A crédito no entra dinero: se elige a quién queda debiendo y
para cuándo, y la deuda aparece en Cobros.

Cuatro decisiones que se notan al usarla:

- **El buscador abre el catálogo, no solo filtra.** Al tocarlo la pantalla entra en
  modo búsqueda: el carrito y el cobro se apartan, y aparece la lista de productos
  para recorrerla. Sin escribir nada se ven todos; al escribir se filtra. Es el
  comportamiento de SELL-B, y la razón es que no siempre se recuerda el nombre: a
  veces hace falta mirar qué hay. Agregar **no** cierra la búsqueda, porque lo
  normal es cargar varios seguidos.
- **Se traen 50 como mucho.** El tope es por rendimiento, no por diseño: con
  cientos de productos, dibujarlos todos en cada tecla se arrastra.
- **No se puede vender sin existencia.** El tope se aplica al agregar al carrito y
  se vuelve a comprobar al cobrar, ya dentro de la transacción: entre que se arma
  el carrito y se confirma, el stock pudo haber cambiado.
- **El botón de cobrar no se habilita hasta que el pago cuadre.** Un reparto que no
  cierra no se guarda: es preferible corregir un número en el momento a que el
  historial quede mintiendo.
- **La fecha de pago se elige con botones** (7, 15, 30 días o sin fecha) en vez de un
  calendario. En un teléfono, tocar «15 días» es más rápido y se equivoca menos que
  buscar el día en una cuadrícula.

Nota de Flet 0.85.3: el desplegable avisa por `on_select`, **no** por `on_change`.
Asignar `on_change` no da error y el control simplemente no reacciona.
"""

from datetime import date, timedelta

import flet as ft

from backend import basedatos
from frontend import dialogos
from frontend import estilo
from backend import formato
from frontend import paleta
from frontend.vistas.historial_view import crear_vista_historial

MAX_RESULTADOS = 50
NOMBRE = 'nombre'
SALTO = chr(10)
DOBLE = chr(10) + chr(10)


def crear_vista_ventas(page, funcion_navegar):
    contenedor = ft.Container(expand=True)

    def mostrar_venta():
        contenedor.content = _pantalla_venta(page, funcion_navegar, mostrar_historial)
        page.update()

    def mostrar_historial():
        contenedor.content = crear_vista_historial(page, mostrar_venta)
        page.update()

    contenedor.content = _pantalla_venta(page, funcion_navegar, mostrar_historial)
    return contenedor


# ==========================================================================
# Cobrar
# ==========================================================================

def _pantalla_venta(page, funcion_navegar, al_ver_historial):
    carrito = {}          # producto_id -> {nombre, precio, stock, cantidad}
    pagos = []            # [{"metodo_id": ..., "campo": TextField}]
    credito = {"activo": False, "cliente_id": None, "vence": None}
    tasa = basedatos.leer_tasa()
    metodos = basedatos.listar_metodos()
    por_id = {m["id"]: m for m in metodos}

    modo = {"buscando": False}

    resultados = ft.Column(spacing=6, tight=True, visible=False)
    lineas = ft.Column(spacing=8, tight=True)
    volver_al_carrito = ft.Container(
        visible=False, bgcolor=paleta.LILA_CLARO, border_radius=10,
        padding=ft.Padding(12, 10, 12, 10))
    bloque_cobro = ft.Column(spacing=12, tight=True)
    filas_pago = ft.Column(spacing=8, tight=True)
    total_usd = estilo.cifra(formato.dinero(0), size=30)
    total_bs = estilo.apunte("", size=13)
    contador = estilo.apunte("", size=12)
    estado_pago = ft.Text("", size=12, weight=estilo.MEDIO)
    boton_otro = ft.TextButton(content="Agregar otro método",
                               style=ft.ButtonStyle(color=paleta.MARCA))
    boton_completar = ft.TextButton(
        content="Completar", visible=False, icon=ft.Icons.AUTO_FIX_HIGH,
        style=ft.ButtonStyle(color=paleta.MARCA))
    boton_cobrar = ft.ElevatedButton(
        content="Cobrar", width=400, height=48, disabled=True,
        style=ft.ButtonStyle(bgcolor=paleta.MARCA, color=paleta.FONDO))

    interruptor = ft.Switch(label="Vender a crédito", active_color=paleta.MARCA)
    selector_cliente = ft.Dropdown(
        label="Cliente", dense=True, border_color=paleta.LILA,
        focused_border_color=paleta.MARCA, options=[])
    texto_vence = estilo.apunte("Sin fecha de pago", size=12)
    caja_pago = ft.Column(spacing=10, tight=True)
    caja_credito = ft.Column(spacing=10, tight=True, visible=False)

    buscador = ft.TextField(
        hint_text="Buscar o ver todos los productos", dense=True,
        border_color=paleta.LILA, focused_border_color=paleta.MARCA,
        bgcolor=paleta.TARJETA, border_radius=10,
        prefix_icon=ft.Icons.SEARCH)

    # ------------------------------------------------------------- cálculos

    def total():
        return round(sum(l["precio"] * l["cantidad"] for l in carrito.values()), 2)

    def a_dolares(monto, metodo_id):
        metodo = por_id.get(metodo_id)
        if metodo is None or tasa <= 0:
            return 0.0
        return monto if metodo["moneda"] == "USD" else monto / tasa

    def pagado():
        return sum(a_dolares(formato.numero(p["campo"].value), p["metodo_id"])
                   for p in pagos)

    def listo_para_cobrar():
        if not carrito or tasa <= 0:
            return False
        if credito["activo"]:
            # A crédito no entra dinero: lo único imprescindible es saber a quién
            # cobrarle después.
            return bool(credito["cliente_id"])
        if not pagos:
            return False
        return abs(pagado() - total()) <= 0.01 * max(1, len(pagos))

    # -------------------------------------------------------------- carrito

    def pintar_carrito():
        lineas.controls.clear()
        for producto_id, l in carrito.items():
            lineas.controls.append(_linea_carrito(
                producto_id, l, cambiar_cantidad, quitar))
        if not carrito:
            lineas.controls.append(estilo.vacio(
                ft.Icons.SHOPPING_CART_OUTLINED, "El carrito está vacío",
                "Busca un producto arriba para agregarlo."))
        t = total()
        unidades = sum(l["cantidad"] for l in carrito.values())
        total_usd.value = formato.dinero(t)
        total_bs.value = (formato.bolivares(t * tasa) if tasa > 0
                          else "falta la tasa del día")
        contador.value = (f"{len(carrito)} producto(s) · "
                          f"{formato.cantidad(unidades)} unidad(es)"
                          if carrito else "")
        # Con un solo método, el monto sigue al total: es el caso normal y no tiene
        # sentido obligar a reescribirlo cada vez que cambia el carrito.
        if len(pagos) == 1:
            _poner_monto(pagos[0], t)
        refrescar_pago()
        if modo["buscando"]:
            pintar_modo()

    def agregar(producto):
        producto_id = producto["id"]
        actual = carrito.get(producto_id)
        disponible = float(producto["stock"])
        if actual:
            if actual["cantidad"] + 1 > disponible:
                dialogos.error(page, f"Solo quedan {formato.cantidad(disponible)} de "
                                     f"«{producto[NOMBRE]}».")
                return
            actual["cantidad"] += 1
        else:
            if disponible < 1:
                dialogos.error(page, f"«{producto[NOMBRE]}» no tiene existencia.")
                return
            carrito[producto_id] = {
                "nombre": producto["nombre"],
                "precio": float(producto["precio_usd"]),
                "stock": disponible,
                "cantidad": 1.0,
            }
        # **No se sale de la búsqueda al agregar.** Lo normal es cargar varios
        # productos seguidos; obligar a volver a abrir la lista en cada uno era
        # un toque de más por artículo.
        pintar_resultados()
        pintar_carrito()

    def cambiar_cantidad(producto_id):
        l = carrito[producto_id]
        dialogos.pedir_numero(
            page, l["nombre"], f"Quedan {formato.cantidad(l['stock'])} en existencia.",
            "Cantidad", formato.cantidad(l["cantidad"]),
            lambda v: _fijar_cantidad(page, carrito, producto_id, v, pintar_carrito),
            texto_vivo=lambda v: (formato.dinero(v * l["precio"]) if v > 0 else ""))

    def quitar(producto_id):
        carrito.pop(producto_id, None)
        pintar_carrito()

    # ---------------------------------------------------------------- pagos

    def _poner_monto(pago, monto_usd):
        metodo = por_id.get(pago["metodo_id"])
        if metodo is None:
            return
        monto = monto_usd if metodo["moneda"] == "USD" else monto_usd * tasa
        pago["campo"].value = f"{monto:.2f}" if monto > 0 else ""

    def _campo_monto():
        return ft.TextField(dense=True, width=124, label="Monto",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            border_color=paleta.LILA,
                            focused_border_color=paleta.MARCA,
                            on_change=lambda ev: refrescar_pago())

    def nuevo_pago(e=None):
        if not metodos:
            return
        pago = {"metodo_id": metodos[0]["id"], "campo": _campo_monto()}
        pagos.append(pago)
        # El nuevo se lleva lo que falta: es lo que se quiere el 100 % de las veces.
        _poner_monto(pago, max(0.0, total() - pagado()))
        pintar_pagos()

    def quitar_pago(pago):
        pagos.remove(pago)
        if len(pagos) == 1:
            _poner_monto(pagos[0], total())
        pintar_pagos()

    def elegir_metodo(pago, metodo_id):
        anterior = por_id.get(pago["metodo_id"])
        nuevo = por_id.get(metodo_id)
        pago["metodo_id"] = metodo_id
        # Si cambia la moneda, se convierte lo escrito en vez de perderlo.
        if anterior and nuevo and anterior["moneda"] != nuevo["moneda"]:
            en_dolares = (formato.numero(pago["campo"].value)
                          if anterior["moneda"] == "USD"
                          else formato.numero(pago["campo"].value) / tasa
                          if tasa else 0)
            _poner_monto(pago, en_dolares)
        pintar_pagos()

    def pintar_pagos():
        """Reconstruye las filas. **Solo cuando cambia la estructura**: al agregar
        o quitar un pago, o al cambiar de metodo.

        No puede llamarse al teclear: recrear la fila destruye el campo y el foco
        se pierde, asi que habia que volver a tocarlo despues de cada digito.
        """
        filas_pago.controls.clear()
        for pago in pagos:
            desplegable = ft.Dropdown(
                value=pago["metodo_id"], dense=True, expand=True, text_size=13,
                border_color=paleta.LILA, focused_border_color=paleta.MARCA,
                options=[ft.DropdownOption(key=m["id"], text=m["nombre"])
                         for m in metodos],
                # En Flet 0.85.3 el evento es `on_select`, no `on_change`.
                on_select=lambda ev, p=pago: elegir_metodo(p, ev.control.value),
            )
            # La etiqueta del equivalente se guarda en el propio pago: asi se
            # actualiza en su sitio, sin rehacer la fila.
            pago["equivalente"] = estilo.apunte("", size=10)
            filas_pago.controls.append(ft.Row([
                desplegable,
                ft.Column([pago["campo"], pago["equivalente"]], spacing=0,
                          tight=True),
                ft.IconButton(icon=ft.Icons.CLOSE, icon_color=paleta.ERROR,
                              icon_size=16, tooltip="Quitar este pago",
                              visible=len(pagos) > 1,
                              on_click=lambda ev, p=pago: quitar_pago(p)),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START))
        refrescar_pago()

    def refrescar_pago():
        """Recalcula lo que cambia al teclear: el equivalente de cada linea, lo que
        falta y si se puede cobrar. **No toca la estructura**, asi que el campo
        conserva el foco."""
        for pago in pagos:
            metodo = por_id.get(pago["metodo_id"])
            etiqueta = pago.get("equivalente")
            if etiqueta is None:
                continue
            etiqueta.value = (
                formato.dinero(a_dolares(formato.numero(pago["campo"].value),
                                         pago["metodo_id"]))
                if metodo and metodo["moneda"] == "Bs" else "")

        falta = round(total() - pagado(), 2)
        cuadra = abs(falta) <= 0.01 * max(1, len(pagos))
        if not carrito or credito["activo"]:
            estado_pago.value = ""
        elif cuadra:
            estado_pago.value = "El pago cuadra"
            estado_pago.color = paleta.OK
        elif falta > 0:
            estado_pago.value = f"Faltan {formato.dinero(falta)}"
            estado_pago.color = paleta.AVISO
        else:
            estado_pago.value = f"Se pasa por {formato.dinero(-falta)}"
            estado_pago.color = paleta.ERROR

        # Completar solo aparece cuando hay algo que completar.
        boton_completar.visible = bool(
            carrito and not credito["activo"] and pagos and not cuadra)
        boton_cobrar.disabled = not listo_para_cobrar()
        page.update()

    def completar(e):
        """Pone en el ultimo pago lo que falta, en su moneda.

        Va sobre el ultimo y no sobre el primero porque al repartir se escribe lo
        que se recibio en efectivo y **el resto** va al otro metodo: ese resto es
        justo el que uno no quiere calcular a mano.
        """
        if not pagos:
            return
        falta = round(total() - pagado(), 2)
        ultimo = pagos[-1]
        ya = a_dolares(formato.numero(ultimo["campo"].value), ultimo["metodo_id"])
        _poner_monto(ultimo, max(0.0, round(ya + falta, 2)))
        refrescar_pago()

    boton_otro.on_click = nuevo_pago
    boton_completar.on_click = completar

    # -------------------------------------------------------------- crédito

    def refrescar_clientes():
        clientes = basedatos.listar_clientes()
        selector_cliente.options = [
            ft.DropdownOption(key=c["id"], text=c["nombre"]) for c in clientes]
        if credito["cliente_id"] not in {c["id"] for c in clientes}:
            credito["cliente_id"] = clientes[0]["id"] if clientes else None
        selector_cliente.value = credito["cliente_id"]

    def elegir_cliente(e):
        credito["cliente_id"] = e.control.value
        refrescar_pago()

    selector_cliente.on_select = elegir_cliente

    def poner_vencimiento(dias):
        if dias is None:
            credito["vence"] = None
            texto_vence.value = "Sin fecha de pago"
        else:
            cuando = date.today() + timedelta(days=dias)
            credito["vence"] = cuando.isoformat()
            texto_vence.value = f"Vence el {cuando.strftime('%d/%m/%Y')}"
        refrescar_pago()

    def nuevo_cliente(e):
        def listo():
            refrescar_clientes()
            page.update()
        _formulario_cliente_rapido(page, listo)

    def cambiar_modo(e):
        credito["activo"] = bool(interruptor.value)
        caja_pago.visible = not credito["activo"]
        caja_credito.visible = credito["activo"]
        boton_cobrar.content = ("Registrar a crédito" if credito["activo"]
                                else "Cobrar")
        if credito["activo"]:
            refrescar_clientes()
        refrescar_pago()

    interruptor.on_change = cambiar_modo

    # --------------------------------------------------------------- buscador

    def pintar_resultados():
        """La lista de productos. **Sin texto muestra todos**, para poder
        recorrerla; con texto, los que coinciden. Es el comportamiento de SELL-B:
        el buscador no es solo un filtro, es la puerta al catálogo."""
        texto = (buscador.value or "").strip()
        resultados.controls.clear()
        productos = basedatos.listar_productos(texto, MAX_RESULTADOS)
        for p in productos:
            resultados.controls.append(_fila_resultado(p, agregar))
        if not productos:
            resultados.controls.append(estilo.vacio(
                ft.Icons.SEARCH_OFF,
                f"Nada coincide con «{texto}»." if texto
                else "No hay productos cargados.",
                "Agrégalos desde Inventario." if not texto else None))

    def pintar_modo():
        """En modo búsqueda se aparta el carrito y el cobro: la lista necesita
        toda la pantalla, y en un teléfono no caben las dos cosas."""
        buscando = modo["buscando"]
        resultados.visible = buscando
        volver_al_carrito.visible = buscando
        lineas.visible = not buscando
        bloque_cobro.visible = not buscando
        if buscando:
            unidades = sum(l["cantidad"] for l in carrito.values())
            volver_al_carrito.content = ft.Row([
                ft.Icon(ft.Icons.ARROW_BACK, size=18, color=paleta.MARCA),
                estilo.dato("Volver al carrito", size=13, color=paleta.MARCA),
                ft.Container(expand=True),
                estilo.apunte(
                    f"{formato.cantidad(unidades)} unidad(es) · "
                    f"{formato.dinero(total())}"
                    if carrito else "vacío"),
            ], spacing=6)
        page.update()

    def abrir_busqueda(e=None):
        if not modo["buscando"]:
            modo["buscando"] = True
            pintar_resultados()
            pintar_modo()

    def cerrar_busqueda(e=None):
        modo["buscando"] = False
        buscador.value = ""
        resultados.controls.clear()
        pintar_modo()

    def buscar(e):
        modo["buscando"] = True
        pintar_resultados()
        pintar_modo()

    buscador.on_change = buscar
    buscador.on_focus = abrir_busqueda
    volver_al_carrito.on_click = cerrar_busqueda

    # ----------------------------------------------------------------- cobrar

    def cobrar(e):
        t = total()
        detalle = SALTO.join(
            f"· {formato.cantidad(l['cantidad'])} × {l['nombre']}"
            for l in carrito.values())
        if credito["activo"]:
            cliente = basedatos.obtener_cliente(credito["cliente_id"])
            cuando = (f"Vence el {credito['vence'][8:10]}/{credito['vence'][5:7]}"
                      if credito["vence"] else "Sin fecha de pago")
            dialogos.confirmar(
                page, "Registrar a crédito",
                detalle + DOBLE + f"Total {formato.dinero(t)}" + SALTO
                + formato.bolivares(t * tasa) + DOBLE
                + f"Queda debiendo: {cliente['nombre']}" + SALTO + cuando,
                "Registrar", lambda: _registrar(page, carrito, [], tasa, limpiar,
                                                credito))
            return
        formas = SALTO.join(
            f"· {por_id[p['metodo_id']]['nombre']}: "
            + (formato.dinero(formato.numero(p["campo"].value))
               if por_id[p["metodo_id"]]["moneda"] == "USD"
               else formato.bolivares(formato.numero(p["campo"].value)))
            for p in pagos)
        dialogos.confirmar(
            page, "Confirmar la venta",
            detalle + DOBLE + f"Total {formato.dinero(t)}" + SALTO
            + formato.bolivares(t * tasa) + DOBLE + formas,
            "Cobrar", lambda: _registrar(page, carrito, pagos, tasa, limpiar,
                                         credito))

    def limpiar():
        carrito.clear()
        pagos.clear()
        modo["buscando"] = False
        buscador.value = ""
        resultados.controls.clear()
        interruptor.value = False
        credito["activo"] = False
        credito["vence"] = None
        texto_vence.value = "Sin fecha de pago"
        caja_pago.visible = True
        caja_credito.visible = False
        boton_cobrar.content = "Cobrar"
        nuevo_pago()
        pintar_carrito()

    boton_cobrar.on_click = cobrar

    # ----------------------------------------------------------------- armado

    caja_pago.controls = [
        estilo.seccion("Cómo paga"),
        filas_pago,
        ft.Row([boton_otro, ft.Container(expand=True),
                boton_completar, estado_pago],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
    ]

    caja_credito.controls = [
        estilo.seccion("Queda debiendo"),
        ft.Row([
            selector_cliente,
            ft.IconButton(icon=ft.Icons.PERSON_ADD, icon_color=paleta.MARCA,
                          tooltip="Cliente nuevo", on_click=nuevo_cliente),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        estilo.seccion("¿Cuándo paga?"),
        ft.Row([
            ft.TextButton(content="7 días", on_click=lambda e: poner_vencimiento(7),
                          style=ft.ButtonStyle(color=paleta.MARCA)),
            ft.TextButton(content="15 días", on_click=lambda e: poner_vencimiento(15),
                          style=ft.ButtonStyle(color=paleta.MARCA)),
            ft.TextButton(content="30 días", on_click=lambda e: poner_vencimiento(30),
                          style=ft.ButtonStyle(color=paleta.MARCA)),
            ft.TextButton(content="Sin fecha",
                          on_click=lambda e: poner_vencimiento(None),
                          style=ft.ButtonStyle(color=paleta.TEXTO_SUAVE)),
        ], spacing=2, wrap=True),
        texto_vence,
    ]

    hoy = basedatos.resumen_de_hoy()
    encabezado = estilo.encabezado(
        "Venta",
        f"Hoy: {hoy['ventas']} venta(s) · {formato.dinero(hoy['ingreso'])}",
        acciones=[ft.TextButton(
            content="Historial", on_click=lambda e: al_ver_historial(),
            icon=ft.Icons.HISTORY,
            style=ft.ButtonStyle(color=paleta.MARCA))])

    cuerpo = [buscador, volver_al_carrito, resultados]

    if tasa <= 0:
        # Sin tasa no se puede decir cuánto es en bolívares, y cada venta guarda la
        # suya. Se avisa con la salida a mano en vez de dejar el botón muerto.
        cuerpo.append(estilo.tarjeta(
            ft.Row([
                ft.Column([
                    estilo.dato("Falta la tasa del día", size=13,
                                color=paleta.AVISO),
                    estilo.apunte("Sin ella no se puede cobrar en bolívares."),
                ], spacing=2, tight=True, expand=True),
                ft.TextButton(content="Cargarla",
                              on_click=lambda e: funcion_navegar("inicio"),
                              style=ft.ButtonStyle(color=paleta.MARCA)),
            ]),
            padding=(12, 10, 8, 10), color_borde=paleta.AVISO))

    bloque_cobro.controls = [
        estilo.tarjeta(ft.Column([
            ft.Row([
                ft.Column([
                    estilo.seccion("Total"),
                    total_usd,
                    total_bs,
                ], spacing=0, tight=True, expand=True),
                contador,
            ], vertical_alignment=ft.CrossAxisAlignment.END),
            ft.Divider(height=14, color=paleta.LILA),
            interruptor,
            caja_pago,
            caja_credito,
        ], spacing=10, tight=True)),
        boton_cobrar,
    ]
    cuerpo += [lineas, bloque_cobro]

    vista = ft.Column([
        encabezado,
        ft.Container(content=ft.Column(cuerpo, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)

    if metodos:
        pagos.append({"metodo_id": metodos[0]["id"], "campo": _campo_monto()})
    pintar_pagos()          # arma las filas una vez; despues solo se refrescan
    pintar_carrito()
    return vista


def _fila_resultado(producto, al_agregar):
    sin_stock = float(producto["stock"]) <= 0
    disponible = ("sin existencia" if sin_stock
                  else f"{formato.cantidad(producto['stock'])} disponibles")
    return estilo.tarjeta(
        ft.Row([
            ft.Column([
                estilo.dato(producto["nombre"], lineas=1),
                estilo.apunte(f"{formato.dinero(producto['precio_usd'])} · "
                              f"{disponible}",
                              color=paleta.ERROR if sin_stock else None),
            ], spacing=1, tight=True, expand=True),
            ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE,
                    color=paleta.LILA if sin_stock else paleta.MARCA, size=22),
        ], spacing=8),
        padding=(12, 8, 12, 8),
        al_tocar=None if sin_stock else (lambda e: al_agregar(producto)))


def _linea_carrito(producto_id, linea, al_cambiar, al_quitar):
    return estilo.tarjeta(
        ft.Row([
            ft.Column([
                estilo.dato(linea["nombre"], lineas=1),
                estilo.apunte(f"{formato.cantidad(linea['cantidad'])} × "
                              f"{formato.dinero(linea['precio'])}"),
            ], spacing=1, tight=True, expand=True),
            estilo.dato(formato.dinero(linea["cantidad"] * linea["precio"]),
                        color=paleta.MARCA),
            ft.IconButton(icon=ft.Icons.EDIT, icon_color=paleta.MARCA_CLARA,
                          icon_size=18, tooltip="Cambiar la cantidad",
                          on_click=lambda e: al_cambiar(producto_id)),
            ft.IconButton(icon=ft.Icons.CLOSE, icon_color=paleta.ERROR,
                          icon_size=18, tooltip="Quitar",
                          on_click=lambda e: al_quitar(producto_id)),
        ], spacing=4),
        padding=(12, 6, 4, 6))


def _formulario_cliente_rapido(page, al_terminar):
    """Alta de cliente sin salir de la venta. Solo el nombre y el teléfono: el
    resto se completa después, en Cobros."""
    nombre = ft.TextField(label="Nombre", border_color=paleta.LILA,
                          focused_border_color=paleta.MARCA)
    telefono = ft.TextField(label="Teléfono (opcional)", dense=True,
                            keyboard_type=ft.KeyboardType.PHONE,
                            border_color=paleta.LILA,
                            focused_border_color=paleta.MARCA)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def guardar(e):
        try:
            basedatos.crear_cliente(nombre.value, telefono.value)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.cerrar(page, dialogo)
        al_terminar()

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato("Cliente nuevo", size=16),
        content=ft.Column([nombre, telefono, problema], spacing=12, tight=True,
                          width=300),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Guardar", guardar),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)


def _fijar_cantidad(page, carrito, producto_id, valor, repintar):
    linea = carrito.get(producto_id)
    if linea is None:
        return
    if valor <= 0:
        carrito.pop(producto_id, None)
        repintar()
        return
    if valor > linea["stock"]:
        dialogos.error(page, f"Solo quedan {formato.cantidad(linea['stock'])} de "
                             f"«{linea['nombre']}».")
        return
    linea["cantidad"] = valor
    repintar()


def _registrar(page, carrito, pagos, tasa, al_terminar, credito):
    items = [{"producto_id": pid, "cantidad": l["cantidad"]}
             for pid, l in carrito.items()]
    reparto = [{"metodo_id": p["metodo_id"], "monto": formato.numero(p["campo"].value)}
               for p in pagos]
    try:
        if credito["activo"]:
            venta = basedatos.registrar_venta(
                items, tasa, tipo="credito", cliente_id=credito["cliente_id"],
                fecha_pago_prevista=credito["vence"])
        else:
            venta = basedatos.registrar_venta(items, tasa, pagos=reparto)
    except (basedatos.SinExistencia, basedatos.PagoNoCuadra, ValueError) as ex:
        # El stock o el reparto cambiaron entre armar la venta y confirmar. Se dice
        # exactamente qué pasó, no un "no se pudo".
        dialogos.error(page, str(ex))
        return
    dialogos.exito(page, f"Venta N° {venta['correlativo']} registrada · "
                         f"{formato.dinero(venta['total_usd'])}")
    al_terminar()
