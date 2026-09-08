"""El respaldo en Neon, contra un Postgres simulado.

No hace falta un servidor: se sustituye la conexión por un doble que guarda las
filas en memoria y responde como pg8000. Así se puede comprobar lo que de verdad
importa —qué se sube, cuándo se marca, qué pasa si se corta— sin credenciales.
"""
import io
import os
import re
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="vanes_nube_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from backend import basedatos as bd
from backend import fotos
from backend import nube
from backend import seguridad

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


class PostgresFalso:
    """Guarda las filas en memoria. Solo entiende lo que `nube.py` le manda."""

    def __init__(self, falla_desde=None):
        self.tablas = {}
        self.ddl = []
        self.escrituras = 0
        self.falla_desde = falla_desde     # revienta a partir de la N-ésima fila
        self.cerrada = False

    def run(self, sql, **kw):
        limpio = " ".join(sql.split())
        if limpio.upper().startswith(("CREATE TABLE", "ALTER TABLE")):
            self.ddl.append(limpio)
            tabla = re.search(r'"([^"]+)"', limpio).group(1)
            self.tablas.setdefault(tabla, {})
            return []
        if limpio.upper().startswith("INSERT"):
            self.escrituras += 1
            if self.falla_desde is not None and self.escrituras > self.falla_desde:
                raise RuntimeError("connection reset by peer")
            tabla = re.search(r'INSERT INTO "([^"]+)"', limpio).group(1)
            clave = kw.get("id") or kw.get("clave")
            self.tablas.setdefault(tabla, {})[clave] = dict(kw)
            return []
        m = re.match(r'SELECT COUNT\(\*\) FROM "([^"]+)"', limpio, re.I)
        if m:
            return [[len(self.tablas.get(m.group(1), {}))]]
        m = re.match(r'SELECT (.+) FROM "([^"]+)"', limpio, re.I)
        if m:
            columnas = [c.strip().strip('"') for c in m.group(1).split(",")]
            return [[fila.get(c) for c in columnas]
                    for fila in self.tablas.get(m.group(2), {}).values()]
        if "version()" in limpio:
            return [["PostgreSQL 18.6 on x86_64"]]
        return []

    def close(self):
        self.cerrada = True


def usar(falso):
    nube._conectar = lambda cadena=None: falso


def imagen():
    im = Image.new("RGB", (800, 800), "#A67C52")
    b = io.BytesIO()
    im.save(b, format="JPEG")
    return b.getvalue()


# --------------------------------------------------------------------- datos
seguridad.establecer("472913", "472913")
bd.guardar_tasa(620.0)
efectivo = [m for m in bd.listar_metodos() if m["moneda"] == "USD"][0]["id"]
prod = bd.crear_producto("Cartera", "Cuero", 20.0, 50.0, stock_inicial=20)
bd.guardar_foto(prod, fotos.preparar(imagen()))
cliente = bd.crear_cliente("Ana", "0412-1234567")
bd.registrar_venta([{"producto_id": prod, "cantidad": 2}], 620.0,
                   pagos=[{"metodo_id": efectivo, "monto": 100}])
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], 620.0, tipo="credito",
                   cliente_id=cliente)
bd.registrar_abono(cliente, 20, "USD", 620.0)
bd.crear_gasto("Delivery", "Moto", 12.0, "USD")

print("La cadena de conexión")
for mala, motivo in [("mysql://a:b@c/d", "otro motor"),
                     ("postgresql://", "sin host"),
                     ("no es una url", "sin forma de URL")]:
    try:
        nube.partir_cadena(mala)
        check(False, f"rechaza {motivo}")
    except nube.ErrorDeNube:
        check(True, f"rechaza {motivo}")

buena = ("postgresql://vane:cla%40ve@ep-rapid-sky-123.us-east-2.aws.neon.tech/"
         "vanesstore?sslmode=require")
p = nube.partir_cadena(buena)
check(p["password"] == "cla@ve", "decodifica el %40 de la contraseña")
check(p["database"] == "vanesstore", "saca el nombre de la base")

check(not nube.configurado(), "al principio no hay conexión guardada")
nube.guardar_cadena(buena)
check(nube.configurado(), "se guarda")
check(nube.leer_cadena() == buena, "y se lee descifrada")
from backend import almacenamiento
crudo = str(almacenamiento.obtener("neon_cadena"))
check("cla%40ve" not in crudo and "vane:" not in crudo,
      "la cadena NO queda en claro en el disco")
check("neon_cadena" in seguridad.SECRETOS,
      "se vuelve a cifrar al cambiar el PIN")

print("\nQué falta por subir")
faltan = nube.pendientes()
check("productos" in faltan and "ventas" in faltan, "detecta lo pendiente")
check("configuracion" not in faltan, "la configuración no lleva marca y no cuenta")
antes = nube.total_pendiente()
check(antes > 0, f"hay {antes} filas pendientes")

print("\nEl respaldo")
falso = PostgresFalso()
usar(falso)
avisos = []
subidas = nube.respaldar(avisos.append)
check(sum(subidas.values()) == antes, "sube exactamente lo que estaba pendiente")
check(nube.total_pendiente() == 0, "y no queda nada pendiente")
check(falso.cerrada, "cierra la conexión al terminar")
check(len(avisos) > 0, "informa el avance mientras sube")

check(len(falso.tablas.get("productos", {})) == 1, "llegó el producto")
check(len(falso.tablas.get("ventas", {})) == 2, "llegaron las dos ventas")
check(len(falso.tablas.get("producto_fotos", {})) == 1, "llegó la foto")
foto_arriba = list(falso.tablas["producto_fotos"].values())[0]
check(isinstance(foto_arriba["completa"], bytes), "la foto viaja como bytes")
check(len(falso.tablas.get("configuracion", {})) >= 2, "y la configuración")

esquema = " ".join(falso.ddl)
check("BYTEA" in esquema, "las fotos se declaran BYTEA")
check("DOUBLE PRECISION" in esquema, "los montos como DOUBLE PRECISION")
check("REFERENCES" not in esquema, "la copia no lleva claves foráneas")
check("PRIMARY KEY" in esquema, "pero sí clave primaria, para poder reescribir")

print("\nRespaldar dos veces no duplica")
escrituras_antes = falso.escrituras
nube.respaldar()
check(falso.escrituras - escrituras_antes <= len(falso.tablas.get("configuracion", {})),
      "el segundo respaldo no reenvía lo ya subido")
check(len(falso.tablas["ventas"]) == 2, "y no duplicó ventas")

print("\nLo nuevo sí se sube")
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], 620.0,
                   pagos=[{"metodo_id": efectivo, "monto": 50}])
check(nube.total_pendiente() > 0, "una venta nueva queda pendiente")
nube.respaldar()
check(len(falso.tablas["ventas"]) == 3, "y sube en el siguiente respaldo")
check(nube.total_pendiente() == 0, "dejando todo al día")

print("\nSi se corta la red, lo que no subió sigue pendiente")
bd.registrar_venta([{"producto_id": prod, "cantidad": 1}], 620.0,
                   pagos=[{"metodo_id": efectivo, "monto": 50}])
pendiente_antes = nube.total_pendiente()
roto = PostgresFalso(falla_desde=0)      # falla en la primera escritura
usar(roto)
try:
    nube.respaldar()
    check(False, "un corte de red avisa en vez de mentir")
except nube.ErrorDeNube as ex:
    mensaje = str(ex)
    check("conectar" in mensaje and "internet" in mensaje,
          "un corte de red avisa en palabras que la persona puede usar")
    check("5432" not in mensaje and "VPN" not in mensaje,
          "y sin jerga técnica: el puerto y el VPN no le dicen nada a quien vende")
check(nube.total_pendiente() == pendiente_antes,
      "lo que no llegó sigue marcado como pendiente")

print("\nRestaurar")
usar(falso)
copia = nube.resumen_de_la_copia()
check(copia["ventas"] == 3, "la copia dice cuántas ventas tiene")
productos_antes = bd.contar_productos()
bd.crear_producto("Solo local", "", 1.0, 2.0)
check(bd.contar_productos() == productos_antes + 1, "hay un producto solo local")
traidas = nube.restaurar()
check(bd.contar_productos() == productos_antes,
      "restaurar reemplaza: el producto que no estaba en la copia desaparece")
check(bd.contar_ventas() == 3, "y vuelven las tres ventas de la copia")
check(bd.leer_tasa() == 620.0, "la configuración también vuelve")
check(len(bd.listar_fotos(prod)) == 1, "y la foto")
check(bd.saldo_cliente(cliente) > 0, "el saldo del cliente se reconstruye")
check(nube.total_pendiente() == 0, "lo restaurado ya está sincronizado")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
