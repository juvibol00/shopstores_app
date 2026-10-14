"""El PIN de entrada.

**El PIN no se guarda.** Se guarda su huella: PBKDF2-HMAC-SHA256 con una sal
aleatoria por instalacion. Con la huella se puede comprobar si un PIN es el
correcto, pero no reconstruirlo. Si alguien se lleva el `config.json`, no se lleva
el PIN.

Las 200.000 vueltas no son decoracion: son lo que hace que probar los diez mil
PIN de cuatro digitos tarde, en vez de resolverse en un segundo. Por eso ademas se
exigen **seis digitos como minimo**.

Mas adelante (Fase 6) esta misma derivacion va a producir la llave que cifra la
credencial de Neon. Por eso se guardan la sal y las vueltas, y no solo la huella.
"""

import base64
import hashlib
import hmac
import os

# **El cifrado es opcional; el PIN no.** La huella del PIN sale de `hashlib`, que es
# biblioteca estandar y funciona en todos lados. `cryptography` solo hace falta para
# cifrar la clave de Gmail, y en el navegador no carga: su parte compilada en Rust
# no se deja abrir ahi. Como desde el navegador tampoco se puede mandar correo, no
# se pierde nada: sin `cryptography` la app entra igual y solo se apaga el correo.
try:
    from cryptography.fernet import Fernet, InvalidToken
    CIFRADO_DISPONIBLE = True
except ImportError:
    Fernet = None
    CIFRADO_DISPONIBLE = False

    class InvalidToken(Exception):
        """Reemplazo inofensivo: sin cifrado nunca se lanza."""

from backend import almacenamiento

VUELTAS = 200_000
LARGO_MINIMO = 6

# Claves de `almacenamiento` cuyo valor esta cifrado. Al cambiar el PIN hay que
# descifrarlas con la llave vieja y volverlas a cifrar con la nueva, o quedan
# ilegibles para siempre.
SECRETOS = ["correo_clave_app"]

# La llave de cifrado vive **solo en memoria** y solo mientras la sesion esta
# abierta. Se deriva del PIN al entrar; si la app se cierra, no queda en ningun
# lado desde donde recuperarla.
_llave = None


class PinInvalido(Exception):
    """El PIN propuesto no cumple las reglas. El mensaje es para mostrarlo."""


def _pbkdf2():
    """`hashlib.pbkdf2_hmac`, repuesto si el navegador lo dejo afuera.

    Es la misma trampa de orden que `HTTPSHandler` (ver `backend/pdf.py`). En el
    navegador, `pbkdf2_hmac` viene de una pieza que se instala aparte, y el
    instalador de Flet (`micropip`) importa `hashlib` **antes** de instalarla: el
    modulo queda guardado sin la funcion, e instalarla despues no lo arregla. Asi
    el boton «Crear acceso» fallaba sin decir nada. Volver a cargar `hashlib`, con
    la pieza ya presente, si la trae. Comprobado en el mismo Pyodide 0.27.7.

    En la computadora y en Android la funcion ya esta y la recarga no se ejecuta.
    """
    if not hasattr(hashlib, "pbkdf2_hmac"):
        import importlib
        importlib.reload(hashlib)     # recarga el mismo modulo, en su lugar
    return hashlib.pbkdf2_hmac


def _derivar(pin, sal, vueltas=VUELTAS):
    return _pbkdf2()("sha256", pin.encode("utf-8"), sal, vueltas)


def validar_propuesta(pin, repeticion=None):
    """Lanza `PinInvalido` con un texto que se puede mostrar tal cual."""
    pin = (pin or "").strip()
    if not pin.isdigit():
        raise PinInvalido("El PIN debe ser solo números.")
    if len(pin) < LARGO_MINIMO:
        raise PinInvalido(f"El PIN debe tener al menos {LARGO_MINIMO} dígitos.")
    if repeticion is not None and pin != (repeticion or "").strip():
        raise PinInvalido("Los dos PIN no coinciden.")
    return pin


def hay_pin():
    return bool(almacenamiento.obtener("pin"))


def establecer(pin, repeticion=None):
    """Guarda la huella del PIN y **abre la sesion**: deja lista la llave de
    cifrado, para que lo que se guarde a continuacion se pueda cifrar."""
    pin = validar_propuesta(pin, repeticion)
    sal = os.urandom(16)
    # Dos sales distintas a proposito: si fueran la misma, la huella guardada en
    # claro seria una pista sobre la llave que cifra los secretos.
    sal_cifrado = os.urandom(16)
    almacenamiento.guardar("pin", {
        "sal": sal.hex(),
        "sal_cifrado": sal_cifrado.hex(),
        "vueltas": VUELTAS,
        "huella": _derivar(pin, sal).hex(),
    })
    _abrir_sesion(pin)


def verificar(pin):
    guardado = almacenamiento.obtener("pin")
    if not guardado:
        return False
    try:
        sal = bytes.fromhex(guardado["sal"])
        esperada = bytes.fromhex(guardado["huella"])
        vueltas = int(guardado["vueltas"])
    except (KeyError, ValueError, TypeError):
        return False

    calculada = _derivar((pin or "").strip(), sal, vueltas)

    # `compare_digest` y no `==`: comparar byte a byte tarda distinto segun cuantos
    # coinciden, y ese tiempo filtra informacion sobre la huella.
    if not hmac.compare_digest(calculada, esperada):
        return False
    _abrir_sesion((pin or "").strip())
    return True


def cambiar(pin_actual, pin_nuevo, repeticion=None):
    """Cambia el PIN y **vuelve a cifrar los secretos** con la llave nueva.

    Sin este paso, la clave del correo quedaria cifrada con una llave que ya no
    se puede derivar, y no habria forma de recuperarla.
    """
    if not verificar(pin_actual):
        raise PinInvalido("El PIN actual no es correcto.")
    validar_propuesta(pin_nuevo, repeticion)

    # Se descifran ANTES de tocar el PIN, con la llave que todavia sirve.
    en_claro = {clave: descifrar(almacenamiento.obtener(clave))
                for clave in SECRETOS}
    establecer(pin_nuevo, repeticion)
    for clave, valor in en_claro.items():
        if valor is None:
            continue
        almacenamiento.guardar(clave, cifrar(valor))


def parece_debil(pin):
    """Avisa, no bloquea. Es la clave del dueno y la decision es suya.

    Se marcan los tres patrones que prueba primero cualquiera: todos los digitos
    iguales, una secuencia corrida, y algo con forma de fecha.
    """
    pin = (pin or "").strip()
    if not pin.isdigit():
        return None
    if len(set(pin)) == 1:
        return "Son todos el mismo dígito."
    corridos = all(int(pin[i + 1]) - int(pin[i]) == 1 for i in range(len(pin) - 1))
    bajando = all(int(pin[i]) - int(pin[i + 1]) == 1 for i in range(len(pin) - 1))
    if corridos or bajando:
        return "Son dígitos consecutivos."
    if len(pin) == 6:
        dia, mes = int(pin[:2]), int(pin[2:4])
        if 1 <= dia <= 31 and 1 <= mes <= 12:
            return "Parece una fecha, y es lo primero que prueba alguien que te conoce."
    return None


# --------------------------------------------------------------------------
# Cifrado de secretos
# --------------------------------------------------------------------------

def _abrir_sesion(pin):
    """Deriva la llave de cifrado y la deja en memoria mientras dure la sesion.

    Sin `cryptography` no hay llave que derivar: el PIN ya se comprobo con su
    huella y se entra igual. Lo unico que queda sin funcionar es guardar secretos.
    """
    global _llave
    if not CIFRADO_DISPONIBLE:
        return
    guardado = almacenamiento.obtener("pin") or {}
    hexa = guardado.get("sal_cifrado")
    if not hexa:
        # Base creada antes de que existiera el cifrado: se le agrega la sal ahora.
        # No se puede reusar la del PIN sin debilitar las dos.
        sal_cifrado = os.urandom(16)
        guardado["sal_cifrado"] = sal_cifrado.hex()
        almacenamiento.guardar("pin", guardado)
    else:
        sal_cifrado = bytes.fromhex(hexa)
    bruta = _derivar(pin, sal_cifrado, int(guardado.get("vueltas", VUELTAS)))
    _llave = Fernet(base64.urlsafe_b64encode(bruta))


def cerrar_sesion():
    global _llave
    _llave = None


def sesion_abierta():
    return _llave is not None


def cifrar(texto):
    """Devuelve el texto cifrado, listo para guardar. Requiere sesion abierta."""
    if not CIFRADO_DISPONIBLE:
        # Antes que guardar la clave en claro, no se guarda: una clave de Gmail
        # legible en el disco da permiso para mandar correo en tu nombre.
        raise PinInvalido("En esta versión no se pueden guardar claves.")
    if _llave is None:
        raise PinInvalido("La sesión no está abierta.")
    return _llave.encrypt((texto or "").encode("utf-8")).decode("ascii")


def descifrar(guardado):
    """Devuelve el texto original, o `None` si no hay nada o no se puede leer.

    Devolver `None` en vez de reventar es deliberado: un secreto ilegible —porque
    se restauro un respaldo de otro telefono, por ejemplo— tiene que hacer que la
    pantalla pida escribirlo de nuevo, no que la app no abra.
    """
    if not guardado or _llave is None:
        return None
    try:
        return _llave.decrypt(guardado.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return None
