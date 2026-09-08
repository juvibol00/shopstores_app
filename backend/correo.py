"""Enviar el catálogo por correo.

Es la vía por la que el PDF sale del teléfono, y se eligió porque `smtplib` está en
la biblioteca estándar y **no le pide nada a Android**: ni permisos, ni plugin, ni
acceso a carpetas compartidas. Verificado en la Fase 0 contra Gmail.

Sirve para dos cosas: mandárselo a un cliente que use correo, y —más importante—
mandárselo a una misma. Al abrirlo en el teléfono y descargar el adjunto, WhatsApp
ya lo ve y lo puede reenviar. Aunque nunca funcione el menú de compartir de Android,
el PDF siempre tiene por dónde salir.

**Gmail no acepta la contraseña de la cuenta**: hace falta una clave de aplicación,
que se genera aparte con la verificación en dos pasos activada y se puede revocar
sin tocar la clave real. Se guarda cifrada con el PIN (ver `seguridad.py`).
"""

import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from backend import almacenamiento
from backend import seguridad

SERVIDOR = "smtp.gmail.com"
PUERTO = 465
ESPERA = 40

CORREO_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorDeCorreo(Exception):
    """Falló el envío. El mensaje está escrito para mostrarlo tal cual."""


def configurado():
    return bool(almacenamiento.obtener("correo_remitente")
                and almacenamiento.obtener("correo_clave_app"))


def leer_configuracion():
    """La clave se devuelve descifrada solo si la sesión está abierta."""
    return {
        "remitente": almacenamiento.obtener("correo_remitente", ""),
        "destino": almacenamiento.obtener("correo_destino", ""),
        "clave": seguridad.descifrar(almacenamiento.obtener("correo_clave_app")),
    }


def guardar_configuracion(remitente, clave, destino=""):
    remitente = (remitente or "").strip()
    destino = (destino or "").strip()
    if not CORREO_VALIDO.match(remitente):
        raise ValueError("El correo del remitente no parece válido.")
    if destino and not CORREO_VALIDO.match(destino):
        raise ValueError("El correo de destino no parece válido.")
    # Gmail muestra la clave de aplicación en cuatro grupos de cuatro letras. Los
    # espacios son de adorno y romperian el login si se enviaran tal cual.
    clave = (clave or "").replace(" ", "")
    if len(clave) < 8:
        raise ValueError("La clave de aplicación parece incompleta.")

    almacenamiento.guardar("correo_remitente", remitente)
    almacenamiento.guardar("correo_destino", destino)
    almacenamiento.guardar("correo_clave_app", seguridad.cifrar(clave))


def olvidar_configuracion():
    for clave in ("correo_remitente", "correo_destino", "correo_clave_app"):
        almacenamiento.borrar(clave)


def armar_mensaje(remitente, destino, asunto, pdf, nombre_archivo,
                  cuerpo=None, html=None, logo=None):
    """Arma el correo. Aparte del envío, para poder revisarlo sin mandar nada.

    **El orden importa**: primero el texto, después la versión con formato y su
    imagen, y el adjunto al final. Al revés, el PDF convierte el mensaje en otra
    cosa y la versión con formato deja de ser una alternativa del mismo cuerpo.
    """
    mensaje = EmailMessage()
    mensaje["From"] = remitente
    mensaje["To"] = destino
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo or "Te mando el catálogo actualizado.")
    if html:
        identificador = make_msgid()[1:-1]
        mensaje.add_alternative(html.replace("{{logo}}", f"cid:{identificador}"),
                                subtype="html")
        if logo:
            mensaje.get_payload()[1].add_related(
                logo, "image", "png", cid=f"<{identificador}>")
    mensaje.add_attachment(pdf, maintype="application", subtype="pdf",
                           filename=nombre_archivo)
    return mensaje


def enviar_pdf(destino, pdf, asunto="Catálogo", cuerpo=None,
               nombre_archivo="catalogo.pdf", html=None, logo=None):
    """Manda un PDF adjunto. Lanza `ErrorDeCorreo` con un texto para mostrar.

    Sirve para el catálogo y para el resumen semanal: lo único que cambia es el
    asunto, el cuerpo y el nombre del archivo.

    Con `html` el correo sale en dos versiones: la de texto que ya estaba y una
    con formato. Cada programa de correo elige la que sabe mostrar, así que la de
    texto **no es opcional**: es lo que se ve donde el formato no llega.

    Si además se pasa `logo` (los bytes de una imagen PNG), la imagen viaja dentro
    del propio correo y el HTML la nombra escribiendo `{{logo}}` donde va la
    dirección. Va incrustada y no enlazada porque un enlace a una imagen de fuera
    queda bloqueado hasta que la persona autoriza «mostrar imágenes».
    """
    destino = (destino or "").strip()
    if not CORREO_VALIDO.match(destino):
        raise ErrorDeCorreo("El correo de destino no parece válido.")

    config = leer_configuracion()
    if not config["remitente"]:
        raise ErrorDeCorreo("Falta configurar el correo en Configuración.")
    if not config["clave"]:
        # Pasa si se restauró un respaldo de otro teléfono: el texto cifrado está,
        # pero la llave de este PIN no lo abre. Hay que escribirla de nuevo.
        raise ErrorDeCorreo("No se pudo leer la clave guardada. "
                            "Vuelve a escribirla en Configuración.")

    mensaje = armar_mensaje(config["remitente"], destino, asunto, pdf,
                            nombre_archivo, cuerpo, html, logo)

    try:
        with smtplib.SMTP_SSL(SERVIDOR, PUERTO, timeout=ESPERA) as servidor:
            servidor.login(config["remitente"], config["clave"])
            servidor.send_message(mensaje)
    except smtplib.SMTPAuthenticationError:
        # El error más probable, y el que más confunde: Gmail rechaza la
        # contraseña normal de la cuenta.
        raise ErrorDeCorreo(
            "Gmail rechazó las credenciales. Tiene que ser una clave de "
            "aplicación, no la contraseña de la cuenta.")
    except (smtplib.SMTPException, OSError) as ex:
        raise ErrorDeCorreo(f"No se pudo enviar: {ex}")
