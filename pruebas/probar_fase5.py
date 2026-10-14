"""Catálogo en PDF, cifrado de secretos y configuración del correo."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
TEMPORAL = tempfile.mkdtemp(prefix="shopstores_catalogo_")
os.environ["FLET_APP_STORAGE_DATA"] = TEMPORAL
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from backend import almacenamiento
from backend import basedatos as bd
import postgres_local
# La base de la app ahora es Supabase: cada suite usa una base nueva en un
# Postgres local, con las mismas funciones que se pegan en el panel.
_pg = postgres_local.conectar_la_app()
from backend import correo
from backend import seguridad

fallos = []


def check(c, e):
    print(("  ok   " if c else "  FALLA") + f" {e}")
    if not c:
        fallos.append(e)


def texto_del_pdf(pdf):
    """El texto de un PDF, descomprimido.

    fpdf2 comprime los flujos con zlib, así que buscar los bytes crudos en el
    archivo NO prueba nada: un `b"Shop" not in pdf` pasa siempre, aunque el nombre
    esté ahí. Hay que descomprimir para comprobar de verdad.
    """
    import zlib
    partes = []
    inicio = 0
    while True:
        i = pdf.find(b"stream", inicio)
        if i < 0:
            break
        j = pdf.find(b"endstream", i)
        if j < 0:
            break
        crudo = pdf[i + 6:j].strip()
        try:
            partes.append(zlib.decompress(crudo))
        except zlib.error:
            partes.append(crudo)
        inicio = j + 9
    return b"".join(partes)


def imagen(color="#A67C52"):
    im = Image.new("RGB", (1600, 1200), color)
    for x in range(0, 1600, 80):
        im.paste("#E3D5BF", (x, 0, x + 40, 1200))
    b = io.BytesIO()
    im.save(b, format="JPEG", quality=92)
    return b.getvalue()


print("Cifrado de secretos")
check(not seguridad.sesion_abierta(), "al arrancar no hay sesión abierta")
try:
    seguridad.cifrar("algo"); check(False, "sin sesión no se puede cifrar")
except seguridad.PinInvalido:
    check(True, "sin sesión no se puede cifrar")

seguridad.establecer("472913", "472913")
check(seguridad.sesion_abierta(), "crear el PIN abre la sesión")
secreto = seguridad.cifrar("abcd efgh ijkl mnop")
check("abcd" not in secreto, "el texto cifrado no contiene el original")
check(seguridad.descifrar(secreto) == "abcd efgh ijkl mnop", "y se puede descifrar")
check(seguridad.descifrar("basura") is None, "un valor ilegible devuelve None")
check(seguridad.descifrar(None) is None, "y un vacío también")

seguridad.cerrar_sesion()
check(seguridad.descifrar(secreto) is None, "con la sesión cerrada no se descifra")
check(seguridad.verificar("000000") is False, "un PIN malo no abre la sesión")
check(not seguridad.sesion_abierta(), "y la deja cerrada")
check(seguridad.verificar("472913"), "el PIN correcto entra")
check(seguridad.descifrar(secreto) == "abcd efgh ijkl mnop", "y vuelve a descifrar")

guardado = seguridad.huella_guardada()
check(guardado["sal"] != guardado["sal_cifrado"], "la sal del PIN y la del cifrado difieren")

print("\nConfiguración del correo")
for datos, motivo in [
    (("no-es-correo", "abcdefgh", ""), "remitente inválido"),
    (("vane@gmail.com", "abc", ""), "clave demasiado corta"),
    (("vane@gmail.com", "abcdefgh", "tampoco-correo"), "destino inválido"),
]:
    try:
        correo.guardar_configuracion(*datos); check(False, f"rechaza {motivo}")
    except ValueError: check(True, f"rechaza {motivo}")

correo.guardar_configuracion("vane@gmail.com", "abcd efgh ijkl mnop",
                             "cliente@gmail.com")
check(correo.configurado(), "queda configurado")
crudo = almacenamiento.obtener("correo_clave_app")
check("abcd" not in crudo and "mnop" not in crudo,
      "la clave NO queda en claro en el disco")
check(correo.leer_configuracion()["clave"] == "abcdefghijklmnop",
      "se lee sin los espacios de adorno de Gmail")

print("\nCambiar el PIN vuelve a cifrar")
seguridad.cambiar("472913", "819274", "819274")
check(correo.leer_configuracion()["clave"] == "abcdefghijklmnop",
      "la clave del correo sigue legible con el PIN nuevo")
seguridad.cerrar_sesion()
check(seguridad.verificar("819274"), "entra con el PIN nuevo")
check(not seguridad.verificar("472913"), "el viejo ya no sirve")
seguridad.verificar("819274")
check(correo.leer_configuracion()["clave"] == "abcdefghijklmnop",
      "y la clave se sigue leyendo tras reabrir")

# Un PDF cualquiera para probar el envio: lo que importa es el correo.
pdf = b"%PDF-1.4\n% prueba\n"

print("\nEnvío: los rechazos que no necesitan red")
try:
    correo.enviar_pdf("no-es-correo", pdf)
    check(False, "rechaza un destino inválido antes de conectar")
except correo.ErrorDeCorreo:
    check(True, "rechaza un destino inválido antes de conectar")

correo.olvidar_configuracion()
check(not correo.configurado(), "olvidar borra los datos")
try:
    correo.enviar_pdf("cliente@gmail.com", pdf)
    check(False, "sin configurar, avisa dónde configurarlo")
except correo.ErrorDeCorreo as ex:
    check("Configuración" in str(ex), "sin configurar, avisa dónde configurarlo")

# Una clave cifrada con OTRA llave: es lo que pasa al restaurar de otro teléfono.
correo.guardar_configuracion("vane@gmail.com", "abcdefghijklmnop", "")
almacenamiento.guardar("correo_clave_app", "gAAAAABlbasura")
try:
    correo.enviar_pdf("cliente@gmail.com", pdf)
    check(False, "una clave ilegible pide escribirla de nuevo")
except correo.ErrorDeCorreo as ex:
    check("Vuelve a escribirla" in str(ex), "una clave ilegible pide escribirla de nuevo")

print()
print("El correo del resumen semanal")
from backend import resumen_semanal

d = resumen_semanal.datos()
texto = resumen_semanal.cuerpo_texto(d)
html = resumen_semanal.cuerpo_html(d)

check("Saludos cordiales" in texto and "Bolívar Software Company" in texto,
      "la versión de texto saluda y firma")
check("ShopStore's" in html and "Resumen de la semana" in html,
      "la versión con formato lleva el nombre del negocio y el título")
check("<table" in html and "cellpadding" in html,
      "va armado con tablas, que es lo que respetan los correos")
check("{{logo}}" in html, "y deja el hueco del logo para incrustarlo")
check(resumen_semanal._logo() is not None, "el logo se encuentra en assets")

# El correo presenta; el PDF informa. Las cifras van en el adjunto y no se
# repiten en el cuerpo: leer dos veces lo mismo alarga el correo sin agregar
# nada, y en el teléfono un correo largo se recorre sin leerse.
peligroso = bd.crear_producto("Bolso <b>rojo</b> & negro", "", 1.0, 5.0,
                              stock_inicial=2)
metodos_pago = bd.listar_metodos()
venta_semana = bd.registrar_venta(
    [{"producto_id": peligroso, "cantidad": 1}], 620.0,
    pagos=[{"metodo_id": metodos_pago[0]["id"], "monto": 5.0}])
desde_s, hasta_s, _ = bd.rango("semana_pasada")
_pg.sql("update ventas set fecha = cast(:f as timestamptz) "
        "where id = cast(:i as uuid)", f=desde_s, i=venta_semana["id"])

d2 = resumen_semanal.datos()
html2 = resumen_semanal.cuerpo_html(d2)
check(d2["metricas"]["vendido"] > 0, "hay movimiento en la semana del ejemplo")
check("Ganancia" not in html2 and "Ingresos" not in html2,
      "el cuerpo del correo no repite las cuentas: van en el PDF")
check("Bolso" not in html2,
      "ni los nombres de los productos, que además vienen escritos a mano")
check(b"Ganancia neta" in texto_del_pdf(resumen_semanal.armar_pdf(d2)),
      "y el PDF sí las trae")

# Y el armado del mensaje: texto, formato, imagen y adjunto, en ese orden.
mensaje = correo.armar_mensaje(
    "vane@gmail.com", "vane@gmail.com", "Resumen", b"%PDF-falso",
    "resumen_semanal.pdf", cuerpo=texto, html=html,
    logo=resumen_semanal._logo())
tipos = [p.get_content_type() for p in mensaje.walk()]
check("text/plain" in tipos, "el correo lleva su versión de texto")
check("text/html" in tipos, "y su versión con formato")
check("image/png" in tipos, "con el logo dentro del propio correo")
check("application/pdf" in tipos, "y el PDF adjunto")

partes_html = [p for p in mensaje.walk() if p.get_content_type() == "text/html"]
check("{{logo}}" not in partes_html[0].get_content(),
      "el hueco del logo queda reemplazado por la imagen incrustada")
check("cid:" in partes_html[0].get_content(),
      "que se nombra como imagen interna, no como enlace de afuera")

print()
print("Sin cryptography, como en el navegador")
# En el navegador `cryptography` no carga: su parte en Rust no se deja abrir. La app
# tiene que entrar igual —el PIN usa hashlib, que si esta— y solo apagar el correo.
# Se simula poniendo el modulo en None: asi `import cryptography` falla de verdad.
import importlib
for nombre in [n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")]:
    del sys.modules[nombre]
sys.modules["cryptography"] = None
sys.modules["cryptography.fernet"] = None
try:
    importlib.reload(seguridad)
    importlib.reload(correo)

    check(seguridad.CIFRADO_DISPONIBLE is False, "detecta que no hay cifrado")

    almacenamiento.borrar("pin")
    seguridad.establecer("583927", "583927")
    seguridad.cerrar_sesion()
    check(seguridad.verificar("583927"), "el PIN se crea y se verifica igual")
    check(not seguridad.verificar("000000"), "y un PIN malo sigue sin entrar")

    try:
        seguridad.cifrar("una clave")
        check(False, "no guarda secretos en claro")
    except seguridad.PinInvalido:
        check(True, "no guarda secretos en claro")
    check(seguridad.descifrar("cualquier cosa") is None,
          "y leer un secreto devuelve nada en vez de reventar")

    check(correo.disponible() is False, "el correo se declara no disponible")
    check(correo.configurado() is False, "y nunca figura como configurado")
    try:
        correo.guardar_configuracion("tienda@gmail.com", "abcdefghijklmnop")
        check(False, "configurar el correo se rechaza con un mensaje claro")
    except ValueError as ex:
        check("no se puede" in str(ex),
              "configurar el correo se rechaza con un mensaje claro")
finally:
    # Se devuelve todo como estaba, para no contaminar lo que venga despues.
    del sys.modules["cryptography"]
    del sys.modules["cryptography.fernet"]
    importlib.reload(seguridad)
    importlib.reload(correo)

check(seguridad.CIFRADO_DISPONIBLE is True, "al volver, el cifrado esta de nuevo")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
