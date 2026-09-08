"""Historial de ventas: todo lo vendido, no solo lo de hoy.

Se entra desde Venta. Trae **cuarenta por tanda** con un botón para seguir: nadie
recorre mil ventas con el dedo, y cargarlas todas de golpe haría lenta la primera
apertura justo cuando el historial empieza a valer la pena.

Las ventas van agrupadas por día, con su total. Una lista corrida de cincuenta
filas no deja ver dónde termina un día y empieza otro, que es lo primero que uno
busca al revisar hacia atrás.
"""

from datetime import date

import flet as ft

from backend import basedatos
from frontend import dialogos
from frontend import estilo
from backend import formato
from frontend import paleta

POR_TANDA = 40

PERIODOS = [("hoy", "Hoy"), ("semana", "Semana"), ("mes", "Mes"),
            ("todo", "Todo")]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
def _titulo_de_dia(dia):
    hoy = date.today()
    if dia == hoy:
        return "Hoy"
    if (hoy - dia).days == 1:
        return "Ayer"
    return f"{DIAS[dia.weekday()]} {dia.day} de {formato.MESES[dia.month - 1]}"


def crear_vista_historial(page, al_volver):
    estado = {"periodo": "mes", "tope": POR_TANDA}
    contenedor = ft.Container(expand=True)

    def repintar():
        contenedor.content = _pantalla(page, estado, repintar, al_volver).content
        page.update()

    contenedor.content = _pantalla(page, estado, repintar, al_volver).content
    return contenedor


def _rango(periodo):
    if periodo == "todo":
        return None, None
    desde, hasta, _ = basedatos.rango(periodo)
    return desde, hasta


def _pantalla(page, estado, repintar, al_volver):
    desde, hasta = _rango(estado["periodo"])
    ventas = basedatos.listar_ventas(desde, hasta, estado["tope"])
    total_filas = basedatos.contar_ventas(desde, hasta)
    resumen = basedatos.resumen_ventas(desde, hasta)
    pagos = basedatos.desglose_de_pagos(desde or "0000", hasta)

    def elegir(periodo):
        estado["periodo"] = periodo
        estado["tope"] = POR_TANDA
        repintar()

    def mas(e):
        estado["tope"] += POR_TANDA
        repintar()

    bloques = []

    if pagos:
        bloques.append(estilo.tarjeta(ft.Column(
            [estilo.seccion("Entró por")] +
            [ft.Row([
                estilo.dato(p["metodo_nombre"], size=13),
                ft.Container(expand=True),
                estilo.dato(formato.dinero(p["monto"]) if p["moneda"] == "USD"
                            else formato.bolivares(p["monto"]),
                            size=13, color=paleta.MARCA),
            ]) for p in pagos], spacing=8, tight=True)))

    # Agrupadas por día, con el total de cada uno.
    dia_actual = None
    del_dia = []
    for v in ventas:
        dia = formato.dia_local(v["fecha"])
        if dia != dia_actual:
            if dia_actual is not None:
                bloques.append(_grupo(dia_actual, del_dia, page, repintar))
                del_dia = []
            dia_actual = dia
        del_dia.append(v)
    if dia_actual is not None:
        bloques.append(_grupo(dia_actual, del_dia, page, repintar))

    if not ventas:
        bloques.append(estilo.vacio(
            ft.Icons.RECEIPT_LONG,
            "No hay ventas en este período.",
            "Prueba con otro período o registra la primera."))

    faltan = total_filas - len(ventas)
    if faltan > 0:
        bloques.append(ft.TextButton(
            content=f"Ver más ({faltan} sin mostrar)", on_click=mas,
            style=ft.ButtonStyle(color=paleta.MARCA)))

    contenedor = ft.Container(expand=True)
    contenedor.content = ft.Column([
        estilo.encabezado(
            "Historial de ventas",
            f"{resumen['ventas']} venta(s) · {formato.dinero(resumen['ingreso'])}",
            al_volver=al_volver,
            extra=estilo.pastillas(PERIODOS, estado["periodo"], elegir,
                                   sobre_beige=True)),
        ft.Container(content=ft.Column(bloques, spacing=12, tight=True,
                                       scroll=ft.ScrollMode.AUTO),
                     padding=ft.Padding(14, 14, 14, 20), expand=True),
    ], spacing=0, expand=True)
    return contenedor


def _grupo(dia, ventas, page, repintar):
    total = sum(float(v["total_usd"]) for v in ventas
                if v["estado"] == "activa")
    filas = [ft.Row([
        estilo.seccion(_titulo_de_dia(dia)),
        ft.Container(expand=True),
        estilo.apunte(f"{len(ventas)} · {formato.dinero(total)}", size=12),
    ])]
    filas += [_fila_venta(v, page, repintar) for v in ventas]
    return ft.Column(filas, spacing=8, tight=True)


def _fila_venta(v, page, repintar):
    anulada = v["estado"] == "anulada"
    detalle = f"{formato.hora_local(v['fecha'])}"
    if v["tipo"] == "credito":
        cliente = basedatos.obtener_cliente(v["cliente_id"]) if v["cliente_id"] else None
        detalle += f" · crédito de {cliente['nombre']}" if cliente else " · crédito"
    if anulada:
        detalle += "  ·  ANULADA"

    return estilo.tarjeta(
        ft.Row([
            ft.Column([
                estilo.dato(f"N° {v['correlativo']}", size=14,
                            color=paleta.TEXTO_SUAVE if anulada else paleta.TEXTO),
                estilo.apunte(detalle,
                              color=paleta.ERROR if anulada else paleta.TEXTO_SUAVE),
            ], spacing=1, tight=True, expand=True),
            ft.Column([
                estilo.dato(formato.dinero(v["total_usd"]), size=14,
                            color=paleta.TEXTO_SUAVE if anulada else paleta.MARCA),
                estilo.apunte(formato.bolivares(float(v["total_usd"])
                                         * float(v["tasa_usada"])), size=10),
            ], spacing=0, tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.END),
        ], spacing=8),
        padding=(12, 10, 12, 10),
        al_tocar=None if anulada else (
            lambda e: ver_venta(page, v["id"], v["correlativo"], repintar)),
    )


def ver_venta(page, venta_id, correlativo, recargar):
    """El detalle de una venta, con la opción de anularla."""
    venta, lineas = basedatos.obtener_venta(venta_id)
    if venta is None:
        return
    pagos = basedatos.pagos_de_venta(venta_id)

    detalle = [ft.Row([
        estilo.dato(f"{formato.cantidad(l['cantidad'])} × {l['nombre_congelado']}",
                    size=13),
        ft.Container(expand=True),
        estilo.dato(formato.dinero(float(l["cantidad"]) * float(l["precio_unit_usd"])),
                    size=13),
    ]) for l in lineas]

    if pagos:
        detalle.append(ft.Divider(height=12, color=paleta.BEIGE))
        detalle.append(estilo.seccion("Pagó con"))
        for p in pagos:
            detalle.append(ft.Row([
                estilo.dato(p["metodo_nombre"], size=13),
                ft.Container(expand=True),
                estilo.dato(formato.dinero(p["monto"]) if p["moneda"] == "USD"
                            else formato.bolivares(p["monto"]), size=13),
            ]))

    def anular():
        try:
            basedatos.anular_venta(venta_id)
        except ValueError as ex:
            dialogos.error(page, str(ex))
            return
        dialogos.exito(page, f"Venta N° {correlativo} anulada. "
                             f"La mercancía volvió al inventario.")
        recargar()

    def pedir_anulacion(e):
        dialogos.cerrar(page, dialogo)
        dialogos.confirmar(
            page, f"Anular la venta N° {correlativo}",
            "La venta queda marcada como anulada y la mercancía vuelve al "
            "inventario. No se borra: el historial sigue mostrando que ocurrió.",
            "Anular", anular, peligro=True)

    dialogo = ft.AlertDialog(
        modal=True,
        title=estilo.dato(f"Venta N° {correlativo}", size=16),
        content=ft.Column(detalle + [
            ft.Divider(height=14, color=paleta.BEIGE),
            ft.Row([
                estilo.seccion("Total"),
                ft.Container(expand=True),
                estilo.cifra(formato.dinero(venta["total_usd"]), size=18),
            ]),
            estilo.apunte(formato.bolivares(float(venta["total_usd"])
                                     * float(venta["tasa_usada"]))),
        ], tight=True, spacing=8, width=310, scroll=ft.ScrollMode.AUTO,
            # Sin tope, una columna con scroll se estira a toda la pantalla y la
            # ventana de una venta de dos renglones quedaba enorme.
            height=min(420, 130 + 30 * len(detalle))),
        actions=[
            estilo.boton("Anular", pedir_anulacion, peligro=True),
            estilo.boton("Cerrar", lambda e: dialogos.cerrar(page, dialogo)),
        ],
        bgcolor=paleta.TARJETA)
    dialogos.abrir(page, dialogo)
