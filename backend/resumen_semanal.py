"""El resumen de la semana, en un PDF para descargar.

Se conserva de SELL-B, y con él la lección que allá salió cara y está escrita en su
propio código:

    **El envío no puede depender de que sea lunes.** La primera versión disparaba
    solo con `hoy.weekday() == 0`. Si el negocio no abría ese día —feriado, viaje,
    teléfono descargado— la semana se perdía y no se recuperaba nunca, porque el
    martes la condición ya era falsa.

Lo que garantiza que el reporte sea de la semana pasada no es el día en que se
manda, sino **el rango de la consulta**. Mandarlo un miércoles reporta exactamente
la misma semana que mandarlo el lunes. La única guarda de verdad es no repetir el
envío dentro de la misma semana, y para eso se guarda el marcador `2026-W36`.

**Ya no se manda por correo.** Al abrir la app, Inicio avisa «¡Tu resumen
semanal está listo!» y se baja con un toque (ver `frontend/descargas.py`). Asi
no hace falta configurar Gmail ni nada que corra solo en segundo plano. El aviso
sigue ahi hasta que se baje, sea lunes o jueves: es la misma guarda de arriba.
"""

from datetime import datetime, timedelta


from backend import basedatos
from backend import formato
from backend import pdf as hoja

MORADO = (107, 78, 155)
GRIS = (110, 102, 121)
NEGRO = (39, 34, 46)
VERDE = (74, 124, 89)
ROJO = (180, 83, 75)

NOMBRE_EN_LA_NUBE = "resumen.pdf"


def marcador(fecha=None):
    """`2026-W36`. Es lo que impide avisar dos veces la misma semana."""
    fecha = fecha or datetime.now().astimezone().date()
    año, semana, _ = fecha.isocalendar()
    return f"{año}-W{semana:02d}"


def ultimo_descargado():
    return basedatos.leer_config("resumen_ultima_semana", "")


def hay_pendiente():
    """Hay resumen por bajar si esta semana todavía no se bajó **y** la semana
    pasada tuvo movimiento. Un aviso que dice «cero» todas las semanas deja de
    leerse."""
    if ultimo_descargado() == marcador():
        return False
    return ventas_de_la_semana() > 0


def ventas_de_la_semana():
    """Cuantas ventas hubo la semana pasada. Solo eso, no el resumen entero:
    se pregunta cada vez que se abre Inicio o Gestion, y armar el resumen son
    seis consultas."""
    desde, hasta, _ = basedatos.rango("semana_pasada")
    return basedatos.resumen_ventas(desde, hasta)["ventas"]


def titulo():
    """`lunes 5 de octubre al domingo 11 de octubre`. Sale de la fecha del
    telefono, sin consultar nada."""
    desde, hasta, _ = basedatos.rango("semana_pasada")
    primero = datetime.fromisoformat(desde).astimezone().date()
    ultimo = datetime.fromisoformat(hasta).astimezone().date() - timedelta(days=1)
    return f"{formato.dia_largo(primero)} al {formato.dia_largo(ultimo)}"


def marcar_descargado():
    basedatos.escribir_config("resumen_ultima_semana", marcador())


def nombre_archivo(d):
    """`resumen-semanal-2026-10-05.pdf`, con el lunes de esa semana."""
    lunes = datetime.fromisoformat(d["desde"]).astimezone().date().isoformat()
    return f"resumen-semanal-{lunes}.pdf"


def datos():
    """Todo lo que va en el resumen, de la semana pasada completa."""
    desde, hasta, _ = basedatos.rango("semana_pasada")
    basedatos.precargar_semana(desde, hasta)       # las seis, en un viaje
    return {
        "desde": desde,
        "hasta": hasta,
        "titulo": titulo(),
        "metricas": basedatos.metricas(desde=desde, hasta=hasta,
                                       etiqueta="La semana pasada"),
        "top": basedatos.top_productos(limite=5, desde=desde, hasta=hasta),
        "pagos": basedatos.desglose_de_pagos(desde, hasta),
        "gastos": basedatos.gastos_por_categoria(desde=desde, hasta=hasta),
        "serie": basedatos.serie_diaria(desde=desde, hasta=hasta),
        "por_cobrar": basedatos.total_por_cobrar(),
    }


# --------------------------------------------------------------------------
# El PDF
# --------------------------------------------------------------------------

def armar_pdf(d=None):
    d = d or datos()
    m = d["metricas"]

    pdf = hoja.hoja_a4()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title("Resumen semanal")
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*MORADO)
    pdf.cell(0, 10, "Resumen de la semana", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 6, d["titulo"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    def fila(etiqueta, valor, negrita=False, color=NEGRO, signo=""):
        pdf.set_font("Helvetica", "B" if negrita else "", 11)
        pdf.set_text_color(*GRIS)
        pdf.cell(110, 7, etiqueta)
        pdf.set_text_color(*color)
        pdf.cell(0, 7, f"{signo}{formato.dinero(valor)}", align="R",
                 new_x="LMARGIN", new_y="NEXT")

    def raya():
        y = pdf.get_y() + 1
        pdf.set_draw_color(220, 205, 240)
        pdf.line(15, y, 195, y)
        pdf.ln(3)

    fila("Ingresos", m["vendido"])
    fila("Costo de lo vendido", m["costo"], signo="- ")
    raya()
    fila("Ganancia bruta", m["bruta"], negrita=True)
    fila("Gastos", m["gastos"], signo="- ")
    raya()
    fila("Ganancia neta", m["neta"], negrita=True,
         color=VERDE if m["neta"] >= 0 else ROJO)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 6, f"{m['ventas']} venta(s)  ·  margen {m['margen']:.1f} %  ·  "
                   f"entró en caja {formato.dinero(m['entro_en_caja'])}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    def seccion(titulo, filas):
        if not filas:
            return
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NEGRO)
        pdf.cell(0, 8, titulo, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        for izquierda, derecha in filas:
            pdf.set_text_color(*GRIS)
            pdf.cell(120, 6, izquierda[:60])
            pdf.set_text_color(*NEGRO)
            pdf.cell(0, 6, derecha, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    seccion("Lo que más se vendió",
            [(f"{t['nombre']}  ({float(t['unidades']):g} u.)",
              formato.dinero(t["vendido"]))
             for t in d["top"]])
    seccion("Entró por",
            [(p["metodo_nombre"],
              formato.dinero(p["monto"]) if p["moneda"] == "USD"
              else formato.bolivares(p["monto"]))
             for p in d["pagos"]])
    seccion("Gastos",
            [(g["categoria"], formato.dinero(g["total"])) for g in d["gastos"]])

    c = d["por_cobrar"]
    if c["total"] > 0:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NEGRO)
        pdf.cell(0, 8, "Crédito pendiente", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*GRIS)
        pdf.cell(0, 6, f"{formato.dinero(c['total'])} en la calle, de "
                       f"{c['clientes']} cliente(s), al día de hoy",
                 new_x="LMARGIN", new_y="NEXT")
        if c["vencido"] > 0:
            pdf.set_text_color(*ROJO)
            pdf.cell(0, 6, f"{formato.dinero(c['vencido'])} ya vencido",
                     new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


# --------------------------------------------------------------------------
# El correo
# --------------------------------------------------------------------------
