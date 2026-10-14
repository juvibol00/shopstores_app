"""Clientes, ventas a crédito y reparto de abonos."""
import io
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="shopstores_cobros_")
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
prod = bd.crear_producto("Cartera", "", 20.0, 50.0, stock_inicial=1000)
HOY = date.today()


def vender_credito(cliente, unidades, dia_vencimiento):
    return bd.registrar_venta(
        [{"producto_id": prod, "cantidad": unidades}], TASA, tipo="credito",
        cliente_id=cliente, fecha_pago_prevista=dia_vencimiento.isoformat())


print("Clientes")
maria = bd.crear_cliente("María Rodríguez", "0412-1234567")
luis = bd.crear_cliente("Luis Pérez")
check(len(bd.listar_clientes()) == 2, "se crean y se listan")
check(len(bd.listar_clientes("maría")) == 1, "el buscador filtra por nombre")
check(len(bd.listar_clientes("0412")) == 1, "y por teléfono")
for malo in ("", "   "):
    try:
        bd.crear_cliente(malo); check(False, "rechaza un cliente sin nombre")
    except ValueError: check(True, "rechaza un cliente sin nombre")

print("\nVenta a crédito")
try:
    bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA, tipo="credito")
    check(False, "una venta a crédito sin cliente se rechaza")
except ValueError:
    check(True, "una venta a crédito sin cliente se rechaza")

# Tres facturas de María: $100 vencida, $50 para dentro de 3 días, $200 sin fecha.
f1 = vender_credito(maria, 2, HOY - timedelta(days=4))     # $100
f2 = vender_credito(maria, 1, HOY + timedelta(days=3))     # $50
f3 = bd.registrar_venta([{"producto_id": prod, "cantidad": 4}], TASA,
                        tipo="credito", cliente_id=maria)  # $200, sin fecha
check(abs(bd.saldo_cliente(maria) - 350.0) < 0.01, "el saldo suma las tres: $350")
check(len(bd.facturas_pendientes(maria)) == 3, "las tres están pendientes")
check([f["correlativo"] for f in bd.facturas_pendientes(maria)] == [1, 2, 3],
      "salen de la más vieja a la más nueva")
check(bd.saldo_cliente(luis) == 0, "Luis no debe nada")

print("\nRechazos del abono")
for monto, moneda, tasa, motivo in [
    (0, "USD", TASA, "monto cero"),
    (-10, "USD", TASA, "monto negativo"),
    (500, "USD", TASA, "más de lo que debe"),
    (1000, "Bs", 0, "bolívares sin tasa"),
    (10, "EUR", TASA, "moneda desconocida"),
]:
    try:
        bd.registrar_abono(maria, monto, moneda, tasa)
        check(False, f"rechaza {motivo}")
    except ValueError:
        check(True, f"rechaza {motivo}")
try:
    bd.registrar_abono(luis, 10, "USD", TASA)
    check(False, "rechaza abonar a quien no debe")
except ValueError:
    check(True, "rechaza abonar a quien no debe")
check(abs(bd.saldo_cliente(maria) - 350.0) < 0.01, "ningún rechazo movió el saldo")
check(len(bd.abonos_de_cliente(maria)) == 0, "ni dejó un abono escrito")

print("\nAbono que salda la más vieja y sobra")
r = bd.registrar_abono(maria, 120, "USD", TASA)
check(abs(bd.saldo_cliente(maria) - 230.0) < 0.01, "el saldo baja a $230")
check(len(r["aplicadas"]) == 2, "se repartió entre dos facturas")
check(r["aplicadas"][0]["correlativo"] == 1 and r["aplicadas"][0]["saldada"],
      "la primera factura queda saldada")
check(abs(r["aplicadas"][1]["monto"] - 20.0) < 0.01,
      "los $20 que sobran van a la siguiente")
check(len(bd.facturas_pendientes(maria)) == 2, "quedan dos facturas abiertas")
check(bd.facturas_pendientes(maria)[0]["correlativo"] == 2,
      "la más vieja abierta es ahora la segunda")
check(abs(float(bd.facturas_pendientes(maria)[0]["restante"]) - 30.0) < 0.01,
      "a la segunda le quedan $30")

print("\nAbono en bolívares")
# 18.600 Bs a 620 son exactamente $30: debería saldar la segunda factura.
r = bd.registrar_abono(maria, 18600, "Bs", TASA)
check(abs(r["monto_usd"] - 30.0) < 0.01, "18.600 Bs se convierten a $30")
check(len(bd.facturas_pendientes(maria)) == 1, "salda la segunda factura")
abono = bd.abonos_de_cliente(maria)[0]
check(float(abono["monto_recibido"]) == 18600, "guarda los bolívares recibidos")
check(abono["moneda_recibida"] == "Bs", "y en qué moneda entraron")
check(float(abono["tasa_usada"]) == TASA, "y la tasa con la que se convirtió")

print("\nPagar todo lo que queda")
saldo = bd.saldo_cliente(maria)
check(abs(saldo - 200.0) < 0.01, "queda debiendo $200")
r = bd.registrar_abono(maria, saldo, "USD", TASA)
check(bd.saldo_cliente(maria) == 0, "el saldo queda en cero")
check(len(bd.facturas_pendientes(maria)) == 0, "no queda ninguna factura abierta")
check(r["saldo_restante"] == 0, "y el abono lo reporta")

print("\nLos centavos no dejan facturas fantasma")
otro = bd.crear_cliente("Centavos")
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA,
                   tipo="credito", cliente_id=otro)   # $50
# 31.000 Bs a 620 son exactamente $50, pero la división deja resto binario.
bd.registrar_abono(otro, 31000, "Bs", TASA)
check(bd.facturas_pendientes(otro) == [], "una factura pagada al centavo queda cerrada")
check(bd.saldo_cliente(otro) == 0, "y el saldo en cero limpio")

print("\nSe pasa por centavos: se ajusta en vez de dejar saldo negativo")
tercero = bd.crear_cliente("Ajuste")
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA,
                   tipo="credito", cliente_id=tercero)   # $50
r = bd.registrar_abono(tercero, 50.009, "USD", TASA)
check(abs(r["monto_usd"] - 50.0) < 0.005, "el abono se recorta al restante exacto")
check(bd.saldo_cliente(tercero) == 0, "el saldo no queda negativo")

print("\nLista de cobros ordenada por vencimiento")
ana = bd.crear_cliente("Ana")
vender_credito(ana, 1, HOY + timedelta(days=10))
beto = bd.crear_cliente("Beto")
vender_credito(beto, 1, HOY - timedelta(days=2))
carla = bd.crear_cliente("Carla")
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], TASA,
                   tipo="credito", cliente_id=carla)     # sin fecha
nombres = [c["nombre"] for c in bd.clientes_con_saldo()]
check(nombres[0] == "Beto", "lo vencido va primero")
check(nombres[-1] == "Carla", "lo que no tiene fecha va al final")
check("María Rodríguez" not in nombres, "quien ya pagó no aparece")

vencidos, proximos = bd.avisos_de_cobro(dias_aviso=7)
check([v[0]["nombre"] for v in vencidos] == ["Beto"], "el aviso detecta el vencido")
check(vencidos[0][1] == 2, "y dice que venció hace 2 días")
check([p[0]["nombre"] for p in proximos] == [], "Ana vence en 10 días: todavía no avisa")
vencidos, proximos = bd.avisos_de_cobro(dias_aviso=15)
check([p[0]["nombre"] for p in proximos] == ["Ana"], "con 15 días de aviso sí aparece")

print("\nProtecciones")
try:
    bd.eliminar_cliente(beto)
    check(False, "no deja borrar un cliente que debe")
except ValueError:
    check(True, "no deja borrar un cliente que debe")
bd.eliminar_cliente(maria)
check(bd.obtener_cliente(maria)["activo"] == 0, "sí deja borrar a quien ya pagó")

try:
    bd.anular_venta(f2["id"])
    check(False, "no deja anular una factura con abonos aplicados")
except ValueError as ex:
    check("abonados" in str(ex), "no deja anular una factura con abonos aplicados")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
