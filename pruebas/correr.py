"""Corre todas las suites de prueba de Vane's Store.

    python pruebas/correr.py

Cada suite trabaja contra una base temporal que crea y borra ella misma: ninguna
toca los datos reales de `app/datos/`.
"""
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))

SUITES = [
    ("Fase 1 · base, PIN e inventario", "probar_fase1.py"),
    ("Fase 2 · venta y stock", "probar_fase2.py"),
    ("Métodos de pago y reparto", "probar_pagos.py"),
    ("Fase 3 · clientes y cobros", "probar_fase3.py"),
    ("Fase 4 · métricas y gastos", "probar_fase4.py"),
    ("Fase 5 · catálogo y cifrado", "probar_fase5.py"),
    ("Fase 6 · respaldo en la nube", "probar_fase6.py"),
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
