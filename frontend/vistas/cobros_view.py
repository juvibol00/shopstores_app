"""Cobros: quién debe, cuánto, y desde cuándo.

La lista se ordena **por vencimiento**: primero lo vencido, después lo que vence
pronto, y al final lo que no tiene fecha puesta. Es el orden en que hay que llamar
a la gente.

**El abono se registra contra el cliente, no contra una factura.** El cliente paga y
el sistema reparte, saldando la más vieja primero. Pero queda escrito a qué factura
fue cada pedazo, que es lo que permite decirle «te quedó saldada la del 3 de marzo»
en vez de solo mostrarle un saldo que bajó.
"""

from datetime import date

import flet as ft

from backend import basedatos
from frontend import dialogos
from frontend import estilo
from backend import formato
from frontend import paleta


def _texto_vencimiento(iso):
    """Cómo se dice una fecha de vencimiento, y de qué color."""
    if not iso:
        return "sin fecha de pago", paleta.TEXTO_SUAVE
    dias = (date.fromisoformat(iso) - date.today()).days
    if dias < 0:
        cuantos = -dias
        return (f"venció hace {cuantos} día{'s' if cuantos != 1 else ''}",
                paleta.ERROR)
    if dias == 0:
        return "vence hoy", paleta.AVISO
    if dias == 1:
        return "vence mañana", paleta.AVISO
    if dias <= 7:
        return f"vence en {dias} días", paleta.AVISO
    return f"vence el {iso[8:10]}/{iso[5:7]}", paleta.TEXTO_SUAVE


def crear_vista_cobros(page):
    contenedor = ft.Container(expand=True)

    def deudores():
        contenedor.content = _lista_deudores(page, ficha, todos_los_clientes)
        page.update()

    def ficha(cliente_id):
        contenedor.content = _ficha_cliente(page, cliente_id, deudores)
        page.update()

    def todos_los_clientes():
        contenedor.content = _lista_clientes(page, deudores, ficha)
        page.update()

    contenedor.content = _lista_deudores(page, ficha, todos_los_clientes)
    return contenedor


# ==========================================================================
# Quién debe
# ==========================================================================

def _lista_deudores(page, al_abrir, al_ver_clientes):
    deudores = basedatos.clientes_con_saldo()
    total = sum(float(d["saldo"]) for d in deudores)

    filas = []
    for d in deudores:
        texto, color = _texto_vencimiento(d["vence"])
        filas.append(estilo.tarjeta(
            ft.Row([
                ft.Column([
                    estilo.dato(d["nombre"], size=15, lineas=1),
                    estilo.apunte(f"{texto} · {d['facturas']} factura"
                                  f"{'s' if d['facturas'] != 1 else ''}",
                                  color=color),
                ], spacing=2, tight=True, expand=True),
                estilo.cifra(formato.dinero(d["saldo"]), size=17),
            ], spacing=8),
            padding=(12, 10, 12, 10), color_borde=color,
            al_tocar=lambda e, cid=d["id"]: al_abrir(cid)))

    if not filas:
        filas = [estilo.vacio(ft.Icons.SENTIMENT_SATISFIED,
                              "Nadie debe nada.",
                              "Las ventas a crédito aparecen aquí.")]

    return ft.Column([
        estilo.encabezado(
            "Cobros", f"Por cobrar: {formato.dinero(total)}",
            acciones=[ft.TextButton(
                content="Clientes", on_click=lambda e: al_ver_clientes(),
                icon=ft.Icons.PEOPLE_OUTLINE,
                style=ft.ButtonStyle(color=paleta.MARCA))]),
        ft.Container(
            content=ft.Column(filas, spacing=8, tight=True,
                              scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 12, 14, 20), expand=True),
    ], spacing=0, expand=True)


# ==========================================================================
# La ficha del cliente: sus facturas agrupadas
# ==========================================================================

def _ficha_cliente(page, cliente_id, al_volver):
    contenedor = ft.Container(expand=True)

    def recargar():
        contenedor.content = _ficha_cliente(page, cliente_id, al_volver).content
        page.update()

    cliente = basedatos.obtener_cliente(cliente_id)
    if cliente is None:
        al_volver()
        return ft.Container()

    facturas = basedatos.facturas_pendientes(cliente_id)
    saldo = basedatos.saldo_cliente(cliente_id)
    abonos = basedatos.abonos_de_cliente(cliente_id, limite=10)

    bloques = []

    if facturas:
        bloques.append(estilo.seccion("Facturas pendientes"))
        for f in facturas:
            texto, color = _texto_vencimiento(f["fecha_pago_prevista"])
            abonado = float(f["abonado"])
            detalle = f"{f['fecha'][8:10]}/{f['fecha'][5:7]} · {texto}"
            if abonado > 0:
                detalle += f" · abonado {formato.dinero(abonado)}"
            bloques.append(estilo.tarjeta(
                ft.Row([
                    ft.Column([
                        estilo.dato(f"N° {f['correlativo']}"),
                        estilo.apunte(detalle, color=color),
                    ], spacing=1, tight=True, expand=True),
                    ft.Column([
                        estilo.dato(formato.dinero(f["restante"]), color=paleta.MARCA),
                        estilo.apunte(f"de {formato.dinero(f['total_usd'])}", size=10),
                    ], spacing=0, tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.END),
                ], spacing=8),
                padding=(12, 8, 12, 8)))
    else:
        bloques.append(estilo.vacio(ft.Icons.CHECK_CIRCLE_OUTLINE,
                                    "No debe nada."))

    if abonos:
        bloques.append(ft.Divider(height=16, color=paleta.BEIGE))
        bloques.append(estilo.seccion("Abonos recibidos"))
        for a in abonos:
            recibido = (formato.dinero(a["monto_recibido"])
                        if a["moneda_recibida"] == "USD"
                        else formato.bolivares(a["monto_recibido"]))
            metodo = a["metodo_nombre"] or "sin método"
            bloques.append(ft.Row([
                ft.Column([
                    estilo.dato(f"{a['fecha'][8:10]}/{a['fecha'][5:7]} · {metodo}",
                                size=12),
                    estilo.apunte(recibido, size=10),
                ], spacing=0, tight=True, expand=True),
                estilo.dato(formato.dinero(a["monto_usd"]), size=13, color=paleta.OK),
            ], spacing=8))

    contenedor.content = ft.Column([
        estilo.encabezado(
            cliente["nombre"], cliente["telefono"] or "sin teléfono",
            al_volver=al_volver,
            acciones=[ft.IconButton(icon=ft.Icons.EDIT, icon_color=paleta.MARCA,
                                    tooltip="Editar el cliente",
                                    on_click=lambda e: _formulario_cliente(
                                        page, cliente, recargar))],
            extra=ft.Row([
                estilo.seccion("Debe"),
                ft.Container(expand=True),
                estilo.cifra(formato.dinero(saldo), size=24,
                             color=paleta.MARCA if saldo > 0 else paleta.OK),
            ], vertical_alignment=ft.CrossAxisAlignment.END)),
        ft.Container(content=ft.Column(bloques + ([
            ft.Container(height=6),
            estilo.boton("Registrar un abono",
                         lambda e: _dialogo_abono(page, cliente, saldo, recargar),
                         ancho=400, alto=46),
        ] if saldo > 0 else []), spacing=8, tight=True,
            scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding(14, 12, 14, 20), expand=True),
    ], spacing=0, expand=True)

    return contenedor


# ==========================================================================
# El abono
# ==========================================================================

def _dialogo_abono(page, cliente, saldo, al_terminar):
    metodos = basedatos.listar_metodos()
    tasa = basedatos.leer_tasa()
    if not metodos:
        dialogos.error(page, "No hay métodos de pago configurados.")
        return

    estado = {"metodo": metodos[0]}
    monto = ft.TextField(label="Monto recibido", dense=True,
                         keyboard_type=ft.KeyboardType.NUMBER,
                         border_color=paleta.BEIGE,
                         focused_border_color=paleta.MARCA)
    equivalente = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.TEXTO_SUAVE)
    reparto = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.TEXTO_SUAVE)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def en_dolares():
        v = formato.numero(monto.value)
        if estado["metodo"]["moneda"] == "USD":
            return v
        return v / tasa if tasa > 0 else 0.0

    def refrescar(e=None):
        problema.value = ""
        usd = en_dolares()
        if estado["metodo"]["moneda"] == "Bs":
            equivalente.value = f"Equivale a {formato.dinero(usd)}"
        else:
            equivalente.value = ""
        # Se muestra **antes de guardar** qué facturas va a saldar. Ver el efecto
        # es lo que evita el abono mal escrito.
        if usd <= 0:
            reparto.value = ""
        elif usd - saldo > 0.01:
            reparto.value = f"Se pasa: debe {formato.dinero(saldo)}."
        else:
            restante = usd
            saldadas, parcial = [], None
            for f in basedatos.facturas_pendientes(cliente["id"]):
                if restante <= 0.005:
                    break
                trozo = min(restante, float(f["restante"]))
                if trozo >= float(f["restante"]) - 0.005:
                    saldadas.append(str(f["correlativo"]))
                else:
                    parcial = f["correlativo"]
                restante -= trozo
            partes = []
            if saldadas:
                partes.append("salda la" + ("s" if len(saldadas) > 1 else "")
                              + " N° " + ", ".join(saldadas))
            if parcial:
                partes.append(f"abona a la N° {parcial}")
            partes.append(f"queda debiendo {formato.dinero(max(0, saldo - usd))}")
            reparto.value = " · ".join(partes)
        page.update()

    monto.on_change = refrescar

    def elegir(e):
        nuevo = next((m for m in metodos if m["id"] == e.control.value), None)
        if nuevo:
            estado["metodo"] = nuevo
        refrescar()

    desplegable = ft.Dropdown(
        label="Cómo paga", value=metodos[0]["id"], dense=True,
        border_color=paleta.BEIGE, focused_border_color=paleta.MARCA,
        options=[ft.DropdownOption(key=m["id"], text=m["nombre"])
                 for m in metodos],
        on_select=elegir)   # en Flet 0.85.3 el evento es on_select

    def todo(e):
        metodo = estado["metodo"]
        monto.value = (f"{saldo:.2f}" if metodo["moneda"] == "USD"
                       else f"{saldo * tasa:.2f}")
        refrescar()

    def guardar(e):
        try:
            resultado = basedatos.registrar_abono(
                cliente["id"], formato.numero(monto.value), estado["metodo"]["moneda"],
                tasa, estado["metodo"]["id"], nota.value)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.cerrar(page, dialogo)
        saldadas = [str(a["correlativo"]) for a in resultado["aplicadas"]
                    if a["saldada"]]
        aviso = f"Abono de {formato.dinero(resultado['monto_usd'])} registrado."
        if saldadas:
            aviso += (" Saldó la" + ("s" if len(saldadas) > 1 else "")
                      + " factura" + ("s" if len(saldadas) > 1 else "")
                      + " N° " + ", ".join(saldadas) + ".")
        dialogos.exito(page, aviso)
        al_terminar()

    nota = ft.TextField(label="Nota (opcional)", dense=True,
                        border_color=paleta.BEIGE,
                        focused_border_color=paleta.MARCA)

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato(f"Abono de {cliente['nombre']}", size=16),
        content=ft.Column([
            estilo.dato(f"Debe {formato.dinero(saldo)}", color=paleta.MARCA),
            desplegable,
            monto,
            equivalente,
            ft.TextButton(content="Pagar todo", on_click=todo,
                          style=ft.ButtonStyle(color=paleta.MARCA)),
            nota,
            reparto,
            problema,
        ], spacing=8, tight=True, width=320, scroll=ft.ScrollMode.AUTO),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Registrar", guardar),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)


# ==========================================================================
# Todos los clientes
# ==========================================================================

def _lista_clientes(page, al_volver, al_abrir):
    contenedor = ft.Container(expand=True)
    estado = {"busqueda": ""}
    filas = ft.Column(spacing=8, tight=True)

    def recargar():
        filas.controls.clear()
        clientes = basedatos.listar_clientes(estado["busqueda"])
        for c in clientes:
            saldo = basedatos.saldo_cliente(c["id"])
            filas.controls.append(estilo.tarjeta(
                ft.Row([
                    ft.Column([
                        estilo.dato(c["nombre"], size=15, lineas=1),
                        estilo.apunte(c["telefono"] or "sin teléfono"),
                    ], spacing=1, tight=True, expand=True),
                    estilo.dato(formato.dinero(saldo) if saldo > 0 else "al día",
                                size=13,
                                color=paleta.MARCA if saldo > 0 else paleta.OK),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                                  icon_color=paleta.ERROR, icon_size=18,
                                  tooltip="Borrar",
                                  on_click=lambda e, f=c: _borrar_cliente(
                                      page, f, recargar)),
                ], spacing=4),
                padding=(12, 8, 4, 8),
                al_tocar=lambda e, cid=c["id"]: al_abrir(cid)))
        if not clientes:
            filas.controls.append(estilo.vacio(
                ft.Icons.PEOPLE_OUTLINE,
                "No hay clientes todavía." if not estado["busqueda"]
                else f"Nada coincide con «{estado['busqueda']}».",
                "Toca + para agregar el primero."
                if not estado["busqueda"] else None))
        page.update()

    def buscar(e):
        estado["busqueda"] = buscador.value or ""
        recargar()

    buscador = ft.TextField(hint_text="Buscar cliente", dense=True,
                            border_color=paleta.BEIGE,
                            focused_border_color=paleta.MARCA,
                            prefix_icon=ft.Icons.SEARCH, on_change=buscar,
                            bgcolor=paleta.TARJETA, border_radius=10)

    contenedor.content = ft.Column([
        estilo.encabezado(
            "Clientes", al_volver=al_volver,
            acciones=[ft.IconButton(icon=ft.Icons.ADD, icon_color=paleta.FONDO,
                                    bgcolor=paleta.MARCA,
                                    tooltip="Agregar cliente",
                                    on_click=lambda e: _formulario_cliente(
                                        page, None, recargar))],
            extra=buscador),
        ft.Container(content=ft.Column([filas], scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 12, 14, 20), expand=True),
    ], spacing=0, expand=True)

    recargar()
    return contenedor


def _formulario_cliente(page, existente, al_terminar):
    nombre = ft.TextField(label="Nombre",
                          value=existente["nombre"] if existente else "",
                          border_color=paleta.BEIGE,
                          focused_border_color=paleta.MARCA)
    telefono = ft.TextField(label="Teléfono",
                            value=existente["telefono"] if existente else "",
                            keyboard_type=ft.KeyboardType.PHONE,
                            border_color=paleta.BEIGE,
                            focused_border_color=paleta.MARCA)
    notas = ft.TextField(label="Notas",
                         value=existente["notas"] if existente else "",
                         border_color=paleta.BEIGE,
                         focused_border_color=paleta.MARCA)
    problema = ft.Text("", size=12, weight=estilo.MEDIO, color=paleta.ERROR)

    def guardar(e):
        try:
            if existente:
                basedatos.actualizar_cliente(existente["id"], nombre.value,
                                             telefono.value, notas.value)
            else:
                basedatos.crear_cliente(nombre.value, telefono.value, notas.value)
        except ValueError as ex:
            problema.value = str(ex)
            page.update()
            return
        dialogos.cerrar(page, dialogo)
        dialogos.exito(page, "Cliente guardado.")
        al_terminar()

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato("Editar cliente" if existente else "Nuevo cliente",
                          size=16),
        content=ft.Column([nombre, telefono, notas, problema], spacing=12,
                          tight=True, width=310),
        actions=[
            estilo.boton("Cancelar", lambda e: dialogos.cerrar(page, dialogo),
                         principal=False),
            estilo.boton("Guardar", guardar),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)


def _borrar_cliente(page, cliente, al_terminar):
    def borrar():
        try:
            basedatos.eliminar_cliente(cliente["id"])
        except ValueError as ex:
            dialogos.error(page, str(ex))
            return
        dialogos.exito(page, "Cliente borrado.")
        al_terminar()

    dialogos.confirmar(
        page, f"Borrar a {cliente['nombre']}",
        "Deja de aparecer en la lista. Las ventas que ya se le hicieron no se "
        "tocan. Si todavía debe algo, no se puede borrar.",
        "Borrar", borrar, peligro=True)
