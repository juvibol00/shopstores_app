"""Corre todas las suites de prueba de ShopStore's.

    python pruebas/correr.py

Los datos de la app viven en Supabase, y las pruebas **no lo tocan**: aca se
levanta un Postgres de usar y tirar (ver `postgres_local.py`) y cada suite crea
su propia base vacia dentro, con las mismas funciones que se pegan en el panel.
Hace falta tener PostgreSQL instalado; no se usa ningun servidor que ya este
corriendo.
"""
import os
import subprocess
import sys

import postgres_local

AQUI = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    ("Fase 1 · base, PIN e inventario", "probar_fase1.py"),
    ("Fase 2 · venta y stock", "probar_fase2.py"),
    ("Métodos de pago y reparto", "probar_pagos.py"),
    ("Fase 3 · clientes y cobros", "probar_fase3.py"),
    ("Fase 4 · métricas y gastos", "probar_fase4.py"),
    ("Fase 5 · correo y cifrado", "probar_fase5.py"),
    # Fase 6 (respaldo en archivo) sale hasta que el respaldo se rehaga contra
    # Supabase: copiaba el archivo de SQLite del telefono, que ya no existe.
    ("Los botones hacen lo que dicen", "probar_botones.py"),
]

# Primero la revisión estática: encuentra nombres que no existen sin ejecutar
# nada, que es justo lo que las suites no ven porque no pulsan los botones.
revision = subprocess.run([sys.executable, os.path.join(AQUI, "revisar.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
print((revision.stdout or "").strip())
if revision.returncode != 0:
    sys.exit(1)
print()

# Un solo servidor para todas: cada suite lo encuentra por la variable que deja
# esto, y se apaga solo al terminar.
postgres_local.levantar()

fallaron = []
for titulo, archivo in SUITES:
    r = subprocess.run([sys.executable, os.path.join(AQUI, archivo)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    ultima = [l for l in (r.stdout or "").strip().splitlines() if l.strip()]
    estado = ultima[-1] if ultima else "sin salida"
    print(f"{titulo:38} {estado}")
    if r.returncode != 0:
        fallaron.append((titulo, r.stdout, r.stderr))

if fallaron:
    print()
    for titulo, salida, error in fallaron:
        print(f"===== {titulo} =====")
        print("\n".join(l for l in salida.splitlines() if "FALLA" in l))
        if error.strip():
            print(error.strip()[-1500:])
    sys.exit(1)
print("\nTodas las suites pasan.")
