"""Ejercita la venta contra una base temporal."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="vanes_venta_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import basedatos as bd

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


bd.guardar_tasa(620.0)
cartera = bd.crear_producto("Cartera", "", 20.0, 45.0, stock_inicial=10)
pulsera = bd.crear_producto("Pulsera", "", 3.0, 8.5, stock_inicial=4)
vacio = bd.crear_producto("Agotado", "", 1.0, 2.0, stock_inicial=0)

print("Rechazos")
for items, tasa, motivo in [
    ([], 620.0, "carrito vacío"),
    ([{"producto_id": cartera, "cantidad": 1}], 0, "sin tasa cargada"),
    ([{"producto_id": cartera, "cantidad": 0}], 620.0, "cantidad cero"),
    ([{"producto_id": cartera, "cantidad": -2}], 620.0, "cantidad negativa"),
]:
    try:
        bd.registrar_venta(items, tasa)
        check(False, f"rechaza {motivo}")
    except ValueError:
        check(True, f"rechaza {motivo}")

try:
    bd.registrar_venta([{"producto_id": vacio, "cantidad": 1}], 620.0)
    check(False, "rechaza vender sin existencia")
except bd.SinExistencia as ex:
    check("Agotado" in str(ex), "rechaza vender sin existencia y nombra el producto")

try:
    bd.registrar_venta([{"producto_id": cartera, "cantidad": 11}], 620.0)
    check(False, "rechaza vender más de lo que hay")
except bd.SinExistencia as ex:
    check("quedan 10" in str(ex), "rechaza pedir 11 de 10 y dice cuántas quedan")

check(bd.resumen_de_hoy()["ventas"] == 0, "ningún rechazo dejó una venta a medias")
check(float(bd.obtener_producto(cartera)["stock"]) == 10, "ni tocó el stock")

print("\nVenta correcta")
v = bd.registrar_venta([{"producto_id": cartera, "cantidad": 2},
                        {"producto_id": pulsera, "cantidad": 3}], 620.0)
check(v["correlativo"] == 1, "el primer correlativo es 1")
check(abs(v["total_usd"] - (2 * 45.0 + 3 * 8.5)) < 0.001, "el total suma 115.50")
check(float(bd.obtener_producto(cartera)["stock"]) == 8, "descontó 2 carteras")
check(float(bd.obtener_producto(pulsera)["stock"]) == 1, "descontó 3 pulseras")

venta, lineas = bd.obtener_venta(v["id"])
check(len(lineas) == 2, "guardó las dos líneas")
check(float(venta["tasa_usada"]) == 620.0, "congeló la tasa")
linea_cartera = [l for l in lineas if l["producto_id"] == cartera][0]
check(float(linea_cartera["costo_unit_usd"]) == 20.0, "congeló el costo")
check(linea_cartera["nombre_congelado"] == "Cartera", "congeló el nombre")

print("\nLo congelado no se mueve al cambiar el producto")
bd.actualizar_producto(cartera, "Cartera premium", "", 33.0, 60.0, True)
bd.guardar_tasa(700.0)
_, lineas = bd.obtener_venta(v["id"])
l = [x for x in lineas if x["producto_id"] == cartera][0]
check(float(l["costo_unit_usd"]) == 20.0, "el costo de la venta vieja sigue en 20")
check(float(l["precio_unit_usd"]) == 45.0, "el precio sigue en 45")
check(l["nombre_congelado"] == "Cartera", "el nombre sigue siendo el de entonces")
venta, _ = bd.obtener_venta(v["id"])
check(float(venta["tasa_usada"]) == 620.0, "la tasa de la venta vieja no cambió")

print("\nEl mismo producto dos veces en el carrito")
v2 = bd.registrar_venta([{"producto_id": pulsera, "cantidad": 0.5},
                         {"producto_id": pulsera, "cantidad": 0.5}], 700.0)
check(v2["correlativo"] == 2, "el correlativo avanza a 2")
check(float(bd.obtener_producto(pulsera)["stock"]) == 0, "se sumaron y descontó 1")
try:
    bd.registrar_venta([{"producto_id": cartera, "cantidad": 5},
                        {"producto_id": cartera, "cantidad": 5}], 700.0)
    check(False, "suma los repetidos antes de comprobar la existencia")
except bd.SinExistencia:
    check(True, "suma los repetidos antes de comprobar la existencia")

print("\nTodo o nada")
antes_stock = float(bd.obtener_producto(cartera)["stock"])
antes_ventas = bd.resumen_de_hoy()["ventas"]
try:
    # La primera línea entra, la segunda no: no debe quedar nada.
    bd.registrar_venta([{"producto_id": cartera, "cantidad": 1},
                        {"producto_id": vacio, "cantidad": 1}], 700.0)
except bd.SinExistencia:
    pass
check(float(bd.obtener_producto(cartera)["stock"]) == antes_stock,
      "una venta fallida no descuenta la parte que sí alcanzaba")
check(bd.resumen_de_hoy()["ventas"] == antes_ventas, "ni deja la cabecera escrita")
check(len(bd.obtener_venta("no-existe")[1]) == 0, "pedir una venta inexistente no revienta")

print("\nResumen del día")
r = bd.resumen_de_hoy()
check(r["ventas"] == 2, "cuenta las dos ventas")
check(abs(float(r["ingreso"]) - (115.50 + 8.5)) < 0.001, "suma el ingreso del día")
check(len(bd.ventas_de_hoy()) == 2, "las lista")

print("\nAnular")
stock_previo = float(bd.obtener_producto(cartera)["stock"])
bd.anular_venta(v["id"])
check(float(bd.obtener_producto(cartera)["stock"]) == stock_previo + 2,
      "la mercancía vuelve al inventario")
check(bd.obtener_venta(v["id"])[0]["estado"] == "anulada", "queda marcada como anulada")
check(bd.resumen_de_hoy()["ventas"] == 1, "sale del resumen del día")
check(len(bd.obtener_venta(v["id"])[1]) == 2, "pero las líneas siguen ahí")
movs = [m for m in bd.movimientos(cartera) if m["referencia_id"] == v["id"]]
check(len(movs) == 2, "quedan los dos movimientos: la salida y la devolución")
try:
    bd.anular_venta(v["id"])
    check(False, "no se puede anular dos veces")
except ValueError:
    check(True, "no se puede anular dos veces")
try:
    bd.anular_venta("no-existe")
    check(False, "anular una venta inexistente falla con mensaje")
except ValueError:
    check(True, "anular una venta inexistente falla con mensaje")

suma = sum(float(m["delta"]) for m in bd.movimientos(cartera, limite=999))
check(abs(suma - float(bd.obtener_producto(cartera)["stock"])) < 1e-9,
      "los movimientos siguen cuadrando con el stock")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
