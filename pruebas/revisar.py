"""Revisa el código en busca de nombres que no existen.

Nace de un fallo real: al reescribir la pantalla de Venta para el pase visual se
perdió `_formulario_cliente_rapido`, y la aplicación reventaba al tocar «cliente
nuevo». Las pruebas no lo vieron porque **construyen las pantallas pero no llaman a
los manejadores**: un nombre inexistente dentro de un `on_click` no se toca hasta
que alguien pulsa el botón.

Esto lo encuentra sin ejecutar nada. `pyflakes` es solo para desarrollo, no entra en
el APK: si no está instalado, se avisa y se sigue.

    python pruebas/revisar.py
"""

import glob
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(AQUI)

# Lo que rompe la aplicación en marcha. Un import sin usar es desorden; un nombre
# que no existe es una pantalla que revienta al tocarla.
GRAVES = ("undefined name", "redefinition of unused")


def archivos_de_la_app():
    """Todo el codigo de la aplicacion: la raiz, el backend y el frontend.

    Se lista aca y no en cada revision para que agregar una carpeta sea un solo
    cambio.
    """
    return sorted(
        glob.glob(os.path.join(APP, "*.py"))
        + glob.glob(os.path.join(APP, "backend", "*.py"))
        + glob.glob(os.path.join(APP, "frontend", "*.py"))
        + glob.glob(os.path.join(APP, "frontend", "vistas", "*.py")))


def el_backend_no_sabe_de_pantallas():
    """Ningún archivo de `backend/` puede importar `flet` ni el `frontend`.

    Es lo que sostiene la división en dos carpetas. Mientras se cumpla, el backend
    se puede usar desde una prueba, desde un script o desde otra interfaz; el día
    que un generador de PDF importe un control, la línea deja de existir y volvemos
    a tener todo mezclado.
    """
    infractores = []
    for ruta in sorted(glob.glob(os.path.join(APP, "backend", "*.py"))):
        for numero, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if (linea.startswith("import flet")
                    or linea.startswith("from flet")
                    or linea.startswith("from frontend")
                    or linea.startswith("import frontend")):
                infractores.append(
                    f"{os.path.relpath(ruta, APP)}:{numero}: el backend no puede "
                    f"depender de la interfaz; eso va en frontend/")
    return infractores


def nadie_se_repinta_robandose_el_contenido():
    """Una pantalla no puede repintarse construyendo una copia de si misma.

    El idioma prohibido es `contenedor.content = _pantalla(...).content`: la copia
    trae su propio contenedor y su propio repintado, y los botones quedan
    apuntando a una pantalla que nunca se monto. Se ve como que el primer toque
    funciona y el segundo no. Para eso esta `frontend/pantalla.py`.
    """
    infractores = []
    for ruta in sorted(glob.glob(os.path.join(APP, "frontend", "vistas", "*.py"))
                       + glob.glob(os.path.join(APP, "frontend", "*.py"))):
        for numero, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            limpia = linea.strip()
            if ".content = " in limpia and limpia.endswith(").content"):
                infractores.append(
                    f"{os.path.relpath(ruta, APP)}:{numero}: se repinta robandole "
                    f"el contenido a una copia; usa pantalla.repintable")
    return infractores


def solo_dialogos_toca_el_overlay():
    """`page.overlay` se manipula **solo** en `dialogos.py`.

    Ahí están escritas las cinco trampas de los diálogos en Flet 0.85.3, y ya se
    rompieron dos veces por saltárselas. Si otra pantalla empieza a meter mano al
    overlay por su cuenta, esas reglas dejan de valer para toda la aplicación.
    """
    infractores = []
    archivos = archivos_de_la_app()
    for ruta in sorted(archivos):
        if os.path.basename(ruta) == "dialogos.py":
            continue
        for numero, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if "page.overlay" in linea:
                infractores.append(
                    f"{os.path.relpath(ruta, APP)}:{numero}: toca page.overlay "
                    f"directamente; usa dialogos.abrir/cerrar/aviso")
    return infractores


def los_formateadores_viven_en_formato():
    """Escribir montos, cantidades y fechas se hace **solo** en `formato.py`.

    `_dinero` llegó a estar copiado en ocho archivos, `_bolivares` en cinco y las
    listas de meses en cuatro. Todas iguales, que es lo malo: el día que cambie
    cómo se escribe un monto, hay que acordarse de ocho lugares. Esto avisa apenas
    aparezca la novena copia.
    """
    prohibidos = ("def _dinero", "def _bolivares", "def _cantidad",
                  "def _numero", "def _dia_local", "def _hora_local",
                  "def _dia_largo", "MESES = [")
    infractores = []
    archivos = archivos_de_la_app()
    for ruta in sorted(archivos):
        if os.path.basename(ruta) == "formato.py":
            continue
        for numero, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            for prohibido in prohibidos:
                if linea.startswith(prohibido):
                    infractores.append(
                        f"{os.path.relpath(ruta, APP)}:{numero}: "
                        f"«{prohibido}» ya vive en formato.py; úsalo desde ahí")
    return infractores


def main():
    archivos = archivos_de_la_app()
    try:
        r = subprocess.run([sys.executable, "-m", "pyflakes"] + archivos,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        print("pyflakes no está instalado; se salta la revisión.")
        print("  pip install pyflakes")
        return 0

    salida = ((r.stdout or "") + (r.stderr or "")).strip()
    if "No module named" in salida:
        print("pyflakes no está instalado; se salta la revisión.")
        print("  pip install pyflakes")
        return 0

    lineas = [l for l in salida.splitlines() if l.strip()]
    graves = [l for l in lineas if any(g in l for g in GRAVES)]
    graves += el_backend_no_sabe_de_pantallas()
    graves += nadie_se_repinta_robandose_el_contenido()
    graves += solo_dialogos_toca_el_overlay()
    graves += los_formateadores_viven_en_formato()
    leves = [l for l in lineas if l not in graves]

    for l in graves:
        print("GRAVE  " + l.replace(APP + os.sep, ""))
    for l in leves:
        print("       " + l.replace(APP + os.sep, ""))

    if graves:
        print(f"\n{len(graves)} problema(s) que rompen la aplicación en marcha.")
        return 1
    print(f"Sin nombres indefinidos."
          + (f" ({len(leves)} aviso(s) menor(es))" if leves else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
