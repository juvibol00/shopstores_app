"""El respaldo: toda la base en un archivo, y de vuelta.

Lo que se prueba no es que el archivo se escriba, sino lo que de verdad duele si
falla: que la copia traiga **lo ultimo** que se guardo —la base trabaja en modo
WAL y copiarla a mano se deja las ultimas ventas afuera—, que un archivo que no es
nuestro se rechace **antes** de tocar nada, y que al restaurar vuelva exactamente
lo que habia.
"""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="shopstores_respaldo_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from backend import almacenamiento
from backend import basedatos as bd
from backend import correo
from backend import fotos
from backend import respaldo
from backend import seguridad

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
cartera = bd.crear_producto("Cartera de cuero", "Cuero natural", 20.0, 45.0,
                            stock_inicial=5)
bd.guardar_foto(cartera, fotos.preparar(imagen()))
cliente = bd.crear_cliente("Ana Pérez", "0412-1234567", "")
metodos = bd.listar_metodos()
bd.registrar_venta([{"producto_id": cartera, "cantidad": 2}], 620.0,
                   pagos=[{"metodo_id": metodos[0]["id"], "monto": 90.0}])

copia = respaldo.armar()
check(copia[:16] == b"SQLite format 3\x00", "sale una base de datos de verdad")
check(len(copia) > 10_000, f"y pesa lo que debe ({len(copia) / 1024:.0f} KB)")

# El punto fino: la venta se acaba de registrar y en modo WAL puede estar todavia
# en el archivo de al lado. Si el respaldo se hiciera copiando el archivo
# principal a mano, esa venta NO estaria.
resumen = respaldo.revisar(copia)
check(resumen["ventas"] == 1, "la copia trae la venta recien hecha")
check(resumen["productos"] == 1 and resumen["clientes"] == 1,
      "y el producto y el cliente")

print("\nEl nombre del archivo")
from datetime import datetime, timezone, timedelta
nombre = respaldo.nombre_sugerido(
    datetime(2026, 10, 9, 23, 30, tzinfo=timezone(timedelta(hours=-4))))
check(nombre == "respaldo-shopstores-2026-10-09.db",
      f"lleva la fecha local, no la de UTC ({nombre})")

print("\nLo que NO se acepta")
for malo, motivo in [
    (b"", "un archivo vacío"),
    (b"esto no es una base de datos", "un archivo cualquiera"),
    (b"SQLite format 3\x00" + b"\x00" * 200, "una base sin nuestras tablas"),
]:
    try:
        respaldo.revisar(malo)
        check(False, f"rechaza {motivo}")
    except respaldo.ErrorDeRespaldo:
        check(True, f"rechaza {motivo}")

# Una base de SQLite legitima pero de otro programa.
import sqlite3
ajena = os.path.join(TEMPORAL, "ajena.db")
c = sqlite3.connect(ajena)
c.execute("CREATE TABLE cosas (id INTEGER)")
c.commit()
c.close()
try:
    respaldo.revisar(open(ajena, "rb").read())
    check(False, "rechaza una base de otro programa")
except respaldo.ErrorDeRespaldo:
    check(True, "rechaza una base de otro programa")

print("\nRestaurar")
# Se cambia todo despues de hacer la copia, para ver que de verdad vuelve atras.
bd.crear_producto("Producto de después", "", 1.0, 2.0, stock_inicial=1)
bd.crear_cliente("Cliente de después", "", "")
check(bd.contar_productos() == 2, "antes de restaurar hay 2 productos")

vuelto = respaldo.restaurar(copia)
check(vuelto["productos"] == 1, "restaurar dice cuántos productos trae")
check(bd.contar_productos() == 1, "y la base vuelve a tener 1")
check([c["nombre"] for c in bd.listar_clientes()] == ["Ana Pérez"],
      "el cliente de después desapareció")
check(bd.contar_ventas() == 1, "la venta sigue ahí")
check(len(bd.listar_fotos(bd.listar_productos()[0]["id"])) == 1,
      "y la foto del producto también: viaja dentro de la base")

# La base anterior se guarda al lado, por si el archivo elegido era el viejo.
check(os.path.exists(almacenamiento.RUTA_BASE_DATOS + ".anterior"),
      "la base que había queda guardada como .anterior")

print("\nEl correo del respaldo")
correo.guardar_configuracion("tienda@gmail.com", "abcdefghijklmnop", "")
mensaje = correo.armar_mensaje(
    "tienda@gmail.com", "tienda@gmail.com", "Respaldo", copia,
    "respaldo-shopstores-2026-10-09.db", cuerpo="Adjunto va el respaldo.",
    tipo="octet-stream")
tipos = [p.get_content_type() for p in mensaje.walk()]
check("application/octet-stream" in tipos,
      "el adjunto NO va como PDF: es una base de datos")
adjuntos = [p for p in mensaje.walk()
            if p.get_filename() == "respaldo-shopstores-2026-10-09.db"]
check(len(adjuntos) == 1, "y viaja con el nombre que lleva la fecha")
check(adjuntos[0].get_payload(decode=True) == copia,
      "el archivo llega entero, byte por byte")

print()
print("Heredar la base con el nombre viejo")
# Error real: al renombrar la aplicacion se cambio el nombre del archivo de la
# base, y al abrir no encontro nada y empezo de cero. Los datos estaban al lado,
# en el archivo viejo, pero en pantalla se veia igual que haberlos perdido.
viejo = os.path.join(TEMPORAL, "vanesstore.db")
nuevo = os.path.join(TEMPORAL, "heredada.db")
almacenamiento._NOMBRE_ANTERIOR = viejo
almacenamiento.RUTA_BASE_DATOS = nuevo

open(viejo, "wb").write(copia)
almacenamiento._heredar_la_base_vieja()
check(os.path.exists(nuevo) and not os.path.exists(viejo),
      "una base con el nombre anterior se adopta con el nombre nuevo")
check(open(nuevo, "rb").read() == copia, "y llega entera")

# Si ya hay una con el nombre nuevo no se pisa: aunque este vacia, es la que la
# persona esta usando, y pisarla seria peor que no hacer nada.
open(viejo, "wb").write(b"la vieja")
open(nuevo, "wb").write(b"la que vale")
almacenamiento._heredar_la_base_vieja()
check(open(nuevo, "rb").read() == b"la que vale",
      "y si ya hay una con el nombre nuevo, NO se pisa")
check(os.path.exists(viejo), "la vieja se queda donde esta, sin borrarse")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
