"""Bajar un archivo al aparato: el respaldo y el resumen semanal.

**En el iPhone no se puede bajar un archivo desde Python.** Safari solo deja
descargar si la orden sale dentro del toque, y la orden que sale de Python llega
tarde: lo mismo que paso con la galeria. Lo que si funciona dentro del toque es
abrir un enlace (`ft.OpenUrl`, de Flet 1.0). Entonces, en la web:

1. El archivo se arma aca y se sube a la carpeta privada de la cuenta en
   Supabase (`supabase/03_descargas.sql`).
2. Supabase da un enlace firmado, que vence en una hora.
3. Aparece una ventana con «Descargar», y ese boton abre el enlace por su
   cuenta. En el iPhone el archivo queda en la app Archivos.

En la computadora y en Android no hace falta nada de eso: se elige donde
guardarlo y listo.
"""

import flet as ft

from backend import formato
from backend import nube
from backend import resumen_semanal as resumen
from frontend import dialogos
from frontend import selector

# Flet 1.0 o mas nuevo: la pantalla puede abrir un enlace dentro del toque.
PUEDE_ENLAZAR = hasattr(ft, "OpenUrl")

_ESCRITORIO = (ft.PagePlatform.WINDOWS, ft.PagePlatform.MACOS,
               ft.PagePlatform.LINUX)


async def ofrecer(page, datos, nombre_visible, nombre_en_la_nube, tipo, titulo,
                  explicacion, al_descargar=None):
    """Deja el archivo listo para bajar. `al_descargar` se llama cuando la
    persona lo baja (o lo guarda), no antes."""
    if page.web and PUEDE_ENLAZAR:
        try:
            nube.subir_archivo(nombre_en_la_nube, datos, tipo)
            enlace = nube.enlace_de_descarga(nombre_en_la_nube, nombre_visible)
        except nube.ErrorDeNube as ex:
            dialogos.error(page, str(ex))
            return
        dialogos.descargar(page, titulo, explicacion, enlace, al_descargar)
        return

    try:
        ruta = await selector.de(page).save_file(
            dialog_title=titulo, file_name=nombre_visible, src_bytes=datos)
    except Exception as ex:
        dialogos.error(page, f"No se pudo guardar el archivo: {ex}")
        return
    if not ruta:
        return                          # cancelo
    if page.platform in _ESCRITORIO:
        # En la computadora el selector solo elige la ruta; el archivo se
        # escribe aca. En Android lo escribe Flet con `src_bytes`.
        with open(ruta, "wb") as f:
            f.write(datos)
    if al_descargar:
        al_descargar()
    dialogos.exito(page, "Archivo guardado.")


async def resumen_semanal(page, al_terminar=None):
    """Arma el PDF de la semana pasada y lo ofrece. Lo usan el aviso de Inicio y
    el boton de Gestion. Se marca como bajado recien cuando se baja."""
    try:
        d = resumen.datos()
        pdf = resumen.armar_pdf(d)
    except ValueError as ex:
        dialogos.error(page, str(ex))
        return

    def bajado():
        resumen.marcar_descargado()
        if al_terminar:
            al_terminar()

    m = d["metricas"]
    await ofrecer(
        page, pdf, resumen.nombre_archivo(d), resumen.NOMBRE_EN_LA_NUBE,
        "application/pdf", "Tu resumen semanal está listo",
        f"Semana del {d['titulo']}: {m['ventas']} venta(s) y ganancia neta de "
        f"{formato.dinero(m['neta'])}.",
        al_descargar=bajado)
