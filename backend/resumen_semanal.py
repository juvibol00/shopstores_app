"""El resumen de la semana, por correo.

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

En el teléfono no se manda solo: no hay servicio en segundo plano, y disparar un
correo por datos móviles sin avisar es más intrusivo que en una computadora que
está siempre encendida. La app deja el aviso en Inicio y se manda con un toque.
"""

import os
from datetime import datetime, timedelta


from backend import basedatos
from backend import formato
from backend import pdf as hoja
from backend import correo

MORADO = (107, 78, 155)
GRIS = (110, 102, 121)
NEGRO = (39, 34, 46)
VERDE = (74, 124, 89)
ROJO = (180, 83, 75)

def marcador(fecha=None):
    """`2026-W36`. Es lo que impide mandar dos veces la misma semana."""
    fecha = fecha or datetime.now().astimezone().date()
    año, semana, _ = fecha.isocalendar()
    return f"{año}-W{semana:02d}"


def ultimo_enviado():
    return basedatos.leer_config("resumen_ultima_semana", "")


def hay_pendiente():
    """Hay resumen por mandar si la semana en curso todavía no se envió **y** la
    semana pasada tuvo movimiento. Un correo que dice «cero» todas las semanas
    deja de leerse."""
    if ultimo_enviado() == marcador():
        return False
    # Solo cuantas ventas hubo, no el resumen entero: esto se pregunta cada vez
    # que se abre Inicio, y armar el resumen eran seis viajes a Supabase.
    desde, hasta, _ = basedatos.rango("semana_pasada")
    return basedatos.resumen_ventas(desde, hasta)["ventas"] > 0


def marcar_enviado():
    basedatos.escribir_config("resumen_ultima_semana", marcador())


def datos():
    """Todo lo que va en el resumen, de la semana pasada completa."""
    desde, hasta, _ = basedatos.rango("semana_pasada")
    basedatos.precargar_semana(desde, hasta)       # las seis, en un viaje
    primero = datetime.fromisoformat(desde).astimezone().date()
    ultimo = datetime.fromisoformat(hasta).astimezone().date() - timedelta(days=1)
    return {
        "desde": desde,
        "hasta": hasta,
        "titulo": f"{formato.dia_largo(primero)} al {formato.dia_largo(ultimo)}",
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

def cuerpo_texto(d):
    """La versión sin formato. **No es un descarte**: es la que se ve en los
    programas de correo que no muestran el formato, así que dice lo mismo."""
    return "\n".join([
        "Saludos cordiales,",
        "",
        f"Este es el cierre de la semana del {d['titulo']}. El detalle completo "
        "va en el PDF adjunto.",
        "",
        "--",
        "Mensaje generado automáticamente por ShopStore's.",
        "No hace falta responder a esta dirección.",
        "Bolívar Software Company.",
    ])


def cuerpo_html(d):
    """El correo con formato, en la línea de los de SELL-B: tarjeta blanca, el
    logo arriba y un pie institucional.

    **Las cifras no van aquí, van en el PDF.** Repetirlas en el cuerpo obliga a
    leer dos veces lo mismo, y un correo largo en el teléfono se recorre sin
    leerse. El correo presenta; el PDF informa.
    """
    raya = "border-top:1px solid #DCCDF0;"

    return f"""<html><body style="margin:0;padding:24px 12px;
background:#F1EBFA;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;background:#FFFFFF;border-radius:12px;">
<tr><td style="padding:32px 34px 34px;">

  <table width="100%" cellpadding="0" cellspacing="0"><tr>
    <td width="46" style="padding-right:12px;">
      <img src="{{{{logo}}}}" width="46" height="46" alt=""
           style="display:block;border-radius:11px;">
    </td>
    <td>
      <p style="margin:0;color:#6B4E9B;font-size:19px;font-weight:bold;
                letter-spacing:.3px;">ShopStore's</p>
      <p style="margin:2px 0 0;color:#9A91A8;font-size:12px;">
        Resumen semanal</p>
    </td>
  </tr></table>

  <div style="margin:26px 0 22px;{raya}"></div>

  <p style="margin:0;color:#27222E;font-size:21px;font-weight:bold;">
    Resumen de la semana</p>
  <p style="margin:4px 0 22px;color:#6E6679;font-size:14px;">{d['titulo']}</p>

  <p style="margin:0;color:#6E6679;font-size:14px;line-height:1.6;">
    Saludos cordiales,<br><br>
    Este es el cierre de la semana pasada. El detalle completo va en el PDF
    adjunto.
  </p>

  <div style="margin:30px 0 14px;border-top:1px dashed #DCCDF0;"></div>
  <p style="margin:0;color:#9A91A8;font-size:11px;line-height:1.6;
            text-align:center;">
    Mensaje generado automáticamente por ShopStore's.<br>
    No hace falta responder a esta dirección.<br>
    <span style="color:#B8AEC6;">Bolívar Software Company</span>
  </p>

</td></tr></table>
</td></tr></table>
</body></html>"""


def _logo():
    """Los bytes del icono, para que viajen dentro del correo. Si el archivo no
    está, el correo sale igual: sin imagen, no roto."""
    ruta = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "icon.png")
    try:
        with open(ruta, "rb") as archivo:
            return archivo.read()
    except OSError:
        return None


def enviar(destino=None):
    """Arma el resumen y lo manda. Devuelve el resumen para poder mostrarlo.

    Solo se marca como enviado **si el correo salió**. Si falla, la semana sigue
    pendiente y se puede reintentar: perder el resumen por un corte de red es
    justamente lo que pasaba en SELL-B.
    """
    d = datos()
    destino = (destino or correo.leer_configuracion()["destino"]
               or correo.leer_configuracion()["remitente"])
    correo.enviar_pdf(
        destino, armar_pdf(d),
        asunto=f"ShopStore's · Resumen de la semana · {d['titulo']}",
        cuerpo=cuerpo_texto(d),
        html=cuerpo_html(d),
        logo=_logo(),
        nombre_archivo="resumen_semanal.pdf")
    marcar_enviado()
    return d
