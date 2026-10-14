"""La conexion con Supabase: la sesion y las llamadas a las funciones.

Toda la app habla con Supabase por **dos puertas**, y las dos viven aca:

- **La sesion** (`/auth/v1/token`): correo y contrasena una sola vez por
  telefono. Lo que queda guardado es el *refresh token*, no la contrasena: con el
  se pide una sesion nueva cada vez que la anterior vence (dura una hora).
- **Las funciones** (`/rest/v1/rpc/<nombre>`): cada operacion de
  `basedatos.py` es una funcion de `supabase/02_funciones.sql` con el mismo
  nombre. Una llamada, una ida y vuelta.

**Por que llamadas sincronicas.** Todo el codigo de la app esta escrito para una
base que responde en el acto (`registrar_venta(...)` devuelve la venta). Para no
reescribirlo, la llamada espera la respuesta. En la computadora y en Android eso
es `http.client`; en el navegador, `XMLHttpRequest` en modo sincronico, que esta
permitido porque Flet corre Python dentro de un *worker*, no en la pagina.
Comprobado en el mismo Pyodide 0.27.7 de la app, contra el proyecto real. En
la computadora y en Android se usa `http.client` con la conexion abierta, que
`urllib` no reusa.

**Las pruebas no tocan la red.** Ponen en `transporte` una funcion que llama a las
mismas funciones SQL en un Postgres local (ver `pruebas/postgres_local.py`).
"""

import json
import sys
import threading
import time

from backend import almacenamiento

URL = "https://vysrqhzlcwedebraptod.supabase.co"

# La clave **publicable**. Esta hecha para ir dentro de la app: cualquiera que
# abra la pagina web puede verla, igual que en toda app que usa Supabase. Por si
# sola no da acceso a nada; lo que protege los datos es el RLS del esquema, que
# sin una sesion iniciada no deja ver ni una fila. La que **nunca** puede estar
# aca es la secreta (`sb_secret_...`), que se salta el RLS.
CLAVE_PUBLICA = "sb_publishable_v-2SSgX2XdiSEe7mqMmzDA_x2MiMxH1"

EN_NAVEGADOR = sys.platform == "emscripten"

# Donde queda la sesion entre una apertura y otra. Ver `almacenamiento.py`.
CLAVE_SESION = "sesion_nube"

# Si se pone una funcion aca, `llamar` la usa en vez de la red. Solo las pruebas.
transporte = None

SIN_CONEXION = ("No hay conexión con el servidor. Revisa el internet y vuelve a "
                "intentar.")


class ErrorDeNube(ValueError):
    """Algo de la conexion que hay que contarle a la persona. El texto se muestra
    tal cual. Hereda de `ValueError` para que las pantallas, que ya muestran los
    `ValueError` en su aviso, lo muestren sin cambiar nada."""


class SinConexion(ErrorDeNube):
    """No se pudo llegar a Supabase: sin internet, o el servidor no respondio."""


class SinSesion(ErrorDeNube):
    """No hay sesion, o vencio y no se pudo renovar. Hay que volver a entrar."""


class ErrorRemoto(Exception):
    """Lo que devolvio una funcion al fallar. `basedatos` lo traduce."""

    def __init__(self, codigo, mensaje, pista=None):
        super().__init__(mensaje)
        self.codigo = codigo or ""
        self.mensaje = mensaje or ""
        self.pista = pista


# --------------------------------------------------------------------------
# El viaje por la red
# --------------------------------------------------------------------------

def _http(metodo, ruta, cuerpo=None, token=None, reintentable=False,
          archivo=None, tipo=None, extra=None):
    """Devuelve `(estado, texto)`. Un estado de error **no** es una excepcion:
    lo decide quien llama. Solo la falta de red lo es.

    `cuerpo` va como JSON; `archivo` (bytes) va tal cual, con su `tipo`, para
    subir un archivo. `reintentable` dice si se puede mandar dos veces sin dano
    (una lectura). Ver `_http_directo`."""
    encabezados = {"apikey": CLAVE_PUBLICA,
                   "Content-Type": tipo or "application/json"}
    if token:
        encabezados["Authorization"] = f"Bearer {token}"
    encabezados.update(extra or {})
    if archivo is not None:
        datos = archivo
    else:
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    if EN_NAVEGADOR:
        return _http_navegador(metodo, URL + ruta, datos, encabezados)
    return _http_directo(metodo, ruta, datos, encabezados, reintentable)


# **Una sola conexion, reusada.** Abrir una conexion segura cuesta tres idas y
# vueltas antes de mandar nada; medido desde Venezuela a este proyecto, una
# llamada con conexion nueva tardaba ~450 ms y con la conexion ya abierta ~250.
# El navegador ya la reusa solo; esto es para la computadora y Android.
_conexion = {"c": None, "usada": 0.0}
_candado = threading.Lock()        # Flet atiende los botones desde varios hilos

# El servidor cierra las conexiones que quedan quietas. Pasado este tiempo se
# abre una nueva en vez de arriesgarse a escribir en una ya cerrada.
QUIETA_MAXIMO = 20


def _http_directo(metodo, ruta, datos, encabezados, reintentable):
    """Si la conexion se corta, **solo se reintenta una lectura**. Una venta
    cortada a mitad de camino pudo haber llegado igual: mandarla de nuevo
    podria registrarla dos veces. Se avisa que no hubo conexion, y la persona
    mira el historial antes de volver a cobrar."""
    import http.client
    with _candado:
        for intento in (1, 2):
            if (_conexion["c"] is None
                    or time.monotonic() - _conexion["usada"] > QUIETA_MAXIMO):
                if _conexion["c"] is not None:
                    _conexion["c"].close()
                _conexion["c"] = http.client.HTTPSConnection(
                    URL.split("://", 1)[1], timeout=30)
            try:
                _conexion["c"].request(metodo, ruta, body=datos,
                                       headers=encabezados)
                respuesta = _conexion["c"].getresponse()
                texto = respuesta.read().decode("utf-8", "replace")
                _conexion["usada"] = time.monotonic()
                return respuesta.status, texto
            except (http.client.HTTPException, OSError):
                _conexion["c"].close()
                _conexion["c"] = None
                if not reintentable or intento == 2:
                    raise SinConexion(SIN_CONEXION) from None


def _http_navegador(metodo, url, datos, encabezados):
    from js import XMLHttpRequest
    pedido = XMLHttpRequest.new()
    pedido.open(metodo, url, False)      # False: espera la respuesta
    for nombre, valor in encabezados.items():
        pedido.setRequestHeader(nombre, valor)
    try:
        if datos is None:
            pedido.send()
        else:
            # Los bytes de Python no cruzan solos al navegador: `to_js` los
            # convierte en un Uint8Array, que XMLHttpRequest manda tal cual.
            from pyodide.ffi import to_js
            pedido.send(to_js(datos))
    except Exception:
        raise SinConexion(SIN_CONEXION) from None
    if pedido.status == 0:               # el navegador no llego al servidor
        raise SinConexion(SIN_CONEXION)
    return pedido.status, pedido.responseText


def _json(texto):
    try:
        return json.loads(texto) if texto else None
    except ValueError:
        return None


# --------------------------------------------------------------------------
# La sesion
# --------------------------------------------------------------------------

_sesion = {"token": None, "vence": 0.0, "refresh": None, "correo": None,
          "usuario": None}


def _quedarse_con(respuesta):
    """Guarda la sesion que devolvio Supabase. El *refresh token* **cambia cada
    vez** que se usa —el viejo deja de servir—, asi que hay que guardar el nuevo
    siempre, o la proxima apertura pide la contrasena de nuevo."""
    usuario = respuesta.get("user") or {}
    _sesion.update(
        token=respuesta["access_token"],
        vence=time.time() + float(respuesta.get("expires_in") or 3600),
        refresh=respuesta["refresh_token"],
        correo=usuario.get("email") or _sesion["correo"],
        usuario=usuario.get("id") or _sesion["usuario"],
    )
    almacenamiento.guardar(CLAVE_SESION, {"refresh": _sesion["refresh"],
                                          "correo": _sesion["correo"]})


def _olvidar():
    _sesion.update(token=None, vence=0.0, refresh=None)
    almacenamiento.guardar(CLAVE_SESION, None)


def iniciar(correo, clave):
    """Entra con correo y contrasena. Lanza `ErrorDeNube` con un texto para la
    pantalla si no se puede."""
    correo = (correo or "").strip()
    if not correo or not clave:
        raise ErrorDeNube("Escribe tu correo y tu contraseña.")
    estado, texto = _http("POST", "/auth/v1/token?grant_type=password",
                          {"email": correo, "password": clave})
    respuesta = _json(texto) or {}
    if estado == 200:
        _quedarse_con(respuesta)
        return
    codigo = respuesta.get("error_code") or respuesta.get("error") or ""
    if codigo in ("invalid_credentials", "invalid_grant"):
        raise ErrorDeNube("Correo o contraseña incorrectos.")
    if estado == 429:
        raise ErrorDeNube("Demasiados intentos seguidos. Espera un minuto y "
                          "vuelve a intentar.")
    raise ErrorDeNube("No se pudo entrar. Intenta de nuevo en un momento.")


def reanudar():
    """Recupera la sesion guardada sin pedir la contrasena. `True` si se pudo.

    `False` si no habia sesion o ya no sirve (se cerro, o se cambio la
    contrasena desde el panel). Sin internet **lanza** `SinConexion`: no es lo
    mismo que una sesion vencida, y la pantalla tiene que decir cual de los dos.
    """
    guardada = almacenamiento.obtener(CLAVE_SESION) or {}
    if not guardada.get("refresh"):
        return False
    _sesion["correo"] = guardada.get("correo")
    _sesion["refresh"] = guardada["refresh"]
    return _renovar()


def _renovar():
    estado, texto = _http("POST", "/auth/v1/token?grant_type=refresh_token",
                          {"refresh_token": _sesion["refresh"]})
    if estado == 200:
        _quedarse_con(_json(texto) or {})
        return True
    if 400 <= estado < 500:
        _olvidar()
        return False
    raise SinConexion(SIN_CONEXION)


def cerrar_sesion():
    """Cierra la sesion aca y en Supabase. Si no hay red, igual la olvida aca."""
    token = _sesion["token"]
    _olvidar()
    if token:
        try:
            _http("POST", "/auth/v1/logout", {}, token=token)
        except SinConexion:
            pass


def hay_sesion():
    return bool(_sesion["token"])


def correo():
    """El correo de la cuenta abierta (o de la ultima que se uso en el telefono)."""
    return _sesion["correo"] or (almacenamiento.obtener(CLAVE_SESION) or {}).get("correo")


def _token():
    """El token vigente, renovado si esta por vencer."""
    if not _sesion["refresh"]:
        raise SinSesion("La sesión se cerró. Vuelve a entrar con tu correo.")
    if not _sesion["token"] or time.time() > _sesion["vence"] - 60:
        if not _renovar():
            raise SinSesion("La sesión venció. Vuelve a entrar con tu correo.")
    return _sesion["token"]


# --------------------------------------------------------------------------
# Las funciones
# --------------------------------------------------------------------------

def llamar(nombre, datos=None, lectura=False):
    """Llama a la funcion `nombre` de `02_funciones.sql` y devuelve su resultado.

    `lectura=True` permite reintentarla si se corta la conexion (ver
    `_http_directo`). Si falla, lanza `ErrorRemoto` con el codigo, el mensaje y
    la pista de Postgres; `basedatos` decide que significa para la pantalla.
    """
    datos = datos or {}
    if transporte is not None:
        return transporte(nombre, datos)

    estado, texto = _http("POST", f"/rest/v1/rpc/{nombre}", {"p": datos},
                          token=_token(), reintentable=lectura)
    if estado == 401 and _renovar():
        # El token vencio entre que se miro la hora y llego el pedido. Un 401
        # quiere decir que no se ejecuto nada: repetirlo es seguro.
        estado, texto = _http("POST", f"/rest/v1/rpc/{nombre}", {"p": datos},
                              token=_sesion["token"], reintentable=lectura)
    if 200 <= estado < 300:
        return _json(texto)
    if estado == 401:
        raise SinSesion("La sesión venció. Vuelve a entrar con tu correo.")
    error = _json(texto) or {}
    raise ErrorRemoto(error.get("code"), error.get("message") or texto[:200],
                      error.get("hint"))


# --------------------------------------------------------------------------
# Archivos para descargar (Supabase Storage)
# --------------------------------------------------------------------------
#
# En el iPhone, Safari solo deja bajar un archivo si la orden sale dentro del
# toque. Lo que si se puede dentro del toque es abrir un enlace. Por eso el
# archivo se sube aca y se baja con un enlace firmado: ver
# `supabase/03_descargas.sql` y `frontend/descargas.py`.

CARPETA = "descargas"


def _ruta_propia(nombre):
    """`<usuario>/<nombre>`: el RLS solo deja tocar la carpeta propia."""
    _token()                         # de paso, deja la sesion vigente
    if not _sesion["usuario"]:
        raise SinSesion("La sesión se cerró. Vuelve a entrar con tu correo.")
    return f"{_sesion['usuario']}/{nombre}"


def subir_archivo(nombre, datos, tipo):
    """Sube `datos` a la carpeta propia, reemplazando el que hubiera."""
    ruta = _ruta_propia(nombre)
    estado, texto = _http("POST", f"/storage/v1/object/{CARPETA}/{ruta}",
                          token=_token(), archivo=datos, tipo=tipo,
                          extra={"x-upsert": "true"})
    if not 200 <= estado < 300:
        error = _json(texto) or {}
        raise ErrorDeNube("No se pudo preparar el archivo. "
                          f"({error.get('message') or estado})")


def enlace_de_descarga(nombre, nombre_visible, segundos=3600):
    """Un enlace que baja el archivo con `nombre_visible` y vence en `segundos`.

    Sirve sin sesion —por eso se puede abrir en el navegador—, pero solo hasta
    que vence, y nadie mas lo conoce.
    """
    from urllib.parse import quote
    ruta = _ruta_propia(nombre)
    estado, texto = _http("POST", f"/storage/v1/object/sign/{CARPETA}/{ruta}",
                          {"expiresIn": segundos}, token=_token())
    respuesta = _json(texto) or {}
    firmado = respuesta.get("signedURL") or respuesta.get("signedUrl")
    if not 200 <= estado < 300 or not firmado:
        raise ErrorDeNube("No se pudo preparar el enlace de descarga. "
                          f"({respuesta.get('message') or estado})")
    separador = "&" if "?" in firmado else "?"
    return (f"{URL}/storage/v1{firmado}{separador}"
            f"download={quote(nombre_visible)}")
