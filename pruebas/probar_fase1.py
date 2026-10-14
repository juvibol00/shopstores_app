"""Ejercita la capa de datos de la Fase 1 contra una base temporal.

Se apunta FLET_APP_STORAGE_DATA a una carpeta descartable **antes** de importar
nada: los modulos calculan sus rutas al importarse.
"""
import io
import os
import shutil
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="shopstores_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from backend import almacenamiento
from backend import basedatos as bd
from backend import fotos
from backend import seguridad

fallos = []


def check(condicion, etiqueta):
    print(("  ok   " if condicion else "  FALLA") + f" {etiqueta}")
    if not condicion:
        fallos.append(etiqueta)


def imagen(w=2400, h=1800, formato="JPEG", calidad=92):
    im = Image.new("RGB", (w, h), "#A67C52")
    for x in range(0, w, 90):
        im.paste("#E3D5BF", (x, 0, x + 45, h))
    b = io.BytesIO()
    im.save(b, format=formato, quality=calidad)
    return b.getvalue()


print(f"base temporal: {TEMPORAL}\n")

print("PIN")
check(not seguridad.hay_pin(), "al principio no hay PIN")
for malo, motivo in [("123", "corto"), ("abcdef", "con letras"), ("", "vacio")]:
    try:
        seguridad.establecer(malo, malo)
        check(False, f"rechaza un PIN {motivo}")
    except seguridad.PinInvalido:
        check(True, f"rechaza un PIN {motivo}")
try:
    seguridad.establecer("130900", "130901")
    check(False, "rechaza cuando los dos no coinciden")
except seguridad.PinInvalido:
    check(True, "rechaza cuando los dos no coinciden")

seguridad.establecer("472913", "472913")
check(seguridad.hay_pin(), "queda establecido")
check(seguridad.verificar("472913"), "acepta el correcto")
check(not seguridad.verificar("472914"), "rechaza el incorrecto")
guardado = almacenamiento.obtener("pin")
check("472913" not in str(guardado), "el PIN NO queda guardado en claro")
check(len(guardado["huella"]) == 64 and len(guardado["sal"]) == 32,
      "guarda huella de 32 bytes y sal de 16")
check(seguridad.parece_debil("130900") is not None, "avisa que 130900 parece fecha")
check(seguridad.parece_debil("111111") is not None, "avisa digitos repetidos")
check(seguridad.parece_debil("123456") is not None, "avisa digitos corridos")
check(seguridad.parece_debil("472913") is None, "no molesta con uno razonable")

print("\nProductos")
pid = bd.crear_producto("Cartera de cuero", "Cuero natural, 30x22", 20.0, 45.0,
                        stock_inicial=10)
p = bd.obtener_producto(pid)
check(p["nombre"] == "Cartera de cuero", "se crea y se lee")
check(float(p["stock"]) == 10, "la existencia inicial queda en 10")
check(len(bd.movimientos(pid)) == 1, "la existencia inicial dejo su movimiento")
check(bd.movimientos(pid)[0]["motivo"] == "alta", "el movimiento es de tipo alta")
check(p["sincronizado_en"] is None, "nace pendiente de sincronizar")

bd.crear_producto("Pulsera tejida", "Hilo encerado", 3.0, 8.5, stock_inicial=0)
bd.crear_producto("Billetera", "Ocho ranuras", 12.0, 22.0, stock_inicial=4)
check(bd.contar_productos() == 3, "hay tres productos")
check(len(bd.listar_productos("puls")) == 1, "el buscador filtra por nombre")
check(len(bd.listar_productos("encerado")) == 1, "el buscador filtra por descripcion")
check(len(bd.listar_productos("zzz")) == 0, "no inventa resultados")

print("\nStock: movimientos relativos")
bd.reabastecer(pid, 5, costo_usd=22.0)
check(float(bd.obtener_producto(pid)["stock"]) == 15, "entrada de 5 -> 15")
check(float(bd.obtener_producto(pid)["costo_usd"]) == 22.0, "el costo nuevo reemplaza")
delta = bd.ajustar_stock(pid, 12)
check(delta == -3, "ajuste a 12 guarda la diferencia -3, no el total")
check(float(bd.obtener_producto(pid)["stock"]) == 12, "el resumen queda en 12")
sumados = sum(float(m["delta"]) for m in bd.movimientos(pid))
check(sumados == 12, "la suma de los movimientos coincide con el resumen")
check(bd.ajustar_stock(pid, 12) == 0, "ajustar al mismo total no hace nada")

# El resumen es cache: si se corrompe, se reconstruye desde los movimientos.
bd.conexion().execute("UPDATE productos SET stock = 999 WHERE id = ?", (pid,))
bd.conexion().commit()
check(bd.recalcular_stock(pid) == 12, "recalcular reconstruye desde los movimientos")

try:
    bd.reabastecer(pid, 0)
    check(False, "rechaza una entrada de cero")
except ValueError:
    check(True, "rechaza una entrada de cero")

print("\nFotos")
tamanos = fotos.preparar(imagen())
check(set(tamanos) == {"miniatura", "catalogo", "completa"}, "prepara los tres tamanos")
check(len(tamanos["miniatura"]) < len(tamanos["catalogo"]) < len(tamanos["completa"]),
      "cada tamano pesa mas que el anterior")
f1 = bd.guardar_foto(pid, tamanos)
f2 = bd.guardar_foto(pid, fotos.preparar(imagen(1200, 1600)))
f3 = bd.guardar_foto(pid, fotos.preparar(imagen(800, 800, "PNG")))
check(len(bd.listar_fotos(pid)) == 3, "entran tres fotos")
try:
    bd.guardar_foto(pid, tamanos)
    check(False, "la cuarta foto se rechaza")
except ValueError:
    check(True, "la cuarta foto se rechaza")

check([f["orden"] for f in bd.listar_fotos(pid)] == [1, 2, 3], "ordenes 1, 2 y 3")
bd.hacer_principal(f3)
ordenes = {f["id"]: f["orden"] for f in bd.listar_fotos(pid)}
check(ordenes[f3] == 1 and ordenes[f1] == 3, "hacer principal intercambia con la 1")
bd.eliminar_foto(f3)
check([f["orden"] for f in bd.listar_fotos(pid)] == [1, 2],
      "al borrar, los ordenes se cierran sin huecos")
check(bd.obtener_foto(f2, "completa")[:2] == b"\xff\xd8", "la completa es un JPEG")
check(bd.obtener_foto(f2, "miniatura") != bd.obtener_foto(f2, "completa"),
      "miniatura y completa son distintas")

fila_lista = [f for f in bd.listar_productos() if f["id"] == pid][0]
check(fila_lista["miniatura"] is not None, "la lista trae la miniatura de la principal")

print("\nBorrado logico")
otro = bd.crear_producto("Temporal", "", 1.0, 2.0)
bd.eliminar_producto(otro)
check(bd.contar_productos() == 3, "el borrado lo saca de la lista")
check(bd.obtener_producto(otro) is not None, "pero la fila sigue existiendo")
check(bd.obtener_producto(otro)["activo"] == 0, "marcada como inactiva")

print("\nResumen")
r = bd.resumen_inventario()
check(r["productos"] == 3, "cuenta 3 productos activos")
check(r["sin_stock"] == 1, "detecta el que no tiene existencia")
bd.actualizar_producto(pid, "Cartera de cuero", "", 50.0, 45.0, True)
check(bd.resumen_inventario()["bajo_costo"] == 1, "detecta precio por debajo del costo")
check(float(bd.obtener_producto(pid)["stock"]) == 12,
      "editar los datos NO toca el stock")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)

print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
