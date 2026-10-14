"""Un Postgres de usar y tirar, para que las pruebas no toquen Supabase.

La app ya no tiene base propia: cada operacion es una funcion SQL en Supabase.
Probar contra el proyecto real seria lento (0,3 s por llamada), ensuciaria la
cuenta y pediria una contrasena en la maquina. En cambio, aca se levanta un
Postgres en una carpeta temporal y se cargan **los mismos archivos** que se pegan
en el panel de Supabase (`supabase/01_esquema.sql` y `02_funciones.sql`), encima
de `simular_supabase.sql`, que pone lo que Supabase trae de fabrica.

Las llamadas entran como el rol `authenticated` y con un usuario fijado, igual que
una sesion de verdad: el RLS esta prendido y las pruebas pasan por el.

**Solo usa los programas de Postgres** (`initdb`, `pg_ctl`, `psql`); no toca
ningun servidor que ya este corriendo en la maquina ni pide contrasenas. Se busca
en `SHOPSTORES_PG_BIN`, despues en el PATH y despues en `C:\\Program Files`.

`correr.py` levanta un solo servidor para todas las suites (se pasa por
`SHOPSTORES_PG_PUERTO`); cada suite crea su propia base vacia dentro.
"""

import atexit
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import uuid

import pg8000.native

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVOS = [
    os.path.join(AQUI, "simular_supabase.sql"),
    os.path.join(RAIZ, "supabase", "01_esquema.sql"),
    os.path.join(RAIZ, "supabase", "02_funciones.sql"),
]
_SILENCIO = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
             "stdin": subprocess.DEVNULL}


def _programa(nombre):
    carpeta = os.environ.get("SHOPSTORES_PG_BIN")
    if carpeta:
        return os.path.join(carpeta, nombre)
    en_path = shutil.which(nombre)
    if en_path:
        return en_path
    for carpeta in sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin"),
                          reverse=True):
        candidato = os.path.join(carpeta, nombre + ".exe")
        if os.path.exists(candidato):
            return candidato
    raise RuntimeError(
        "No se encontro PostgreSQL para las pruebas. Instalalo o pon la carpeta "
        "de sus programas en SHOPSTORES_PG_BIN.")


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _responde(puerto):
    try:
        pg8000.native.Connection("postgres", host="127.0.0.1", port=puerto).close()
        return True
    except Exception:
        return False


def levantar():
    """El puerto de un servidor listo. Si `correr.py` ya levanto uno, se usa ese;
    si no, se levanta uno nuevo y se apaga al terminar este proceso."""
    ya = os.environ.get("SHOPSTORES_PG_PUERTO")
    if ya and _responde(int(ya)):
        return int(ya)

    carpeta = tempfile.mkdtemp(prefix="shopstores_pg_")
    subprocess.run([_programa("initdb"), "-D", carpeta, "-U", "postgres",
                    "-A", "trust", "-E", "UTF8", "--locale=C"],
                   check=True, **_SILENCIO)
    puerto = _puerto_libre()
    # La salida va a DEVNULL a proposito: si se hereda la consola, el proceso
    # del servidor la deja tomada y quien lo lanzo se queda esperando para
    # siempre. `fsync=off` porque es una base de prueba: velocidad sobre
    # durabilidad.
    subprocess.run([_programa("pg_ctl"), "-D", carpeta, "-w", "-l",
                    os.path.join(carpeta, "registro.log"), "-o",
                    f"-p {puerto} -c listen_addresses=127.0.0.1 -c fsync=off "
                    f"-c timezone=UTC", "start"], check=True, **_SILENCIO)

    def apagar():
        subprocess.run([_programa("pg_ctl"), "-D", carpeta, "-m", "immediate",
                        "stop"], **_SILENCIO)
        shutil.rmtree(carpeta, ignore_errors=True)

    atexit.register(apagar)
    os.environ["SHOPSTORES_PG_PUERTO"] = str(puerto)
    return puerto


def base_nueva():
    """Una base vacia con el esquema y las funciones. Devuelve `(puerto, nombre)`."""
    puerto = levantar()
    nombre = "prueba_" + uuid.uuid4().hex[:12]
    admin = pg8000.native.Connection("postgres", host="127.0.0.1", port=puerto)
    admin.run(f"create database {nombre}")
    # Como en Supabase: las fechas salen en UTC, no en la hora de esta maquina.
    admin.run(f"alter database {nombre} set timezone to 'UTC'")
    admin.close()
    for archivo in ARCHIVOS:
        r = subprocess.run([_programa("psql"), "-h", "127.0.0.1", "-p", str(puerto),
                            "-U", "postgres", "-d", nombre, "-q", "-X",
                            "-v", "ON_ERROR_STOP=1", "-f", archivo],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"{os.path.basename(archivo)} fallo:\n{r.stderr}")
    return puerto, nombre


_IDENTIFICADOR = re.compile(r"^[a-z_][a-z0-9_]*$")


class Transporte:
    """Hace lo mismo que la red, pero contra el Postgres local.

    Llama a `public.<nombre>(p)` como `authenticated` con el usuario fijado, y
    devuelve el JSON igual que lo devolveria Supabase. Los errores salen como
    `nube.ErrorRemoto` con el codigo, el mensaje y la pista de Postgres.
    """

    def __init__(self, puerto, base, usuario):
        self.c = pg8000.native.Connection("postgres", host="127.0.0.1",
                                          port=puerto, database=base)
        self.c.run("set role authenticated")
        self.c.run("select set_config('request.jwt.claim.sub', :u, false)",
                   u=usuario)

    def __call__(self, nombre, datos):
        from backend import nube
        if not _IDENTIFICADOR.match(nombre):
            raise ValueError(f"Nombre de funcion invalido: {nombre!r}")
        try:
            fila = self.c.run(f"select public.{nombre}(cast(:p as jsonb))::text",
                              p=json.dumps(datos))
        except pg8000.native.DatabaseError as ex:
            info = ex.args[0] if ex.args and isinstance(ex.args[0], dict) else {}
            raise nube.ErrorRemoto(info.get("C"), info.get("M") or str(ex),
                                   info.get("H")) from None
        valor = fila[0][0]
        return json.loads(valor) if valor is not None else None

    def cerrar(self):
        self.c.close()


class Sesion:
    """Lo que la app tendria con una sesion abierta: una base, un usuario y el
    transporte enchufado en `nube`. `sql` corre como dueno de la base, para que
    una prueba pueda acomodar algo (una fecha vieja) que la app no deja hacer."""

    def __init__(self):
        from backend import nube
        self.puerto, self.base = base_nueva()
        self.usuario = str(uuid.uuid4())
        self.admin = pg8000.native.Connection("postgres", host="127.0.0.1",
                                              port=self.puerto, database=self.base)
        self.admin.run("insert into auth.users (id) values (cast(:u as uuid))",
                       u=self.usuario)
        self.transporte = Transporte(self.puerto, self.base, self.usuario)
        nube.transporte = self.transporte

    def sql(self, consulta, **parametros):
        return self.admin.run(consulta, **parametros)

    def otro_usuario(self):
        """Un segundo dueno en la misma base. Para probar que no se ven entre si."""
        otro = str(uuid.uuid4())
        self.admin.run("insert into auth.users (id) values (cast(:u as uuid))",
                       u=otro)
        return Transporte(self.puerto, self.base, otro)


def conectar_la_app():
    """Lo que cada suite llama al empezar: base nueva, usuario nuevo, y la app
    apuntando ahi. Devuelve la `Sesion` por si la prueba necesita `sql`."""
    sesion = Sesion()
    from backend import basedatos
    basedatos.preparar_cuenta()
    return sesion
