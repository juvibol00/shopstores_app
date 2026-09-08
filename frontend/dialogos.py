"""Dialogos y avisos, en un solo lugar.

Flet 0.85.3 no tiene `page.open()`: los dialogos se meten a mano en `page.overlay`.
Eso tiene cinco trampas, y son la razon de que este archivo exista: para pagarlas
una vez. **Antes de tocarlo, leelas.** Las funciones `abrir` y `cerrar` estan
copiadas de SELL-B Movil, que corre la misma version de Flet en produccion.

1. **La limpieza del overlay se hace al ABRIR, no al cerrar.** Un dialogo que se
   saca del overlay dentro del `on_click` de su propio boton muere con el evento en
   vuelo: el boton deja de responder y la ventana queda colgada. Da igual que se
   parta en dos `page.update()` seguidos —las dos actualizaciones ocurren dentro
   del mismo manejador—. Ya se intento y volvio a colgar.
2. **Nunca quitar del overlay un dialogo que sigue ABIERTO.** Su ventana queda
   huerfana en pantalla y ya no hay control al que decirle que se cierre. Al abrir
   se limpian solo los que estan cerrados (`not c.open`).
3. **Nunca reasignar la lista del overlay** (`page.overlay[:] = [...]`). Eso la
   marca como cambiada entera y el cliente vuelve a montar todo lo que hay dentro,
   incluido un dialogo ya cerrado, que reaparece.
4. **La etiqueta de los botones es `.content`, no `.text`.** Asignar `.text` no da
   error y deja el boton en blanco.
5. **Un dialogo confirma una sola vez.** Si la accion tarda, la ventana se queda
   visible mientras tanto y cada toque extra encolaba otra ejecucion.
6. **Los controles se comparan por VALOR, no por identidad.** En Flet 0.85.3 son
   dataclasses: dos dialogos con el mismo texto dan `a == b` verdadero siendo
   objetos distintos. Por eso `x in page.overlay` y `page.overlay.remove(x)`
   mienten —`remove` se lleva el primero que *parezca* igual, que puede ser otro—.
   Aqui se compara siempre con `is`.
7. **Un dialogo abre a otro dentro del mismo clic.** Guardar la tasa abre la
   confirmacion; Anular una venta abre la suya. Ahi corren seguidos `cerrar(A)` y
   `abrir(B)`, y si `abrir` limpiara ahi mismo los cerrados se llevaria a A con su
   clic todavia en vuelo: la trampa 1 otra vez, con la ventana colgada y ni
   Guardar ni Cancelar respondiendo. La limpieza va **con un evento de retraso**.

Las tres primeras parecen contradecirse: no se puede limpiar al cerrar, no se puede
quitar uno abierto, y dejarlo ahi parecia hacerlo reaparecer. La salida es la que
hay aqui: **cerrar no toca el overlay, y el siguiente `abrir` quita solo los que ya
estan cerrados.**
"""

import flet as ft

from frontend import paleta


def _boton(texto, al_click, destacado=False, peligro=False):
    if peligro:
        estilo = ft.ButtonStyle(bgcolor=paleta.ERROR, color=paleta.FONDO)
    elif destacado:
        estilo = ft.ButtonStyle(bgcolor=paleta.MARCA, color=paleta.FONDO)
    else:
        estilo = ft.ButtonStyle(color=paleta.MARCA)
    return ft.ElevatedButton(content=texto, on_click=al_click, style=estilo)


def _quitar(page, objetivo):
    """Saca del overlay **ese** control, no uno que se le parezca.

    `page.overlay.remove(x)` compara por valor y puede llevarse otro (trampa 6).
    """
    for i, c in enumerate(page.overlay):
        if c is objetivo:
            del page.overlay[i]
            return


# Dialogos ya cerrados que se pueden sacar del overlay **en la proxima apertura**,
# no en esta. Ver `abrir`: el que se acaba de cerrar todavia tiene su clic en vuelo.
_POR_LIMPIAR = []


def abrir(page, dialogo):
    """Muestra el dialogo y limpia los que quedaron cerrados **antes**.

    Cuatro detalles que **no** son adorno:

    - La limpieza va con un evento de retraso. Un dialogo que abre a otro —Guardar
      la tasa abre la confirmacion, Anular abre la suya— lo hace dentro de su
      propio clic: `cerrar(A)` y enseguida `abrir(B)`. Si aqui se sacara A del
      overlay, se estaria destruyendo A mientras su clic sigue en vuelo, que es
      justo la trampa 1: la ventana se cuelga y ya no responde ni Guardar ni
      Cancelar. Por eso lo cerrado se anota y se saca la vez siguiente, cuando ese
      evento ya termino.
    - Solo se quitan los que estan **cerrados** (`not c.open`). Sacar del overlay
      uno que sigue abierto deja su ventana huerfana en pantalla: ya no queda
      control al que decirle que se cierre, y no hay forma de quitarla.
    - Se agrega **solo si no estaba** ya en el overlay, comparando por identidad.
    - Nunca se reasigna la lista (`page.overlay[:] = [...]`): eso la marca como
      cambiada entera y el cliente vuelve a montar todo lo que hay dentro.
    """
    # 1. Lo que se cerro en eventos anteriores: ya es seguro sacarlo.
    for viejo in _POR_LIMPIAR:
        if viejo is not dialogo and not viejo.open:
            _quitar(page, viejo)
    _POR_LIMPIAR.clear()

    # 2. Lo que se cerro recien queda anotado para la proxima vez.
    _POR_LIMPIAR.extend(c for c in page.overlay
                        if isinstance(c, ft.AlertDialog) and not c.open
                        and c is not dialogo)

    # 3. Nunca dos ventanas a la vez. Se cierran, **no se quitan** (trampa 2). En
    # el historial se apilaban dos detalles identicos de la misma venta: cerrar el
    # de arriba dejaba a la vista el de abajo, igualito, y parecia que el boton
    # Cerrar no servia.
    for abierto in [c for c in page.overlay
                    if isinstance(c, ft.AlertDialog) and c.open
                    and c is not dialogo]:
        abierto.open = False

    if not any(c is dialogo for c in page.overlay):
        page.overlay.append(dialogo)
    dialogo.open = True
    page.update()


def cerrar(page, dialogo):
    """Cierra el dialogo. **No lo saca del overlay**, a proposito.

    `cerrar` se llama casi siempre desde el `on_click` de un boton del propio
    dialogo. Quitar el control ahi lo destruye mientras su evento todavia se esta
    procesando, y la ventana se cuelga: el boton Guardar deja de responder y no hay
    forma de salir. Pasó en SELL-B y volvio a pasar aqui al intentar limpiarlo
    antes de tiempo.

    La limpieza se hace **al abrir el siguiente** (ver `abrir`), cuando ya no hay
    ningun evento en vuelo.
    """
    dialogo.open = False
    page.update()


def aviso(page, mensaje, color=None):
    """Una barra de aviso al pie.

    Se quitan las que ya se cerraron, con el mismo cuidado que los dialogos: una
    barra todavia visible no se saca del overlay.
    """
    for barra_vieja in [c for c in page.overlay
                        if isinstance(c, ft.SnackBar) and not c.open]:
        page.overlay.remove(barra_vieja)
    barra = ft.SnackBar(ft.Text(mensaje, color=paleta.FONDO),
                        bgcolor=color or paleta.MARCA)
    page.overlay.append(barra)
    barra.open = True
    page.update()


def error(page, mensaje):
    aviso(page, mensaje, paleta.ERROR)


def exito(page, mensaje):
    aviso(page, mensaje, paleta.OK)


def confirmar(page, titulo, explicacion, etiqueta_si, al_confirmar, peligro=False):
    """Pregunta antes de algo que no se deshace.

    `explicacion` tiene que decir **el alcance**, no solo "¿estas seguro?": que se
    lleva por delante y que no.
    """
    # Un dialogo confirma **una sola vez**. Si la accion tarda —mandar un correo
    # son varios segundos— la ventana se queda visible mientras tanto y cada toque
    # extra encolaba otra ejecucion. Al volver el control, se ejecutaban todas.
    hecho = {"si": False}

    def responder(e):
        if hecho["si"]:
            return
        hecho["si"] = True
        cerrar(page, dialogo)
        al_confirmar()

    dialogo = ft.AlertDialog(
        modal=True,
        title=ft.Text(titulo, color=paleta.TEXTO),
        content=ft.Text(explicacion, color=paleta.TEXTO_SUAVE),
        actions=[
            _boton("Cancelar", lambda e: cerrar(page, dialogo)),
            _boton(etiqueta_si, responder, destacado=not peligro, peligro=peligro),
        ],
        bgcolor=paleta.TARJETA,
    )
    abrir(page, dialogo)


def pedir_numero(page, titulo, explicacion, etiqueta_campo, valor_inicial,
                 al_aceptar, texto_vivo=None):
    """Un dialogo con un solo campo numerico.

    `texto_vivo(valor)` puede devolver una linea que se actualiza mientras se
    escribe — por ejemplo "Nuevo total: 23". Ver lo que va a quedar **antes** de
    guardar es lo que evita el error de tipeo que descuadra el inventario.
    """
    resultado = ft.Text("", size=12, color=paleta.TEXTO_SUAVE)
    problema = ft.Text("", size=12, color=paleta.ERROR)

    campo = ft.TextField(label=etiqueta_campo, value=str(valor_inicial),
                         keyboard_type=ft.KeyboardType.NUMBER,
                         border_color=paleta.BEIGE,
                         focused_border_color=paleta.MARCA)

    def al_escribir(e):
        problema.value = ""
        if texto_vivo:
            try:
                resultado.value = texto_vivo(float((campo.value or "0").replace(",", ".")))
            except ValueError:
                resultado.value = ""
        page.update()

    campo.on_change = al_escribir
    al_escribir(None)

    def aceptar(e):
        try:
            valor = float((campo.value or "").replace(",", "."))
        except ValueError:
            problema.value = "Escribe un número."
            page.update()
            return
        cerrar(page, dialogo)
        al_aceptar(valor)

    dialogo = ft.AlertDialog(
        modal=True,
        title=ft.Text(titulo, color=paleta.TEXTO),
        content=ft.Column([
            ft.Text(explicacion, size=12, color=paleta.TEXTO_SUAVE),
            campo, resultado, problema,
        ], tight=True, spacing=10, width=300),
        actions=[
            _boton("Cancelar", lambda e: cerrar(page, dialogo)),
            _boton("Guardar", aceptar, destacado=True),
        ],
        bgcolor=paleta.TARJETA,
    )
    abrir(page, dialogo)


def en_segundo_plano(page, trabajo, al_terminar=None):
    """Corre algo lento fuera del hilo de la interfaz.

    Un envio de correo tarda unos segundos. Hecho dentro del manejador del boton,
    la pantalla queda congelada: no se cierra el dialogo, no se ve ningun cambio, y
    quien lo usa vuelve a tocar creyendo que no funciono. Cada toque encola otro
    envio, y al soltarse el hilo salen todos de golpe. Eso es lo que se veia como
    "se manda muchas veces".

    `trabajo()` corre en un hilo aparte y devuelve `(exito, mensaje)`.
    `al_terminar()` se llama despues, pase lo que pase.
    """
    def envoltura():
        try:
            exito_, mensaje = trabajo()
        except Exception as ex:
            exito_, mensaje = False, f"No se pudo completar: {ex}"
        if mensaje:
            (exito if exito_ else error)(page, mensaje)
        if al_terminar:
            al_terminar()

    page.run_thread(envoltura)
