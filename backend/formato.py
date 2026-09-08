"""Cómo se escriben los números y las fechas. En un solo lugar.

Estaba copiado por todas partes: `_dinero` ocho veces, `_bolivares` cinco,
`_cantidad` tres, y dos listas de meses distintas. Todas las copias eran idénticas
—se comprobó antes de unificarlas—, que es justamente el problema: **el día que se
cambie cómo se escribe un monto, hay que acordarse de ocho archivos**. Con una
copia sola, no hay nada que recordar.

No importa `flet` a propósito. Esto lo usan también el PDF del catálogo, el del
resumen semanal y los correos, que no tienen pantalla; si arrastrara la interfaz,
no se podría usar desde ahí.
"""

from datetime import datetime

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Para los ejes de los gráficos, donde el nombre entero no cabe.
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def dinero(valor):
    """Dólares. La moneda constante: los precios y las deudas viven en esta."""
    return f"$ {float(valor or 0):,.2f}"


def bolivares(valor):
    return f"Bs {float(valor or 0):,.2f}"


def cantidad(valor):
    """Sin decimales cuando no hacen falta: «3 unidades», no «3,00 unidades»."""
    v = float(valor or 0)
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def numero(texto):
    """Lo que se escribió en un campo, como número.

    Acepta la coma decimal, que es como se escribe aquí, y devuelve 0 en vez de
    reventar: un campo a medio escribir no puede tumbar la pantalla.
    """
    try:
        return float((texto or "").replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


def dia_largo(fecha):
    """«6 de septiembre»."""
    return f"{fecha.day} de {MESES[fecha.month - 1]}"


def dia_local(iso):
    """El día **en la hora de aquí**, no en UTC.

    Las fechas se guardan en UTC. Convertirlas es lo que evita que las ventas de
    la noche aparezcan como del día siguiente: en Venezuela (UTC−4) todo lo que
    pasa después de las ocho ya es «mañana» en UTC.
    """
    return datetime.fromisoformat(iso).astimezone().date()


def hora_local(iso):
    return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
