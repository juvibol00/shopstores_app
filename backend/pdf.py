"""La hoja en blanco de los PDF, cargada recien cuando hace falta.

`fpdf2` arma el catalogo y el resumen semanal. Se importa **aca adentro, al pedir
una hoja**, y no arriba de los archivos, por dos razones que salieron de la version
para navegador:

**1. La app no puede depender de los PDF para arrancar.** Importado arriba, `fpdf2`
se cargaba al abrir la aplicacion aunque nadie fuera a generar nada. Si fallaba,
la app no llegaba ni a la pantalla del PIN. Un PDF es una funcion entre muchas:
si algun dia falla, que falle al tocar «Generar», no al abrir.

**2. En el navegador, `fpdf2` choca con el orden de arranque.** Al importarse pide
`urllib.request.HTTPSHandler`, y Python solo lo define si `ssl` estaba cargado
**antes** de que alguien importara `urllib.request`. El arranque de Flet usa
`urllib` antes de instalar `ssl`, y cargar `ssl` despues no lo arregla: el modulo
ya quedo guardado sin esa pieza. Lo que si lo arregla es volver a cargar
`http.client` y `urllib.request` con `ssl` ya presente. Comprobado en el mismo
Pyodide 0.27.7 que usa la app, en los tres casos: orden malo, `ssl` tarde, y
recarga.

En la computadora y en Android nada de esto pasa: `ssl` viene incluido, la pieza
ya esta, y la recarga ni se ejecuta.
"""


def _asegurar_https():
    """Si a `urllib.request` le falta `HTTPSHandler` pero `ssl` ya esta, lo repone."""
    import importlib
    import importlib.util
    import urllib.request
    if hasattr(urllib.request, "HTTPSHandler"):
        return
    if importlib.util.find_spec("ssl") is None:
        return        # sin ssl no hay nada que reponer; fpdf2 avisara el resto
    # Al recargarse, `http.client` hace su propio `import ssl`: ahora lo encuentra
    # y define la conexion segura, y `urllib.request` la ve y arma el `Handler`.
    import http.client
    importlib.reload(http.client)
    importlib.reload(urllib.request)


def hoja_a4():
    """Un PDF vacio, A4 y en milimetros: el punto de partida de los dos."""
    _asegurar_https()
    from fpdf import FPDF
    return FPDF(format="A4", unit="mm")
