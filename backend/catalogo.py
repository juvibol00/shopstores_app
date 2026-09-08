"""El catálogo en PDF.

Uno solo, armado con los productos marcados «Mostrar en el catálogo». Los que no
tienen existencia entran o no según el interruptor, y cuando entran salen marcados
**«A pedido»**: si aparecieran iguales que el resto, alguien pediría algo esperando
recibirlo mañana.

**Va sin el nombre del negocio**, ni en el encabezado ni en los datos internos del
archivo: se manda por mensaje a alguien que ya sabe a quién le está comprando.

Usa la foto de tamaño `catalogo` (400 px), no la completa. Medido en la Fase 0: con
50 productos, la completa da un PDF de 1,9 MB y la de catálogo uno de 0,5 MB. No se
pierde nada, porque en la hoja la foto mide 32 mm y 400 px ya pasan los 300 puntos
por pulgada.

Las fuentes base de fpdf2 son latin-1, que cubre las tildes y la eñe del español.
Por eso no hace falta empotrar una tipografía, que sumaría peso al APK.
"""

import io
from datetime import datetime

from fpdf import FPDF

from backend import basedatos
from backend import formato

# Coordenadas de la hoja A4, en milímetros.
MARGEN = 15
LADO_FOTO = 32
ALTO_FILA = 36
COLUMNA_TEXTO = 52
CORTE_DE_PAGINA = 240

MARRON = (139, 99, 64)      # #8B6340
GRIS = (122, 110, 98)       # #7A6E62
NEGRO = (46, 42, 38)        # #2E2A26
AMBAR = (201, 146, 46)      # #C9922E


class SinProductos(Exception):
    """No hay nada que poner en el catálogo. El mensaje es para mostrarlo."""


def productos_del_catalogo(incluir_sin_stock):
    """Los marcados para el catálogo, con su foto de catálogo si la tienen."""
    sql = ("SELECT p.id, p.nombre, p.descripcion, p.precio_usd, p.stock, "
           "       f.catalogo AS foto "
           "FROM productos p "
           "LEFT JOIN producto_fotos f ON f.producto_id = p.id AND f.orden = 1 "
           "WHERE p.activo = 1 AND p.en_catalogo = 1")
    if not incluir_sin_stock:
        sql += " AND p.stock > 0"
    sql += " ORDER BY p.nombre COLLATE NOCASE"
    with basedatos._candado:
        return basedatos.conexion().execute(sql).fetchall()


def _cabecera(pdf):
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*MARRON)
    pdf.cell(0, 12, "Catálogo", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def armar(incluir_sin_stock=True):
    """Devuelve `(bytes_del_pdf, cuantos_productos, cuantas_paginas)`."""
    productos = productos_del_catalogo(incluir_sin_stock)
    if not productos:
        raise SinProductos(
            "No hay productos para el catálogo. Marca «Mostrar en el catálogo» "
            "en el inventario.")

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=MARGEN)
    pdf.set_title("Catálogo")
    pdf.add_page()
    _cabecera(pdf)

    for p in productos:
        y = pdf.get_y()
        if y > CORTE_DE_PAGINA:
            pdf.add_page()
            y = pdf.get_y()

        if p["foto"]:
            pdf.image(io.BytesIO(p["foto"]), x=MARGEN, y=y,
                      w=LADO_FOTO, h=LADO_FOTO)
        else:
            # Un hueco blanco desalinea la fila entera. Un recuadro beige con una
            # raya deja claro que ese producto todavía no tiene foto.
            pdf.set_fill_color(227, 213, 191)
            pdf.rect(MARGEN, y, LADO_FOTO, LADO_FOTO, style="F")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(*GRIS)
            pdf.text(MARGEN + 7, y + LADO_FOTO / 2, "sin foto")

        pdf.set_xy(COLUMNA_TEXTO, y + 2)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*NEGRO)
        pdf.cell(0, 6, p["nombre"][:48], new_x="LMARGIN", new_y="NEXT")

        if p["descripcion"]:
            pdf.set_x(COLUMNA_TEXTO)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*GRIS)
            pdf.cell(0, 5, p["descripcion"][:60], new_x="LMARGIN", new_y="NEXT")

        pdf.set_x(COLUMNA_TEXTO)
        pdf.set_font("Helvetica", "B", 11)
        precio = f"$ {float(p['precio_usd']):,.2f}"
        if float(p["stock"]) > 0:
            pdf.set_text_color(*MARRON)
            pdf.cell(0, 6, precio, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_text_color(*AMBAR)
            pdf.cell(0, 6, f"{precio}   -   A pedido",
                     new_x="LMARGIN", new_y="NEXT")

        pdf.set_y(y + ALTO_FILA)

    return bytes(pdf.output()), len(productos), pdf.pages_count


def cuantos_entran(incluir_sin_stock):
    """Para poder decir «12 productos, 3 a pedido» antes de generar nada."""
    todos = productos_del_catalogo(True)
    con_stock = [p for p in todos if float(p["stock"]) > 0]
    sin_foto = [p for p in (todos if incluir_sin_stock else con_stock)
                if not p["foto"]]
    return {
        "total": len(todos) if incluir_sin_stock else len(con_stock),
        "a_pedido": len(todos) - len(con_stock),
        "sin_foto": len(sin_foto),
    }


# --------------------------------------------------------------------------
# El correo con el que sale
# --------------------------------------------------------------------------

def cuerpo_texto(a_pedido=0):
    """La versión sin formato, que es la que se ve donde el formato no llega."""
    lineas = [
        "Saludos cordiales,",
        "",
        "Adjunto va el catálogo actualizado, con los precios en dólares.",
    ]
    if a_pedido:
        lineas.append("Lo que aparece como «A pedido» se consigue por encargo.")
    lineas += [
        "",
        "Cualquier consulta, puedes responder a este correo.",
    ]
    return "\n".join(lineas)


def cuerpo_html(a_pedido=0):
    """El correo con el que viaja el catálogo, con el mismo formato que el del
    resumen semanal: tarjeta blanca, la misma paleta y la misma tipografía.

    **Sin el nombre del negocio**, igual que el PDF y por lo mismo: este correo se
    le manda a un cliente, y quien lo recibe ya sabe a quién le está comprando.

    El pie tampoco dice «no responder»: aquí sí se espera que la persona conteste,
    que es justamente para lo que se manda el catálogo.
    """
    nota = ""
    if a_pedido:
        nota = ('<p style="margin:14px 0 0;padding:12px 14px;background:#F2EADC;'
                'border-radius:8px;color:#7A6E62;font-size:13px;line-height:1.6;">'
                'Lo que aparece como <b style="color:#8B6340;">«A pedido»</b> no '
                'está en existencia ahora mismo: se consigue por encargo.</p>')

    return f"""<html><body style="margin:0;padding:24px 12px;
background:#F2EADC;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;background:#FFFFFF;border-radius:12px;">
<tr><td style="padding:32px 34px 34px;">

  <p style="margin:0;color:#8B6340;font-size:26px;font-weight:bold;
            letter-spacing:.3px;">Catálogo</p>
  <p style="margin:4px 0 0;color:#A69A8C;font-size:13px;">
    Actualizado el {formato.dia_largo(datetime.now().astimezone().date())}</p>

  <div style="margin:24px 0 22px;border-top:1px solid #E3D5BF;"></div>

  <p style="margin:0;color:#7A6E62;font-size:14px;line-height:1.6;">
    Saludos cordiales,<br><br>
    Adjunto va el catálogo actualizado, con los precios en dólares.
  </p>

  {nota}

  <div style="margin:30px 0 14px;border-top:1px dashed #E3D5BF;"></div>
  <p style="margin:0;color:#A69A8C;font-size:12px;line-height:1.6;
            text-align:center;">
    Cualquier consulta, puedes responder a este correo.</p>

</td></tr></table>
</td></tr></table>
</body></html>"""
