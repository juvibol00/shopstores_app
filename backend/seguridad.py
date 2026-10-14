"""El PIN de entrada.

**El PIN no se guarda.** Se guarda su huella: PBKDF2-HMAC-SHA256 con una sal
aleatoria por instalacion. Con la huella se puede comprobar si un PIN es el
correcto, pero no reconstruirlo. Si alguien se lleva el `config.json`, no se lleva
el PIN.

Las 200.000 vueltas no son decoracion: son lo que hace que probar los diez mil
PIN de cuatro digitos tarde, en vez de resolverse en un segundo. Por eso ademas se
exigen **seis digitos como minimo**.

Esta misma derivacion produce la llave que cifra la clave de Gmail (ver
`cifrar`). Por eso se guardan la sal y las vueltas, y no solo la huella.

**La huella vive en la cuenta, no en el aparato.** Se guarda en la configuracion
de la cuenta en Supabase, protegida por el RLS como todo lo demas: un PIN creado
una vez sirve en cualquier telefono donde se entre con ese correo, y cambiarlo en
uno lo cambia en todos. Antes vivia en `config.json` de cada aparato, y cada
telefono nuevo hacia crear el perfil de nuevo. `_leer_pin` sube solo la huella
vieja la primera vez.

Los secretos cifrados (la clave de Gmail) **si** siguen en cada aparato: se usan
solo en Android y en la computadora. Si el PIN se cambia en otro aparato, la
clave guardada en este ya no se puede descifrar y la pantalla del correo la pide
de nuevo (ver `descifrar`).
"""

import base64
import hashlib
import hmac
import json
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
from backend import basedatos

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


CLAVE_PIN = "pin"


def _leer_pin():
    """La huella guardada en la cuenta, o `None` si la cuenta todavia no tiene PIN.

    Si la cuenta no tiene pero **este aparato** tiene una de antes —de cuando
    vivia en cada aparato—, se sube a la cuenta y se borra de aca. Asi nadie
    tiene que volver a crear su perfil al actualizar. Si dos aparatos tenian PIN
    distintos, queda el del primero que se abra.
    """
    texto = basedatos.leer_config(CLAVE_PIN)
    if texto:
        try:
            return json.loads(texto)
        except ValueError:
            return None
    viejo = almacenamiento.obtener(CLAVE_PIN)
    if viejo:
        _guardar_pin(viejo)
        almacenamiento.borrar(CLAVE_PIN)
        return viejo
    return None


def _guardar_pin(datos):
    basedatos.escribir_config(CLAVE_PIN, json.dumps(datos))


def huella_guardada():
    """Lo que queda guardado del PIN. Para las pruebas: que no este en claro."""
    return _leer_pin()


def hay_pin():
    return bool(_leer_pin())


def establecer(pin, repeticion=None):
    """Guarda la huella del PIN y **abre la sesion**: deja lista la llave de
    cifrado, para que lo que se guarde a continuacion se pueda cifrar."""
    pin = validar_propuesta(pin, repeticion)
    sal = os.urandom(16)
    # Dos sales distintas a proposito: si fueran la misma, la huella guardada en
    # claro seria una pista sobre la llave que cifra los secretos.
    sal_cifrado = os.urandom(16)
    guardado = {
        "sal": sal.hex(),
        "sal_cifrado": sal_cifrado.hex(),
        "vueltas": VUELTAS,
        "huella": _derivar(pin, sal).hex(),
    }
    _guardar_pin(guardado)
    _abrir_sesion(pin, guardado)


def verificar(pin):
    guardado = _leer_pin()
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
    _abrir_sesion((pin or "").strip(), guardado)
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

def _abrir_sesion(pin, guardado):
    """Deriva la llave de cifrado y la deja en memoria mientras dure la sesion.

    Sin `cryptography` no hay llave que derivar: el PIN ya se comprobo con su
    huella y se entra igual. Lo unico que queda sin funcionar es guardar secretos.
    """
    global _llave
    if not CIFRADO_DISPONIBLE:
        return
    hexa = guardado.get("sal_cifrado")
    if not hexa:
        # Base creada antes de que existiera el cifrado: se le agrega la sal ahora.
        # No se puede reusar la del PIN sin debilitar las dos.
        sal_cifrado = os.urandom(16)
        guardado["sal_cifrado"] = sal_cifrado.hex()
        _guardar_pin(guardado)
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
