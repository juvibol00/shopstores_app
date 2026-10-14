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
from backend import catalogo
from backend import correo
from backend import fotos
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

guardado = almacenamiento.obtener("pin")
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

print("\nEl catálogo")
try:
    catalogo.armar(True); check(False, "sin productos avisa en vez de reventar")
except catalogo.SinProductos:
    check(True, "sin productos avisa en vez de reventar")

con_foto = bd.crear_producto("Cartera de cuero", "Cuero natural, 30x22",
                             20.0, 45.0, stock_inicial=5)
bd.guardar_foto(con_foto, fotos.preparar(imagen()))
sin_foto = bd.crear_producto("Pulsera tejida", "Hilo encerado", 3.0, 8.5,
                             stock_inicial=10)
agotado = bd.crear_producto("Bolso de mano", "Forro interior", 30.0, 68.0,
                            stock_inicial=0)
bd.guardar_foto(agotado, fotos.preparar(imagen("#8B6340")))
oculto = bd.crear_producto("No mostrar", "", 1.0, 2.0, stock_inicial=5)
bd.actualizar_producto(oculto, "No mostrar", "", 1.0, 2.0, en_catalogo=False)

c = catalogo.cuantos_entran(True)
check(c["total"] == 3, "cuenta 3 productos con el interruptor encendido")
check(c["a_pedido"] == 1, "de los cuales 1 va a pedido")
check(c["sin_foto"] == 1, "y 1 sin foto")
check(catalogo.cuantos_entran(False)["total"] == 2, "apagado, solo los que hay")

pdf, cuantos, paginas = catalogo.armar(True)
check(pdf[:5] == b"%PDF-", "sale un PDF de verdad")
check(cuantos == 3 and paginas == 1, "3 productos en 1 página")
texto = texto_del_pdf(pdf)
check(b"Cartera" in texto, "el texto se puede leer descomprimido")
check(b"No mostrar" not in texto, "el producto excluido no aparece")
check(b"Shop" not in texto and b"Shop" not in pdf,
      "el nombre del negocio NO aparece, ni comprimido ni en claro")
check(b"A pedido" in texto, "el agotado sale marcado A pedido")
check(b"Cat" in texto, "el encabezado dice Catálogo")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo_muestra.pdf"), "wb").write(pdf)

pdf_corto, cuantos, _ = catalogo.armar(False)
check(cuantos == 2, "apagado el interruptor, entran 2")
check(b"Bolso" not in texto_del_pdf(pdf_corto), "el agotado queda fuera")
check(b"Bolso" in texto, "y dentro cuando se incluye")
check(b"A pedido" not in texto_del_pdf(pdf_corto),
      "y sin agotados no queda ningún «A pedido»")

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
bd.conexion().execute("UPDATE ventas SET fecha = ? WHERE id = ?",
                      (desde_s, venta_semana["id"]))
bd.conexion().commit()

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
print("El correo con el que sale el catálogo")
texto_cat = catalogo.cuerpo_texto(0)
html_cat = catalogo.cuerpo_html(0)

check("Saludos cordiales" in texto_cat and "Catálogo" in html_cat,
      "saluda y se presenta como catálogo")
check("Shop" not in html_cat and "Shop" not in texto_cat,
      "va SIN el nombre del negocio, igual que el PDF")
check("no responder" not in html_cat.lower()
      and "responder a este correo" in html_cat,
      "y aquí sí se invita a responder: es un correo a un cliente")
check("#F1EBFA" in html_cat and "#6B4E9B" in html_cat,
      "usa la misma paleta que el del resumen semanal")

check("A pedido" not in catalogo.cuerpo_html(0),
      "sin agotados no se menciona lo de «A pedido»")
check("A pedido" in catalogo.cuerpo_html(3),
      "y con agotados se explica qué significa")

mensaje_cat = correo.armar_mensaje(
    "vane@gmail.com", "cliente@gmail.com", "Catálogo", pdf, "catalogo.pdf",
    cuerpo=texto_cat, html=html_cat)
tipos_cat = [p.get_content_type() for p in mensaje_cat.walk()]
check("text/plain" in tipos_cat and "text/html" in tipos_cat
      and "application/pdf" in tipos_cat,
      "el correo sale con texto, formato y el PDF adjunto")
check("image/png" not in tipos_cat,
      "y sin logo incrustado, que también identificaría el negocio")

bd.cerrar()
shutil.rmtree(TEMPORAL, ignore_errors=True)
print(f"\n{'TODO BIEN' if not fallos else 'FALLARON: ' + ', '.join(fallos)}")
sys.exit(1 if fallos else 0)
