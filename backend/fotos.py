"""Las fotos de los productos.

Tres tamanos, definidos en la seccion 7 del documento de diseno. Se redimensionan
**al guardar**, nunca al mostrar: una foto de camara son 4-6 MB y guardarla entera
llenaria el telefono y haria imposible mandar el catalogo.

Verificado en la Fase 0 con cinco imagenes distintas, incluida una apaisada con
etiqueta EXIF de orientacion.
"""

import io

from PIL import Image, ImageOps

# (lado maximo, calidad JPEG, presupuesto de peso en KB)
MEDIDAS = {
    "miniatura": (200, 70, 25),    # listas y carrito
    "catalogo": (400, 70, 60),     # el PDF
    "completa": (1000, 80, 250),   # al abrir el producto
}

MAXIMO_POR_PRODUCTO = 3

ORIENTACION_EXIF = 0x0112


def redimensionar(datos, lado_max, calidad, presupuesto_kb=None):
    """Devuelve un JPEG que cabe en un cuadrado de `lado_max`, respetando la
    proporcion original.

    Si la imagen que entra ya es un JPEG derecho, ya cabe en `lado_max` y ya pesa
    menos que `presupuesto_kb`, **se devuelve tal cual, sin tocarla**. Volver a
    codificar un JPEG le quita calidad aunque no cambie de tamano —perdida
    generacional, cada pasada degrada un poco mas— y ahi no habria nada que ganar.

    El criterio es el presupuesto y no "cual pesa menos": si se eligiera siempre el
    mas chico, se estaria cambiando calidad por bytes a espaldas del usuario en
    fotos que ya estaban bien.
    """
    imagen = Image.open(io.BytesIO(datos))
    formato = imagen.format
    orientacion = imagen.getexif().get(ORIENTACION_EXIF, 1)

    # Se decide con la cabecera, antes de leer un solo pixel.
    if (formato == "JPEG"
            and orientacion in (0, 1)                    # no hay que enderezarla
            and max(imagen.size) <= lado_max             # ya cabe
            and presupuesto_kb is not None
            and len(datos) <= presupuesto_kb * 1024):    # ya pesa poco
        return datos

    # **Un JPEG se puede leer ya achicado.** `draft` le pide al decodificador la
    # escala mas chica que siga siendo mayor que `lado_max` (1/2, 1/4 o 1/8), en
    # vez de armar los 12 megapixeles de una foto de telefono para despues
    # tirarlos. En el navegador del iPhone eso era lo que hacia que guardar una
    # foto tardara o se colgara: medido en el mismo Pyodide, una foto de 9 MB
    # paso de 2,5 s a 1,3 s, con mucha menos memoria. Como despues igual se
    # achica con LANCZOS, la calidad final no cambia. En PNG no hace nada.
    imagen.draft("RGB", (lado_max, lado_max))

    # El telefono no rota el pixel: escribe la rotacion en el EXIF. Sin esto, la
    # mitad de los productos saldria acostada en el catalogo.
    imagen = ImageOps.exif_transpose(imagen)

    # JPEG no admite canal alfa; un PNG de la galeria reventaria al guardar.
    if imagen.mode != "RGB":
        imagen = imagen.convert("RGB")

    imagen.thumbnail((lado_max, lado_max), Image.LANCZOS)

    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=calidad, optimize=True)
    return salida.getvalue()


def preparar(datos):
    """De los bytes que devuelve el selector a los tres tamanos que se guardan.

    Devuelve un dict listo para `basedatos.guardar_foto`. Si la imagen esta rota o
    no es una imagen, lanza la excepcion de Pillow y la pantalla la muestra.
    """
    return {nombre: redimensionar(datos, lado, calidad, presupuesto)
            for nombre, (lado, calidad, presupuesto) in MEDIDAS.items()}
