"""El respaldo y las descargas: todo lo de la cuenta en un archivo para bajar.

Lo que se prueba es lo que de verdad duele si falla: que el archivo traiga
**todo** —las fotos incluidas, enteras—, que **no** traiga la huella del PIN ni
nada de otra cuenta, y que la descarga llegue al aparato por el camino que
corresponde: en la web, subiendo el archivo y abriendo un enlace dentro del
toque (lo unico que el iPhone deja); en la computadora, guardandolo directo.
"""
import asyncio
import base64
import io
import os
import shutil
import sys
import tempfile
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="shopstores_respaldo_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flet as ft
from PIL import Image

from backend import basedatos as bd
import postgres_local
_pg = postgres_local.conectar_la_app()
from backend import fotos
from backend import nube
from backend import respaldo
from backend import seguridad
from frontend import descargas
from frontend import selector

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


def imagen():
    im = Image.new("RGB", (800, 600), "#6B4E9B")
    b = io.BytesIO()
    im.save(b, format="JPEG")
    return b.getvalue()


print("Armar el respaldo")
seguridad.establecer("472913", "472913")
bd.guardar_tasa(620.0)
cartera = bd.crear_producto("Cartera", "Cuero", 20.0, 45.0, stock_inicial=5)
tamanos = fotos.preparar(imagen())
bd.guardar_foto(cartera, tamanos)
ana = bd.crear_cliente("Ana", "0414")
efectivo = bd.listar_metodos()[0]["id"]
bd.registrar_venta([{"producto_id": cartera, "cantidad": 1}], 620.0,
                   pagos=[{"metodo_id": efectivo, "monto": 45.0}])
bd.registrar_venta([{"producto_id": cartera, "cantidad": 1}], 620.0,
                   tipo="credito", cliente_id=ana)
bd.registrar_abono(ana, 10.0)
bd.crear_gasto("Delivery", "", 3.0)

# Otra cuenta en la misma base, con lo suyo: no puede aparecer en el archivo.
otra = _pg.otro_usuario()
otra("crear_producto", {"nombre": "De otra tienda", "descripcion": "",
                        "costo_usd": 1, "precio_usd": 2, "en_catalogo": True})

contenido, cuantos = respaldo.armar()
check(contenido[:2] == b"PK", "sale un .zip")
with zipfile.ZipFile(io.BytesIO(contenido)) as z:
    nombres = set(z.namelist())
check(nombres == {"datos.json", "LEEME.txt"}, "con los datos y un LEEME")
datos = respaldo.leer(contenido)
check(cuantos == {"productos": 1, "producto_fotos": 1, "clientes": 1,
                  "ventas": 2, "gastos": 1},
      f"cuenta bien lo que trae ({cuantos})")
check([p["nombre"] for p in datos["productos"]] == ["Cartera"],
      "trae los productos de la cuenta, y nada de otra cuenta")
for tabla in ("venta_lineas", "venta_pagos", "abonos", "abono_aplicaciones",
              "movimientos_inventario", "metodos_pago"):
    check(len(datos[tabla]) > 0, f"trae {tabla}")
foto = datos["producto_fotos"][0]
check(base64.b64decode(foto["completa"]) == tamanos["completa"]
      and base64.b64decode(foto["miniatura"]) == tamanos["miniatura"],
      "las fotos vienen enteras, byte por byte")
check("pin" not in datos["configuracion"]
      and "472913" not in contenido.decode("latin-1"),
      "no lleva la huella del PIN")
check(datos["configuracion"].get("tasa_bcv") is not None,
      "pero si la configuracion de la tienda (la tasa)")
check(all("user_id" not in fila for fila in datos["productos"] + datos["ventas"]),
      "sin el id del usuario, que no le dice nada a quien lea el archivo")
check(respaldo.nombre_sugerido().startswith("respaldo-shopstores-")
      and respaldo.nombre_sugerido().endswith(".zip"), "nombre con la fecha")

check(respaldo.ultimo() is None, "antes de bajarlo, figura como nunca hecho")
respaldo.marcar_hecho()
check(respaldo.ultimo() is not None, "y al bajarlo queda anotado")


print("\nSubir a la carpeta privada y pedir el enlace")
# Sin red: se mira que pedido se armaria. La carpeta lleva el id del usuario,
# que es lo que el RLS de Storage exige para dejar escribir.
pedidos = []
http_real = nube._http


def http_falso(metodo, ruta, cuerpo=None, token=None, reintentable=False,
               archivo=None, tipo=None, extra=None):
    pedidos.append({"metodo": metodo, "ruta": ruta, "cuerpo": cuerpo,
                    "archivo": archivo, "tipo": tipo, "extra": extra,
                    "token": token})
    if "/object/sign/" in ruta:
        return 200, '{"signedURL": "/object/sign/descargas/u-1/respaldo.zip?token=abc"}'
    return 200, '{"Key": "descargas/u-1/respaldo.zip"}'


import time  # noqa: E402
nube._http = http_falso
nube._sesion.update(token="t", refresh="r", vence=time.time() + 3600,
                    usuario="u-1")
try:
    nube.subir_archivo("respaldo.zip", contenido, "application/zip")
    subida = pedidos[-1]
    check(subida["ruta"] == "/storage/v1/object/descargas/u-1/respaldo.zip",
          "sube a la carpeta del usuario")
    check(subida["archivo"] == contenido and subida["tipo"] == "application/zip",
          "el archivo va tal cual, con su tipo")
    check(subida["extra"] == {"x-upsert": "true"} and subida["token"] == "t",
          "reemplaza al anterior, con la sesion")
    enlace = nube.enlace_de_descarga("respaldo.zip", "respaldo-shopstores-2026-10-14.zip")
    check(enlace.startswith(nube.URL + "/storage/v1/object/sign/descargas/u-1/"),
          "el enlace firmado apunta al archivo")
    check(enlace.endswith("&download=respaldo-shopstores-2026-10-14.zip"),
          "y baja con el nombre con fecha")
    check(pedidos[-1]["cuerpo"] == {"expiresIn": 3600}, "y vence en una hora")

    nube._sesion.update(usuario=None)
    try:
        nube.subir_archivo("x.zip", b"x", "application/zip")
        check(False, "sin usuario no sube nada")
    except nube.SinSesion:
        check(True, "sin usuario no sube nada")
finally:
    nube._http = http_real
    nube._sesion.update(token=None, refresh=None, vence=0.0, usuario=None)


print("\nDescargar: en la computadora se guarda directo")


class Pagina:
    platform = ft.PagePlatform.WINDOWS
    web = False

    def __init__(self):
        self.overlay, self.services = [], []

    def update(self):
        pass


class SelectorFalso:
    def __init__(self, ruta):
        self.ruta = ruta
        self.pedido = None

    async def save_file(self, **opciones):
        self.pedido = opciones
        return self.ruta


page = Pagina()
destino = os.path.join(TEMPORAL, "respaldo.zip")
selector.preparar(page)
falso = SelectorFalso(destino)
selector._por_pagina[id(page)]["selector"] = falso
avisado = []
asyncio.run(descargas.ofrecer(page, contenido, "respaldo-x.zip", "respaldo.zip",
                              "application/zip", "Tu respaldo", "texto",
                              al_descargar=lambda: avisado.append(True)))
check(falso.pedido["file_name"] == "respaldo-x.zip", "propone el nombre con fecha")
check(open(destino, "rb").read() == contenido, "y el archivo queda guardado entero")
check(avisado == [True], "y recien ahi se anota como hecho")

falso.ruta = None                       # la persona cancela
avisado.clear()
asyncio.run(descargas.ofrecer(page, contenido, "r.zip", "respaldo.zip",
                              "application/zip", "t", "x",
                              al_descargar=lambda: avisado.append(True)))
check(avisado == [], "si cancela, no se anota nada")


if descargas.PUEDE_ENLAZAR:
    print("\nDescargar: en la web, un enlace que se abre dentro del toque")
    web = Pagina()
    web.web = True
    subidos = []
    sub_real, enl_real = nube.subir_archivo, nube.enlace_de_descarga
    nube.subir_archivo = lambda n, d, t: subidos.append((n, d, t))
    nube.enlace_de_descarga = lambda n, v: f"https://enlace/{n}?download={v}"

    # `OpenUrl` busca en la pagina el servicio que abre enlaces. En la app esa
    # pagina existe; aca la pagina es de mentira, y se le presta uno.
    import flet.controls.services.url_launcher as lanzador

    class _ServicioDePrueba:
        _i = 1

    servicio_real = lanzador.shared_service
    lanzador.shared_service = lambda tipo: _ServicioDePrueba()
    try:
        avisado.clear()
        asyncio.run(descargas.ofrecer(web, contenido, "respaldo-x.zip",
                                      "respaldo.zip", "application/zip",
                                      "Tu respaldo está listo", "texto",
                                      al_descargar=lambda: avisado.append(True)))
    finally:
        nube.subir_archivo, nube.enlace_de_descarga = sub_real, enl_real
        lanzador.shared_service = servicio_real
    check(subidos == [("respaldo.zip", contenido, "application/zip")],
          "sube el archivo a la nube")
    ventana = next((c for c in web.overlay if isinstance(c, ft.AlertDialog)), None)
    check(ventana is not None, "y muestra la ventana para bajarlo")
    boton = next((b for b in (ventana.actions if ventana else [])
                  if getattr(b, "content", None) == "Descargar"), None)
    check(boton is not None and isinstance(boton.action, ft.OpenUrl),
          "el boton Descargar abre el enlace por su cuenta, dentro del toque")
    check(boton is not None and boton.action.url
          == "https://enlace/respaldo.zip?download=respaldo-x.zip",
          "el enlace es el del archivo recien subido")
    check(avisado == [], "todavia no se anota: falta que lo toque")
    if boton is not None:
        boton.on_click(None)
    check(avisado == [True], "al tocar Descargar se anota como hecho")


print("\nRestaurar: vuelve exactamente lo que habia")
from backend import perfil  # noqa: E402
perfil.guardar_nombre("Juan")


def foto_de_la_tienda():
    productos = bd.listar_productos()
    fotos_ = bd.listar_fotos(productos[0]["id"], con_datos=True) if productos else []
    return fotos_[0]["completa"] if fotos_ else None


def foto_de_la_tienda_y_estado():
    clientes = bd.listar_clientes()
    return {
        "productos": sorted((p["nombre"], float(p["stock"]), float(p["precio_usd"]))
                            for p in bd.listar_productos()),
        "saldo": bd.saldo_cliente(clientes[0]["id"]) if clientes else None,
        "vendido": bd.metricas("mes")["vendido"],
        "cobrado": bd.metricas("mes")["entro_en_caja"],
        "ventas": bd.contar_ventas(),
        "gastos": len(bd.listar_gastos()),
        "tasa": bd.leer_tasa(),
        "foto": foto_de_la_tienda(),
    }


antes = foto_de_la_tienda_y_estado()
guardado, _ = respaldo.armar()

# Se ensucia la cuenta: lo que se haga despues del respaldo se tiene que perder.
bd.eliminar_producto(cartera)
bd.crear_producto("Comprado despues", "", 1.0, 2.0, stock_inicial=9)
bd.guardar_tasa(700.0)
bd.crear_gasto("Publicidad", "", 8.0)
check(foto_de_la_tienda_y_estado() != antes, "la cuenta cambio despues del respaldo")

datos_r, cuantos_r, fecha_r = respaldo.revisar(guardado)
check(cuantos_r["productos"] == 1 and cuantos_r["ventas"] == 2 and fecha_r,
      "revisar dice que trae y de que fecha es, sin tocar nada")
check(bd.contar_productos() == 1 and bd.listar_productos()[0]["nombre"]
      == "Comprado despues", "revisar no toco la cuenta")

respaldo.restaurar(datos_r)
despues = foto_de_la_tienda_y_estado()
for clave in ("productos", "saldo", "vendido", "cobrado", "ventas", "gastos",
              "tasa"):
    check(despues[clave] == antes[clave],
          f"vuelve igual: {clave} ({despues[clave]} = {antes[clave]})")
check(despues["foto"] == antes["foto"] and despues["foto"] is not None,
      "la foto vuelve entera")
check(seguridad.verificar("472913"), "el PIN de la cuenta sigue sirviendo")
check(perfil.nombre() == "Juan", "y el nombre no cambia")

respaldo.restaurar(datos_r)
check(foto_de_la_tienda_y_estado() == despues,
      "restaurar dos veces el mismo archivo da lo mismo")

print("\nRestaurar en otra cuenta, con la original intacta")
# El caso de pasar los datos de prueba a la cuenta de la vendedora: los ids son
# unicos en todo el proyecto, asi que sin ids nuevos chocarian.
transporte_propio = nube.transporte
nube.transporte = otra
bd.olvidar_lo_leido()
try:
    respaldo.restaurar(datos_r)
    en_la_otra = [p["nombre"] for p in bd.listar_productos()]
    otra_saldo = bd.saldo_cliente(bd.listar_clientes()[0]["id"])
finally:
    nube.transporte = transporte_propio
    bd.olvidar_lo_leido()
check(en_la_otra == ["Cartera"],
      "la otra cuenta queda con lo del archivo, sin lo que tenia")
check(otra_saldo == antes["saldo"], "con las deudas bien enlazadas")
check([p["nombre"] for p in bd.listar_productos()] == ["Cartera"]
      and bd.saldo_cliente(bd.listar_clientes()[0]["id"]) == antes["saldo"],
      "y la cuenta original no se toco")

print("\nArchivos que no sirven")
for contenido_malo, motivo in [
    (b"esto no es un zip", "un archivo que no es zip"),
    (None, "un archivo vacio"),
]:
    try:
        respaldo.revisar(contenido_malo)
        check(False, f"rechaza {motivo}")
    except respaldo.ErrorDeRespaldo:
        check(True, f"rechaza {motivo}")


def zip_con(nombre, texto):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(nombre, texto)
    return b.getvalue()


for contenido_malo, motivo in [
    (zip_con("otra_cosa.txt", "hola"), "un zip que no trae datos.json"),
    (zip_con("datos.json", '{"version": 99}'), "un respaldo de una version futura"),
]:
    try:
        respaldo.revisar(contenido_malo)
        check(False, f"rechaza {motivo}")
    except respaldo.ErrorDeRespaldo:
        check(True, f"rechaza {motivo}")

print("\nTodo o nada")
import copy  # noqa: E402
roto = copy.deepcopy(datos_r)
roto["venta_lineas"][0]["producto_id"] = "00000000-0000-0000-0000-000000000000"
roto["productos"][0]["nombre"] = "No deberia quedar"
antes_roto = foto_de_la_tienda_y_estado()
try:
    respaldo.restaurar(roto)
    check(False, "un archivo con una referencia rota no se restaura")
except ValueError:
    check(True, "un archivo con una referencia rota no se restaura")
check(foto_de_la_tienda_y_estado() == antes_roto,
      "y la cuenta queda exactamente como estaba, sin nada a medias")

print("\nLa pantalla del respaldo")
import inspect  # noqa: E402
from frontend.vistas import configuracion_view  # noqa: E402


def todos(control):
    yield control
    for atributo in ("controls", "content"):
        v = getattr(control, atributo, None)
        for hijo in (v if isinstance(v, list) else [v] if v is not None else []):
            if hasattr(hijo, "__class__") and hijo.__class__.__module__.startswith("flet"):
                yield from todos(hijo)


pantalla_r = configuracion_view._respaldo(Pagina(), lambda: None)
restaurar_b = next((c for c in todos(pantalla_r) if isinstance(c, ft.TextButton)
                    and c.content == "Restaurar desde un archivo"), None)
check(restaurar_b is not None, "tiene el boton Restaurar desde un archivo")
if selector.ABRE_LA_PANTALLA:
    check(isinstance(restaurar_b.action, ft.PickFiles),
          "Flet 1.0: abre el explorador dentro del toque, como en el iPhone")
else:
    check(inspect.iscoroutinefunction(restaurar_b.on_click),
          "Flet 0.85: abre el explorador como antes")
bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
