"""Pulsa los botones de verdad, no solo dibuja las pantallas.

Nace de un fallo real: al reescribir la pantalla de Venta se perdió
`_formulario_cliente_rapido`. La aplicación reventaba al tocar «cliente nuevo» y
**las 260 comprobaciones pasaban igual**, porque construían las pantallas sin
pulsar nada.

Aquí se abre cada diálogo, se llenan sus campos y se pulsa su botón principal, y
después se comprueba en la base que la acción de verdad ocurrió. `revisar.py`
encuentra los nombres que no existen; esto encuentra lo que sí existe pero no hace
lo que dice.
"""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="shopstores_botones_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
from PIL import Image

from backend import basedatos as bd
from backend import fotos
from backend import seguridad
from frontend import dialogos
from frontend.vistas import (catalogo_view, cobros_view, configuracion_view,
                             gestion_view, historial_view, inicio_view,
                             inventario_view, ventas_view)

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


class Pagina:
    """Lo mínimo que usan las vistas. `run_thread` corre en el acto para que la
    prueba pueda comprobar el resultado sin esperar."""
    platform = ft.PagePlatform.WINDOWS

    def __init__(self):
        self.overlay = []
        self.services = []

    def update(self):
        pass

    def run_thread(self, f):
        f()


def dialogo_abierto(page):
    abiertos = [c for c in page.overlay if isinstance(c, ft.AlertDialog)]
    return abiertos[-1] if abiertos else None


def campos_de(dialogo):
    """Los campos de texto del diálogo, en orden."""
    encontrados = []

    def buscar(control):
        if isinstance(control, ft.TextField):
            encontrados.append(control)
        for atributo in ("controls", "content"):
            v = getattr(control, atributo, None)
            if isinstance(v, list):
                for h in v:
                    buscar(h)
            elif v is not None and hasattr(v, "__class__"):
                buscar(v)

    buscar(dialogo.content)
    return encontrados


def pulsar(dialogo, etiqueta):
    for boton in dialogo.actions:
        if getattr(boton, "content", None) == etiqueta:
            boton.on_click(None)
            return True
    return False


def imagen():
    im = Image.new("RGB", (600, 600), "#A67C52")
    b = io.BytesIO()
    im.save(b, format="JPEG")
    return b.getvalue()


page = Pagina()
seguridad.establecer("472913", "472913")
bd.guardar_tasa(620.0)

print("Inventario: alta de producto")
inventario_view.crear_vista_inventario(page, lambda: None)
inventario_view._formulario_producto(page, None, lambda: None)
dlg = dialogo_abierto(page)
check(dlg is not None, "se abre el formulario de producto")
campos = campos_de(dlg)
campos[0].value = "Cartera de prueba"
campos[1].value = "Cuero"
campos[2].value = "20"
campos[3].value = "50"
campos[4].value = "10"
check(pulsar(dlg, "Guardar"), "tiene botón Guardar")
productos = bd.listar_productos()
check(len(productos) == 1 and productos[0]["nombre"] == "Cartera de prueba",
      "el producto quedó guardado")
producto_id = productos[0]["id"]
check(float(bd.obtener_producto(producto_id)["stock"]) == 10,
      "con su existencia inicial")

print("\nInventario: entrada de mercancía y ajuste")
bd.guardar_foto(producto_id, fotos.preparar(imagen()))
inventario_view._ficha(page, producto_id, lambda: None)
inventario_view._reabastecer(page, producto_id, 5, lambda: None)
check(float(bd.obtener_producto(producto_id)["stock"]) == 15, "entraron 5 unidades")
inventario_view._ajustar(page, producto_id, 12, lambda: None)
check(float(bd.obtener_producto(producto_id)["stock"]) == 12, "el ajuste dejó 12")

print("\nVenta: cliente nuevo desde el carrito")
ventas_view.crear_vista_ventas(page, lambda n: None)
ventas_view._formulario_cliente_rapido(page, lambda: None)
dlg = dialogo_abierto(page)
check(dlg is not None, "se abre el alta rápida de cliente")
campos = campos_de(dlg)
campos[0].value = "Ana Pérez"
campos[1].value = "0412-1234567"
check(pulsar(dlg, "Guardar"), "tiene botón Guardar")
check([c["nombre"] for c in bd.listar_clientes()] == ["Ana Pérez"],
      "el cliente quedó guardado")
cliente_id = bd.listar_clientes()[0]["id"]

print("\nVenta: cobrar")
efectivo = [m for m in bd.listar_metodos() if m["moneda"] == "USD"][0]["id"]
carrito = {producto_id: {"nombre": "Cartera de prueba", "precio": 50.0,
                         "stock": 12.0, "cantidad": 2.0}}
pagos = [{"metodo_id": efectivo, "campo": ft.TextField(value="100")}]
ventas_view._registrar(page, carrito, pagos, 620.0, lambda: None,
                       {"activo": False, "cliente_id": None, "vence": None})
check(bd.resumen_de_hoy()["ventas"] == 1, "se registró la venta")
check(float(bd.obtener_producto(producto_id)["stock"]) == 10, "y descontó el stock")

print("\nVenta a crédito")
ventas_view._registrar(page, carrito, [], 620.0, lambda: None,
                       {"activo": True, "cliente_id": cliente_id, "vence": None})
check(bd.saldo_cliente(cliente_id) == 100.0, "el cliente quedó debiendo $100")

print("\nCobros: abono")
cobros_view._ficha_cliente(page, cliente_id, lambda: None)
cobros_view._dialogo_abono(page, bd.obtener_cliente(cliente_id), 100.0,
                           lambda: None)
dlg = dialogo_abierto(page)
check(dlg is not None, "se abre el diálogo de abono")
campos = campos_de(dlg)
campos[0].value = "40"
check(pulsar(dlg, "Registrar"), "tiene botón Registrar")
check(bd.saldo_cliente(cliente_id) == 60.0, "el saldo bajó a $60")

print("\nCobros: editar cliente")
cobros_view._formulario_cliente(page, bd.obtener_cliente(cliente_id),
                                lambda: None)
dlg = dialogo_abierto(page)
campos = campos_de(dlg)
campos[0].value = "Ana Rodríguez"
check(pulsar(dlg, "Guardar"), "tiene botón Guardar")
check(bd.obtener_cliente(cliente_id)["nombre"] == "Ana Rodríguez",
      "el nombre cambió")

print("\nGestión: alta de gasto")
gestion_view._formulario_gasto(page, lambda: None)
dlg = dialogo_abierto(page)
check(dlg is not None, "se abre el formulario de gasto")
campos = campos_de(dlg)
campos[0].value = "Delivery"
campos[1].value = "Moto"
campos[2].value = "15"
check(pulsar(dlg, "Guardar"), "tiene botón Guardar")
check(len(bd.listar_gastos()) == 1, "el gasto quedó guardado")
check(bd.metricas("hoy")["gastos"] == 15.0, "y resta en las métricas")

print("\nConfiguración: método de pago")
configuracion_view._formulario_metodo(page, None, lambda: None)
dlg = dialogo_abierto(page)
campos = campos_de(dlg)
campos[0].value = "Binance"
check(pulsar(dlg, "Guardar"), "tiene botón Guardar")
check("Binance" in [m["nombre"] for m in bd.listar_metodos()],
      "el método quedó guardado")

print("\nCatálogo: generar")
vista = catalogo_view.crear_vista_catalogo(page, lambda: None, lambda: None)
check(vista is not None, "se construye la pantalla del catálogo")
from backend import catalogo
pdf, cuantos, _ = catalogo.armar(True)
check(pdf[:5] == b"%PDF-" and cuantos == 1, "el catálogo sale con el producto")

print("\nUn formulario incompleto no guarda nada")
antes = bd.contar_productos()
inventario_view._formulario_producto(page, None, lambda: None)
dlg = dialogo_abierto(page)
pulsar(dlg, "Guardar")          # sin llenar el nombre
check(bd.contar_productos() == antes, "el producto sin nombre no se creó")

print()
print("El diálogo no se destruye durante su propio clic")
# Es lo que colgaba la ventana: al quitar el AlertDialog del overlay dentro del
# `on_click` de su propio botón, el control muere con su evento en vuelo y el botón
# Guardar deja de responder. La limpieza va al abrir el siguiente, no al cerrar.
from frontend import dialogos
ventas_view._formulario_cliente_rapido(page, lambda: None)
_dlg = dialogo_abierto(page)
_campos = campos_de(_dlg)
_campos[0].value = "Segundo cliente"
pulsar(_dlg, "Guardar")
check(_dlg.open is False, "el diálogo queda cerrado")
check(any(c is _dlg for c in page.overlay),
      "pero sigue en el overlay, no se destruye dentro de su propio clic")
dialogos.exito(page, "un aviso cualquiera")
check(any(c is _dlg for c in page.overlay) and _dlg.open is False,
      "y un aviso posterior no lo vuelve a montar")
# La limpieza va con un evento de retraso: en la apertura siguiente solo se anota,
# porque esa apertura puede ser el mismo clic que lo cerró (Guardar la tasa abre la
# confirmación). Se saca en la de después, cuando ese evento ya terminó.
ventas_view._formulario_cliente_rapido(page, lambda: None)
check(any(c is _dlg for c in page.overlay),
      "en la apertura siguiente todavía sigue ahí, solo queda anotado")
ventas_view._formulario_cliente_rapido(page, lambda: None)
check(not any(c is _dlg for c in page.overlay),
      "y en la de después sí se limpia")
check(len([c for c in page.overlay
           if isinstance(c, ft.AlertDialog) and not c.open]) <= 1,
      "no se acumulan diálogos cerrados dando vueltas")
# Un formulario con un error de validación se queda abierto a propósito, para que
# la persona corrija. Ese NO se puede quitar: su ventana quedaría huérfana.
check(len([c for c in page.overlay
           if isinstance(c, ft.AlertDialog) and c.open]) >= 1,
      "y los que siguen abiertos se respetan")

print()
print("Venta: el buscador abre el catálogo")
# Se busca el buscador dentro de la pantalla armada y se usa como lo haría una
# persona: tocarlo, mirar la lista, escribir para filtrar, tocar un producto.
vista_venta = ventas_view.crear_vista_ventas(page, lambda n: None)


def buscar_control(control, condicion):
    if condicion(control):
        return control
    for atributo in ("controls", "content"):
        v = getattr(control, atributo, None)
        hijos = v if isinstance(v, list) else ([v] if v is not None else [])
        for h in hijos:
            if hasattr(h, "__class__") and h.__class__.__module__.startswith("flet"):
                hallado = buscar_control(h, condicion)
                if hallado is not None:
                    return hallado
    return None


campo = buscar_control(vista_venta, lambda c: isinstance(c, ft.TextField)
                       and (c.hint_text or "").startswith("Buscar o ver"))
check(campo is not None, "el buscador está en la pantalla")
check(campo.on_focus is not None, "reacciona al tocarlo, no solo al escribir")

lista = buscar_control(vista_venta, lambda c: isinstance(c, ft.Column)
                       and c.visible is False and c.spacing == 6)
check(lista is not None and not lista.visible,
      "la lista arranca oculta, con el carrito a la vista")

campo.on_focus(None)
check(lista.visible, "al tocar el buscador se abre la lista")
check(len(lista.controls) >= 1,
      f"y muestra los productos sin escribir nada ({len(lista.controls)})")

campo.value = "zzz-no-existe"
campo.on_change(None)
check(len(lista.controls) == 1,
      "al escribir algo que no coincide queda el aviso de que no hay nada")

campo.value = "Cartera"
campo.on_change(None)
check(len(lista.controls) >= 1, "y al escribir un nombre real vuelve a listar")

print()
print("Venta: escribir el monto no rehace la fila, y Completar cuadra el pago")


def todos(control):
    yield control
    for atributo in ("controls", "content"):
        v = getattr(control, atributo, None)
        hijos = v if isinstance(v, list) else ([v] if v is not None else [])
        for h in hijos:
            if hasattr(h, "__class__") and h.__class__.__module__.startswith("flet"):
                yield from todos(h)


# Se carga un producto al carrito tocando la lista, igual que una persona.
for fila in lista.controls:
    if getattr(fila, "on_click", None) is not None:
        fila.on_click(None)
        break

monto = next((c for c in todos(vista_venta)
              if isinstance(c, ft.TextField) and c.label == "Monto"), None)
check(monto is not None, "hay un campo de monto en la pantalla")

filas = next((c for c in todos(vista_venta)
              if isinstance(c, ft.Column) and any(
                  isinstance(x, ft.Row) and any(h is monto for h in todos(x))
                  for x in (c.controls or []))), None)
check(filas is not None, "y vive dentro de la lista de pagos")

# El fallo real: cada tecla reconstruía la fila, el campo se remontaba y el foco
# se perdía, así que había que volver a tocarlo después de cada dígito.
fila_antes = filas.controls[0]
monto.value = "1"
monto.on_change(None)
check(filas.controls[0] is fila_antes,
      "al teclear un dígito la fila sigue siendo la misma (no se pierde el foco)")
monto.value = "12"
monto.on_change(None)
check(filas.controls[0] is fila_antes, "y con el segundo dígito tampoco cambia")

completar = next((c for c in todos(vista_venta)
                  if isinstance(c, ft.TextButton) and c.content == "Completar"), None)
check(completar is not None, "existe el botón de completar el restante")
check(completar.visible, "y se ofrece justo cuando el pago no cuadra")

completar.on_click(None)
estado = next((c for c in todos(vista_venta)
               if isinstance(c, ft.Text) and str(c.value).startswith(
                   ("El pago cuadra", "Faltan", "Se pasa"))), None)
check(estado is not None and estado.value == "El pago cuadra",
      f"al pulsarlo el pago queda cuadrado ({estado.value if estado else 'sin estado'})")
check(not completar.visible, "y el botón se retira porque ya no falta nada")

cobrar = next((c for c in todos(vista_venta)
               if isinstance(c, ft.ElevatedButton) and c.content == "Cobrar"), None)
check(cobrar is not None and not cobrar.disabled,
      "y Cobrar queda habilitado")

print()
print("Historial: el detalle de la venta se cierra al tocar Cerrar")
# Fallo real: los controles de Flet son dataclasses y se comparan por VALOR, asi
# que dos detalles de la misma venta daban `a == b`. Tocar la fila dos veces
# apilaba dos ventanas identicas; Cerrar cerraba la de arriba y quedaba la de
# abajo, igualita, y parecia que el boton no servia.
metodos = bd.listar_metodos()
producto = bd.crear_producto("Para historial", "", 5.0, 19.0, stock_inicial=3)
venta = bd.registrar_venta(
    [{"producto_id": producto, "cantidad": 1}], 620.0,
    pagos=[{"metodo_id": metodos[0]["id"], "monto": 19.0}])

page.overlay.clear()
historial_view.ver_venta(page, venta["id"], venta["correlativo"], lambda: None)
historial_view.ver_venta(page, venta["id"], venta["correlativo"], lambda: None)
abiertos = [c for c in page.overlay if isinstance(c, ft.AlertDialog) and c.open]
check(len(abiertos) == 1,
      f"tocar la factura dos veces deja una sola ventana ({len(abiertos)})")

detalle = abiertos[-1]
boton_cerrar = [a for a in detalle.actions
                if getattr(a, "content", None) == "Cerrar"][0]
boton_cerrar.on_click(None)
check(not detalle.open, "al tocar Cerrar la ventana se cierra")
check(not [c for c in page.overlay if isinstance(c, ft.AlertDialog) and c.open],
      "y no queda ninguna otra detras")

# El overlay se maneja por identidad: quitar uno no puede llevarse a otro que
# solo se le parezca.
page.overlay.clear()
gemelo_a = ft.AlertDialog(modal=True, title=ft.Text("igualitos"))
gemelo_b = ft.AlertDialog(modal=True, title=ft.Text("igualitos"))
check(gemelo_a == gemelo_b, "dos diálogos iguales se comparan como iguales")
page.overlay.extend([gemelo_a, gemelo_b])
dialogos._quitar(page, gemelo_b)
check(len(page.overlay) == 1 and page.overlay[0] is gemelo_a,
      "y aun así se quita el que se pidió, no el que se le parece")

print()
print("Inventario: la foto nueva aparece sin salir del producto")


def cierre(funcion, nombre):
    """Saca del closure la función que le pasaron, para poder dispararla."""
    libres = funcion.__code__.co_freevars
    if nombre not in libres:
        return None
    return funcion.__closure__[libres.index(nombre)].cell_contents


buf = io.BytesIO()
Image.new("RGB", (900, 700), (180, 120, 60)).save(buf, format="JPEG")
foto_cruda = buf.getvalue()

con_fotos = bd.crear_producto("Con fotos", "", 5.0, 19.0, stock_inicial=3)
ficha = inventario_view._ficha(page, con_fotos, lambda: None)

tira = next((c for c in todos(ficha)
             if isinstance(c, ft.Row) and c.wrap and c.spacing == 8), None)
check(tira is not None, "la tira de fotos está en la ficha")
check(not [c for c in todos(tira) if isinstance(c, ft.Image)],
      "y arranca sin ninguna foto")

boton_foto = next(c for c in todos(tira)
                  if isinstance(c, ft.Container) and c.width == 76
                  and c.bgcolor is not None)
repintar = cierre(boton_foto.on_click, "recargar")
# El fallo: repintaba reemplazando el contenido de un contenedor, y la miniatura
# no se veía hasta salir del producto y volver a entrar.
check(repintar is not None and repintar.__name__ == "refrescar_fotos",
      f"el botón repinta solo la tira ({repintar.__name__ if repintar else 'nada'})")

bd.guardar_foto(con_fotos, fotos.preparar(foto_cruda))
repintar()
check(len([c for c in todos(tira) if isinstance(c, ft.Image)]) == 1,
      "tras agregarla, la foto está en la MISMA tira que ya estaba en pantalla")

# La otra mitad: repintar la ficha entera, muchas veces, tiene que escribir
# siempre en el MISMO contenedor montado. Si cada repintado construye una copia y
# le roba el contenido, del segundo en adelante se escribe en una pantalla que no
# existe (ver frontend/pantalla.py).
ficha2 = inventario_view._ficha(page, con_fotos, lambda: None)
editar = next(c for c in todos(ficha2) if isinstance(c, ft.IconButton)
              and c.icon == ft.Icons.EDIT)
recargar = cierre(editar.on_click, "recargar")
check(recargar is not None, "la ficha tiene su repintado")

bd.actualizar_producto(con_fotos, "Renombrado una vez", "", 5.0, 19.0, True)
recargar()
check(any(getattr(c, "value", None) == "Renombrado una vez" for c in todos(ficha2)),
      "el primer repintado se ve en la ficha montada")

# El que fallaba antes.
bd.actualizar_producto(con_fotos, "Renombrado dos veces", "", 5.0, 19.0, True)
editar2 = next(c for c in todos(ficha2) if isinstance(c, ft.IconButton)
               and c.icon == ft.Icons.EDIT)
cierre(editar2.on_click, "recargar")()
check(any(getattr(c, "value", None) == "Renombrado dos veces" for c in todos(ficha2)),
      "y el segundo también, sin salir y volver a entrar")

print()
print("Inicio: cambiar la tasa, que abre una ventana desde otra")
# Fallo real: Guardar cerraba la ventana de la tasa y enseguida abría la de
# confirmar. `abrir` limpiaba los cerrados y se llevaba la primera **con su clic
# todavía en vuelo**: la ventana quedaba colgada y dejaban de responder tanto
# Guardar como Cancelar. La limpieza tiene que ir con un evento de retraso.
bd.guardar_tasa(950.0)
page.overlay.clear()
dialogos._POR_LIMPIAR.clear()

tarjeta_tasa = inicio_view._tarjeta_tasa(page, lambda: None)
boton_actualizar = next(c for c in todos(tarjeta_tasa)
                        if isinstance(c, ft.ElevatedButton))
boton_actualizar.on_click(None)

ventana_tasa = dialogo_abierto(page)
check(ventana_tasa is not None and ventana_tasa.title.value == "Tasa del día",
      "se abre la ventana de la tasa")

campo_tasa = next(c for c in todos(ventana_tasa) if isinstance(c, ft.TextField))
campo_tasa.value = "1100"
guardar_tasa = [a for a in ventana_tasa.actions if a.content == "Guardar"][0]
guardar_tasa.on_click(None)

check(not ventana_tasa.open, "al guardar, la ventana de la tasa se cierra")
check(any(c is ventana_tasa for c in page.overlay),
      "y NO se saca del overlay mientras su propio clic sigue en vuelo")
confirmacion = dialogo_abierto(page)
check(confirmacion is not None and confirmacion is not ventana_tasa,
      "encima aparece la confirmación")

# La ventana vieja se va en la apertura siguiente, cuando ya no hay evento suyo.
sigue = [c for c in page.overlay if c is ventana_tasa]
dialogos.confirmar(page, "otra cosa", "explicación", "Sí", lambda: None)
check(sigue and not [c for c in page.overlay if c is ventana_tasa],
      "y recién ahí se limpia, en la apertura siguiente")

confirmar_tasa = [a for a in confirmacion.actions
                  if a.content == "Cambiar la tasa"]
check(len(confirmar_tasa) == 1, "la confirmación dice qué se va a hacer")


def estado_de(vista):
    """El período que muestra el subtítulo de la pantalla de Gastos."""
    for c in todos(vista):
        texto = str(getattr(c, "value", ""))
        if texto.startswith("Operativos · "):
            return texto.replace("Operativos · ", "").strip()
    return None


print()
print("Gestión: las pastillas de Gastos se pueden tocar muchas veces seguidas")
# Fallo real, visto en el teléfono: tocabas «Semana» y cambiaba; tocabas «Mes»
# después y no pasaba nada, había que salir y volver a entrar. La pantalla se
# repintaba construyendo una copia nueva y robándole el contenido, así que los
# botones repintados apuntaban a un contenedor que nunca se montó.
vista_gestion = gestion_view.crear_vista_gestion(page)


def pastillas_de(raiz):
    """Las pastillas son contenedores con `on_click` y una etiqueta corta."""
    encontradas = {}
    for c in todos(raiz):
        if isinstance(c, ft.Container) and c.on_click is not None:
            texto = getattr(getattr(c, "content", None), "value", None)
            if texto in ("Hoy", "Semana", "Mes"):
                encontradas[texto] = c
    return encontradas


ir_a_gastos = next(c for c in todos(vista_gestion)
                   if isinstance(c, ft.ElevatedButton) and c.content == "Gastos")
ir_a_gastos.on_click(None)
check("Gastos" in str([getattr(c, "value", "") for c in todos(vista_gestion)]),
      "se entra a la pantalla de Gastos")

for vuelta, (etiqueta, esperado) in enumerate(
        [("Hoy", "hoy"), ("Mes", "este mes"), ("Semana", "esta semana"),
         ("Hoy", "hoy")], 1):
    pastilla = pastillas_de(vista_gestion).get(etiqueta)
    check(pastilla is not None, f"la pastilla «{etiqueta}» está en pantalla (toque {vuelta})")
    if pastilla is None:
        break
    pastilla.on_click(None)
    # La prueba de verdad: que el toque haya cambiado el período. Antes, del
    # segundo en adelante se escribía en una pantalla que no estaba montada.
    check(estado_de(vista_gestion) == esperado,
          f"el toque {vuelta} deja el período en «{esperado}» "
          f"(quedó «{estado_de(vista_gestion)}»)")

print()
print("Arranque: un import que falla se ve en pantalla, no en blanco")
# Fallo real: en la version web la app quedo en blanco cinco veces seguidas, con
# un error distinto cada vez y ninguno visible sin abrir la consola del navegador.
# Los imports estaban arriba de main.py y mataban a Python antes de que existiera
# la red de errores. Aca se rompe un import a proposito y se mira la pantalla.
import importlib
import main as arranque


class PaginaVacia:
    """Una pagina recien abierta: acepta lo que `main` le quiera poner."""
    def __init__(self):
        self.controls = []

    def add(self, *controles):
        self.controls.extend(controles)

    def update(self):
        pass


roto = "frontend.vistas.pin_view"
guardado = sys.modules.get(roto)
sys.modules[roto] = None          # asi `import` falla de verdad
try:
    pantalla_rota = PaginaVacia()
    arranque.main(pantalla_rota)
    textos = [str(getattr(c, "value", "")) for c in pantalla_rota.controls]
    check(any("No se pudo arrancar" in t for t in textos),
          "en vez de quedar en blanco, dice que no pudo arrancar")
    check(any("pin_view" in t for t in textos),
          "y muestra el error real, con el modulo que fallo")
    check(pantalla_rota.bgcolor == "#FFFFFF",
          "la pantalla de error no depende de la paleta, que podria ser lo roto")
finally:
    if guardado is not None:
        sys.modules[roto] = guardado
    else:
        del sys.modules[roto]

print()
print("Puerta: el PIN funciona aunque hashlib llegue sin pbkdf2_hmac")
# Fallo real de la version web: el instalador de Flet importa `hashlib` antes de
# que el navegador instale la pieza que trae `pbkdf2_hmac`. El modulo quedaba sin
# la funcion y «Crear acceso» fallaba sin decir nada. Aca se le quita a proposito.
import hashlib
from frontend.vistas import pin_view

del hashlib.pbkdf2_hmac
check(not hasattr(hashlib, "pbkdf2_hmac"), "hashlib quedo como en el navegador")
seguridad.establecer("583027", "583027")
check(seguridad.verificar("583027"), "aun asi se crea el PIN y se comprueba")
check(not seguridad.verificar("583028"), "y un PIN equivocado sigue sin entrar")
check(hasattr(hashlib, "pbkdf2_hmac"), "la funcion quedo repuesta para lo que siga")

print()
print("Puerta: un fallo inesperado en el boton se ve, no queda mudo")


def boton_de(vista, etiqueta):
    return buscar_control(vista, lambda c: getattr(c, "on_click", None) is not None
                          and etiqueta in str(getattr(c, "content", "")))


def entrada_que_revienta():
    raise RuntimeError("pantalla de inicio rota a proposito")


puerta = pin_view._configurar(page, entrada_que_revienta)
campos_puerta = []
buscar_control(puerta, lambda c: isinstance(c, ft.TextField)
               and campos_puerta.append(c))
campos_puerta[0].value = "Prueba"
campos_puerta[1].value = "583027"
campos_puerta[2].value = "583027"
crear = boton_de(puerta, "Crear acceso")
check(crear is not None, "esta el boton «Crear acceso»")
# En la app el aviso esta montado en la pagina; aca no, y `update()` se quejaria
# de eso y no del boton. Se le da un `update` mudo solo mientras dura el toque.
update_real = ft.Text.update
ft.Text.update = lambda self: None
try:
    crear.on_click(None)
    salio_limpio = True
except Exception:
    salio_limpio = False
finally:
    ft.Text.update = update_real
check(salio_limpio, "el fallo no se escapa del boton")
avisos = []
buscar_control(puerta, lambda c: isinstance(c, ft.Text)
               and "No se pudo completar" in str(c.value) and avisos.append(c))
check(bool(avisos), "aparece el aviso en la pantalla")
check(bool(avisos) and "rota a proposito" in avisos[0].value,
      "y dice que fallo, para poder mandarlo en una captura")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
