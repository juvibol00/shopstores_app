"""Gastos y métricas."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="vanes_metricas_")
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
efectivo = [m for m in bd.listar_metodos() if m["moneda"] == "USD"][0]["id"]

# Cartera: cuesta $20, se vende a $50 -> $30 de ganancia por unidad.
cartera = bd.crear_producto("Cartera", "", 20.0, 50.0, stock_inicial=100)
# Pulsera: cuesta $3, se vende a $10 -> $7 por unidad.
pulsera = bd.crear_producto("Pulsera", "", 3.0, 10.0, stock_inicial=100)
sin_costo = bd.crear_producto("Sin costo", "", 0.0, 15.0, stock_inicial=10)

print("Gastos")
for datos, motivo in [
    (("", "", 10, "USD", TASA), "sin categoría"),
    (("Delivery", "", 0, "USD", TASA), "monto cero"),
    (("Delivery", "", -5, "USD", TASA), "monto negativo"),
    (("Delivery", "", 1000, "Bs", 0), "bolívares sin tasa"),
    (("Delivery", "", 10, "EUR", TASA), "moneda desconocida"),
]:
    try:
        bd.crear_gasto(*datos); check(False, f"rechaza {motivo}")
    except ValueError: check(True, f"rechaza {motivo}")

g1 = bd.crear_gasto("Delivery", "Moto del lunes", 12.0, "USD")
g2 = bd.crear_gasto("Empaques", "Cajas y papel", 6200, "Bs", TASA)
g3 = bd.crear_gasto("Delivery", "Moto del martes", 8.0, "USD")
check(len(bd.listar_gastos()) == 3, "se guardan los tres")
gasto_bs = [g for g in bd.listar_gastos() if g["moneda_pagada"] == "Bs"][0]
check(abs(float(gasto_bs["monto_usd"]) - 10.0) < 0.01, "6.200 Bs se convierten a $10")
check(float(gasto_bs["monto_pagado"]) == 6200, "y guarda los bolívares que salieron")

por_cat = {c["categoria"]: c for c in bd.gastos_por_categoria("hoy")}
check(abs(float(por_cat["Delivery"]["total"]) - 20.0) < 0.01, "agrupa los dos delivery")
check(por_cat["Delivery"]["veces"] == 2, "y cuenta las veces")

bd.eliminar_gasto(g3)
check(len(bd.listar_gastos()) == 2, "el borrado lo saca de la lista")
check(abs(float(bd.gastos_por_categoria("hoy")[0]["total"]) - 12.0) < 0.01,
      "y deja de sumar en las métricas")

check("Delivery" in bd.categorias_de_gasto(), "las categorías usadas se pueden sugerir")

print("\nLa cascada")
# 2 carteras ($100, cuestan $40) + 3 pulseras ($30, cuestan $9) = $130 vendido,
# $49 de costo, $81 de ganancia bruta. Menos $22 de gastos = $59 netos.
bd.registrar_venta([{"producto_id": cartera, "cantidad": 2},
                    {"producto_id": pulsera, "cantidad": 3}], TASA,
                   pagos=[{"metodo_id": efectivo, "monto": 130}])
m = bd.metricas("hoy")
check(m["ventas"] == 1, "cuenta una venta")
check(m["vendido"] == 130.0, "vendido $130")
check(m["costo"] == 49.0, "costo de lo vendido $49")
check(m["bruta"] == 81.0, "ganancia bruta $81")
check(m["gastos"] == 22.0, "gastos $22")
check(m["neta"] == 59.0, "ganancia neta $59")
check(abs(m["margen"] - 45.4) < 0.1, "margen 45,4 %")
check(m["sin_costo"] == 1, "avisa del producto sin costo cargado")

print("\nLo vendido no es lo cobrado")
cliente = bd.crear_cliente("A crédito")
bd.registrar_venta([{"producto_id": cartera, "cantidad": 1}], TASA,
                   tipo="credito", cliente_id=cliente)
m = bd.metricas("hoy")
check(m["vendido"] == 180.0, "la venta a crédito suma a lo vendido")
check(m["costo"] == 69.0, "y su costo también")
check(m["entro_en_caja"] == 130.0, "pero no entró en caja")
bd.registrar_abono(cliente, 20, "USD", TASA)
check(bd.metricas("hoy")["entro_en_caja"] == 150.0, "el abono sí entra en caja")
check(bd.metricas("hoy")["vendido"] == 180.0, "y no vuelve a sumar a lo vendido")

print("\nUna venta anulada no cuenta")
v = bd.registrar_venta([{"producto_id": pulsera, "cantidad": 5}], TASA,
                       pagos=[{"metodo_id": efectivo, "monto": 50}])
check(bd.metricas("hoy")["vendido"] == 230.0, "mientras está activa, suma")
bd.anular_venta(v["id"])
m = bd.metricas("hoy")
check(m["vendido"] == 180.0, "anulada, deja de sumar a lo vendido")
check(m["costo"] == 69.0, "y su costo también sale")

print("\nTop de productos")
top = bd.top_productos("hoy")
check(top[0]["nombre"] == "Cartera", "la cartera encabeza")
check(float(top[0]["vendido"]) == 150.0, "vendió $150 en carteras")
check(float(top[0]["ganancia"]) == 90.0, "con $90 de ganancia")
check(len(top) == 2, "solo aparecen los dos que se vendieron")
check(all(t["nombre"] != "Pulsera" or float(t["unidades"]) == 3 for t in top),
      "la anulada no infla las unidades de la pulsera")

print("\nPeriodos")
for periodo in ("hoy", "semana", "mes"):
    desde, hasta, etiqueta = bd.rango(periodo)
    check(desde < hasta, f"el rango de «{periodo}» tiene principio y fin")
check(bd.rango("hoy")[0] >= bd.rango("semana")[0], "hoy empieza después que la semana")
# La semana PUEDE empezar antes que el mes: si hoy es 5 de septiembre y cae sábado,
# la semana arrancó el lunes 31 de agosto. Lo que sí tiene que cumplirse siempre es
# que ningún periodo empiece después de hoy ni termine antes.
_hoy_utc = bd._a_utc(bd.datetime.now().astimezone().date())
check(all(bd.rango(p)[0] <= _hoy_utc for p in bd.PERIODOS),
      "ningún periodo empieza después de hoy")
check(all(bd.rango(p)[1] > _hoy_utc for p in bd.PERIODOS),
      "y todos llegan hasta el final del día")
try:
    bd.rango("año"); check(False, "rechaza un periodo desconocido")
except ValueError: check(True, "rechaza un periodo desconocido")
check(bd.metricas("mes")["vendido"] == 180.0, "el mes incluye lo de hoy")

print("\nSerie diaria")
serie = bd.serie_diaria("semana")
check(len(serie) >= 1, "devuelve al menos el día de hoy")
check(all("vendido" in d and "costo" in d and "ganancia" in d for d in serie),
      "cada día trae vendido, costo y ganancia")
check(abs(sum(d["vendido"] for d in serie) - 180.0) < 0.01,
      "la serie suma lo mismo que las métricas")
check(all(abs(d["ganancia"] - (d["vendido"] - d["costo"])) < 0.01 for d in serie),
      "la ganancia de cada día cierra")
# Una venta de la tarde: en Venezuela (UTC-4) su fecha UTC cae en el día
# siguiente. Antes esto la sacaba del gráfico, porque se agrupaba por día UTC y
# se buscaba por día local.
_tarde = bd.datetime.combine(bd.datetime.now().astimezone().date(),
                             bd.datetime.min.time().replace(hour=23)).astimezone()
_v = bd.registrar_venta([{"producto_id": cartera, "cantidad": 1}], TASA,
                        pagos=[{"metodo_id": efectivo, "monto": 50}])
bd.conexion().execute("UPDATE ventas SET fecha = ? WHERE id = ?",
                      (_tarde.astimezone(bd.timezone.utc).isoformat(
                          timespec="milliseconds"), _v["id"]))
bd.conexion().commit()
_serie = bd.serie_diaria("semana")
_hoy_local = bd.datetime.now().astimezone().date()
_dia = [d for d in _serie if d["dia"] == _hoy_local]
check(len(_dia) == 1 and _dia[0]["vendido"] >= 50.0,
      "una venta de las 23:00 local aparece en el día local, no en el UTC")
check(abs(sum(d["vendido"] for d in _serie)
          - bd.metricas("semana")["vendido"]) < 0.01,
      "y la serie sigue cuadrando con las métricas")

vacios = [d for d in serie if d["vendido"] == 0]
check(len(serie) == (bd.datetime.now().astimezone().date()
                     - bd.datetime.fromisoformat(bd.rango("semana")[0])
                     .astimezone().date()).days + 1,
      "rellena los días sin ventas")

print("\nSin datos no revienta")
vacio = tempfile.mkdtemp(prefix="vanes_vacio_")
bd.cerrar()
os.environ["FLET_APP_STORAGE_DATA"] = vacio
import importlib
from backend import almacenamiento
importlib.reload(almacenamiento)
importlib.reload(bd)
m = bd.metricas("semana")
check(m["vendido"] == 0 and m["neta"] == 0 and m["margen"] == 0,
      "una base vacía da ceros y no divide por cero")
check(bd.top_productos("semana") == [], "y el top sale vacío")
bd.cerrar()

shutil.rmtree(TEMPORAL, ignore_errors=True)
shutil.rmtree(vacio, ignore_errors=True)
print()
print("La edad de la tasa se cuenta en hora local")
# Fallo real: se restaba el día en UTC menos el día local. En Venezuela (UTC-4)
# eso adelanta el día a partir de las ocho de la noche, así que una tasa guardada
# a las 22:30 aparecía «actualizada ayer» en el acto y la tarjeta se pintaba como
# vieja. Se fija con una hora inventada para que la prueba no dependa de a qué
# hora se corra ni de dónde esté el teléfono.
from datetime import datetime, timedelta, timezone
from frontend.vistas import inicio_view

VENEZUELA = timezone(timedelta(hours=-4))
esta_noche = datetime(2026, 9, 6, 22, 30, tzinfo=VENEZUELA)   # ya es día 7 en UTC

recien = esta_noche.astimezone(timezone.utc).isoformat()
dias, texto = inicio_view._antiguedad(recien, ahora=esta_noche)
check((dias, texto) == (0, "actualizada hoy"),
      f"guardada a las 22:30 dice que es de hoy ({texto})")

de_ayer = (esta_noche - timedelta(days=1)).astimezone(timezone.utc).isoformat()
dias, texto = inicio_view._antiguedad(de_ayer, ahora=esta_noche)
check((dias, texto) == (1, "actualizada ayer"), f"la de ayer sí dice ayer ({texto})")

de_hace_tres = (esta_noche - timedelta(days=3)).astimezone(timezone.utc).isoformat()
dias, texto = inicio_view._antiguedad(de_hace_tres, ahora=esta_noche)
check((dias, texto) == (3, "actualizada hace 3 días"), f"y cuenta los días ({texto})")

manana = datetime(2026, 9, 7, 9, 0, tzinfo=VENEZUELA)
dias, _ = inicio_view._antiguedad(recien, ahora=manana)
check(dias == 1, "a la mañana siguiente ya cuenta un día")

check(inicio_view._antiguedad(None)[1] == "sin cargar", "sin tasa, lo dice")
check(inicio_view._antiguedad("no es una fecha")[1] == "sin cargar",
      "y una fecha ilegible no revienta la pantalla")

print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
