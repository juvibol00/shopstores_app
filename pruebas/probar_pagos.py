"""Métodos de pago y reparto del total."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="vanes_pagos_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import basedatos as bd

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


TASA = 620.0
bd.guardar_tasa(TASA)
prod = bd.crear_producto("Cartera", "", 20.0, 45.0, stock_inicial=100)

print("La lista de métodos")
metodos = bd.listar_metodos()
check(len(metodos) == 5, "arranca con los cinco de siempre")
por_nombre = {m["nombre"]: m for m in metodos}
check(por_nombre["Pago móvil"]["moneda"] == "Bs", "pago móvil es en bolívares")
check(por_nombre["Zelle"]["moneda"] == "USD", "Zelle es en dólares")

nuevo = bd.crear_metodo("Binance", "USD")
check(len(bd.listar_metodos()) == 6, "se puede agregar uno")
for nombre, motivo in [("", "sin nombre"), ("   ", "solo espacios")]:
    try:
        bd.crear_metodo(nombre, "USD"); check(False, f"rechaza {motivo}")
    except ValueError: check(True, f"rechaza {motivo}")
try:
    bd.crear_metodo("Otro", "EUR"); check(False, "rechaza una moneda desconocida")
except ValueError: check(True, "rechaza una moneda desconocida")
try:
    bd.crear_metodo("binance", "USD"); check(False, "rechaza un nombre repetido")
except ValueError: check(True, "rechaza un nombre repetido aunque cambie la caja")

bd.actualizar_metodo(nuevo, "Binance USDT", "USD")
check(bd.obtener_metodo(nuevo)["nombre"] == "Binance USDT", "se puede renombrar")
bd.desactivar_metodo(nuevo)
check(len(bd.listar_metodos()) == 5, "desactivar lo saca de la lista")
check(bd.obtener_metodo(nuevo) is not None, "pero la fila sigue existiendo")

efectivo_usd = por_nombre["Efectivo en dólares"]["id"]
pago_movil = por_nombre["Pago móvil"]["id"]

print("\nEl reparto tiene que cuadrar")
# Una cartera = $45. En bolívares serían 27.900.
for pagos, motivo in [
    ([{"metodo_id": efectivo_usd, "monto": 40}], "faltan $5"),
    ([{"metodo_id": efectivo_usd, "monto": 60}], "sobran $15"),
    ([{"metodo_id": efectivo_usd, "monto": 20},
      {"metodo_id": pago_movil, "monto": 10000}], "el mixto no llega"),
    ([{"metodo_id": efectivo_usd, "monto": 0}], "un pago en cero"),
    ([{"metodo_id": "no-existe", "monto": 45}], "un método inexistente"),
]:
    try:
        bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA, pagos=pagos)
        check(False, f"rechaza cuando {motivo}")
    except bd.PagoNoCuadra:
        check(True, f"rechaza cuando {motivo}")

check(bd.resumen_de_hoy()["ventas"] == 0, "ningún rechazo dejó venta escrita")
check(float(bd.obtener_producto(prod)["stock"]) == 100, "ni descontó stock")

print("\nPago simple")
v = bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA,
                       pagos=[{"metodo_id": efectivo_usd, "monto": 45}])
pagos = bd.pagos_de_venta(v["id"])
check(len(pagos) == 1, "guarda un pago")
check(pagos[0]["metodo_nombre"] == "Efectivo en dólares", "congela el nombre del método")
check(abs(float(pagos[0]["monto_usd"]) - 45.0) < 0.001, "y su equivalente en dólares")

print("\nPago mixto")
# $45 = $20 en efectivo + 15.500 Bs (que a 620 son exactamente $25).
v2 = bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA,
                        pagos=[{"metodo_id": efectivo_usd, "monto": 20},
                               {"metodo_id": pago_movil, "monto": 15500}])
pagos = bd.pagos_de_venta(v2["id"])
check(len(pagos) == 2, "guarda los dos pagos")
suma = sum(float(p["monto_usd"]) for p in pagos)
check(abs(suma - 45.0) < 0.001, "los dos suman exactamente el total")
bs = [p for p in pagos if p["moneda"] == "Bs"][0]
check(float(bs["monto"]) == 15500, "el pago en bolívares guarda los bolívares")
check(abs(float(bs["monto_usd"]) - 25.0) < 0.001, "y también su equivalente")

print("\nCentavos: el redondeo no debe descuadrar")
# 3 carteras = $135. Repartido en tres pagos en bolívares de 27.900 cada uno.
v3 = bd.registrar_venta([{"producto_id": prod, "cantidad": 3}], TASA,
                        pagos=[{"metodo_id": pago_movil, "monto": 27900}] * 3)
pagos = bd.pagos_de_venta(v3["id"])
suma = round(sum(float(p["monto_usd"]) for p in pagos), 2)
venta, _ = bd.obtener_venta(v3["id"])
check(suma == float(venta["total_usd"]),
      f"los pagos suman exactamente el total ({suma} = {venta['total_usd']})")

# Un caso que sí produce fracción: 3 unidades a $45 pagadas con 83.700 Bs.
v4 = bd.registrar_venta([{"producto_id": prod, "cantidad": 3}], TASA,
                        pagos=[{"metodo_id": pago_movil, "monto": 41850},
                               {"metodo_id": pago_movil, "monto": 41850}])
pagos = bd.pagos_de_venta(v4["id"])
venta, _ = bd.obtener_venta(v4["id"])
check(round(sum(float(p["monto_usd"]) for p in pagos), 2) == float(venta["total_usd"]),
      "y también cuando la división da fracciones de centavo")

print("\nEl método renombrado no cambia el historial")
bd.actualizar_metodo(pago_movil, "Pago móvil Banesco", "Bs")
pagos = bd.pagos_de_venta(v2["id"])
bs = [p for p in pagos if p["moneda"] == "Bs"][0]
check(bs["metodo_nombre"] == "Pago móvil", "la venta vieja conserva el nombre anterior")

print("\nDesglose del día")
desglose = {d["metodo_nombre"]: d for d in bd.desglose_de_hoy()}
check("Efectivo en dólares" in desglose, "aparece el efectivo")
check(abs(float(desglose["Efectivo en dólares"]["monto_usd"]) - 65.0) < 0.01,
      "suma los $45 + $20 de efectivo")
check(float(desglose["Pago móvil"]["monto"]) == 15500 + 27900 * 3 + 41850 * 2,
      "y los bolívares se suman como bolívares, sin convertir")

print("\nNo se puede quedar sin métodos")
for m in bd.listar_metodos()[1:]:
    bd.desactivar_metodo(m["id"])
check(len(bd.listar_metodos()) == 1, "quedó uno solo")
try:
    bd.desactivar_metodo(bd.listar_metodos()[0]["id"])
    check(False, "no deja borrar el último")
except ValueError:
    check(True, "no deja borrar el último")

print("\nVenta sin detalle de pago")
v5 = bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA)
check(bd.pagos_de_venta(v5["id"]) == [], "se permite y no guarda reparto")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
