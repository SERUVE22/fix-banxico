#!/usr/bin/env python3
"""
FIX Banxico — pipeline diario para proyecto de trading.

Obtiene el tipo de cambio FIX (serie SF43718) del API del SIE de Banxico,
lo guarda en un histórico CSV sin duplicar días, calcula la variación
frente al dato anterior, alerta si rebasa umbrales y publica un latest.json
que el tablero web puede leer.

Uso:
    export BANXICO_TOKEN="tu_token"
    python fix_banxico.py

Opcionales (variables de entorno):
    FIX_UMBRAL_ALTO   -> alerta si el FIX cierra por encima (ej. 19.50)
    FIX_UMBRAL_BAJO   -> alerta si el FIX cierra por debajo (ej. 17.00)
    FIX_VAR_PCT       -> alerta si la variación diaria supera este % (ej. 1.0)
"""

import os
import csv
import json
import sys
from datetime import datetime

import requests

TOKEN = os.environ.get("BANXICO_TOKEN", "").strip()
SERIE = "SF43718"                      # FIX (fecha de determinación)
CSV_HIST = "fix_historico.csv"
JSON_LATEST = "latest.json"
BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1"


def obtener_fix():
    """Devuelve (fecha_str, valor_float) del último FIX publicado."""
    url = f"{BASE}/series/{SERIE}/datos/oportuno"
    r = requests.get(url, headers={"Bmx-Token": TOKEN}, timeout=20)
    r.raise_for_status()
    dato = r.json()["bmx"]["series"][0]["datos"][0]
    return dato["fecha"], float(dato["dato"].replace(",", ""))


def dato_anterior():
    """Lee el último valor guardado en el histórico, o None si no hay."""
    if not os.path.isfile(CSV_HIST):
        return None
    with open(CSV_HIST, newline="", encoding="utf-8") as f:
        filas = [fila for fila in csv.reader(f) if fila]
    if len(filas) <= 1:                # solo encabezado
        return None
    ultima = filas[-1]
    return {"fecha": ultima[0], "fix": float(ultima[1])}


def ya_registrado(fecha):
    if not os.path.isfile(CSV_HIST):
        return False
    with open(CSV_HIST, newline="", encoding="utf-8") as f:
        return any(fila and fila[0] == fecha for fila in csv.reader(f))


def guardar_csv(fecha, valor):
    nuevo = not os.path.isfile(CSV_HIST)
    with open(CSV_HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha", "fix", "registrado_utc"])
        w.writerow([fecha, valor, datetime.utcnow().isoformat(timespec="seconds")])


def historial_reciente(n=30):
    """Últimos n puntos para el sparkline del tablero."""
    if not os.path.isfile(CSV_HIST):
        return []
    with open(CSV_HIST, newline="", encoding="utf-8") as f:
        filas = [fila for fila in csv.reader(f) if fila][1:]  # sin encabezado
    puntos = [{"fecha": fila[0], "fix": float(fila[1])} for fila in filas[-n:]]
    return puntos


def revisar_alertas(valor, variacion_pct):
    """Devuelve lista de mensajes de alerta según umbrales configurados."""
    alertas = []
    alto = os.environ.get("FIX_UMBRAL_ALTO")
    bajo = os.environ.get("FIX_UMBRAL_BAJO")
    var_lim = os.environ.get("FIX_VAR_PCT")

    if alto and valor > float(alto):
        alertas.append(f"FIX {valor:.4f} por ENCIMA del umbral {float(alto):.4f}")
    if bajo and valor < float(bajo):
        alertas.append(f"FIX {valor:.4f} por DEBAJO del umbral {float(bajo):.4f}")
    if var_lim and variacion_pct is not None and abs(variacion_pct) > float(var_lim):
        alertas.append(
            f"Variación diaria {variacion_pct:+.2f}% supera ±{float(var_lim):.2f}%"
        )
    return alertas


def main():
    if not TOKEN:
        sys.exit("ERROR: define la variable de entorno BANXICO_TOKEN.")

    fecha, valor = obtener_fix()

    if ya_registrado(fecha):
        print(f"{fecha}: FIX {valor:.4f} ya estaba registrado. Sin cambios.")
    else:
        prev = dato_anterior()
        variacion_abs = variacion_pct = None
        if prev:
            variacion_abs = valor - prev["fix"]
            variacion_pct = variacion_abs / prev["fix"] * 100
        guardar_csv(fecha, valor)
        print(f"{fecha}: FIX {valor:.4f} guardado.", end=" ")
        if variacion_pct is not None:
            print(f"Variación {variacion_abs:+.4f} ({variacion_pct:+.2f}%)")
        else:
            print("(primer registro)")

        for a in revisar_alertas(valor, variacion_pct):
            print(f"  ⚠️  ALERTA: {a}")

    # Publicar latest.json para el tablero (siempre, con lo más reciente)
    prev = dato_anterior()
    hist = historial_reciente(30)
    variacion_pct = None
    if len(hist) >= 2:
        variacion_pct = (hist[-1]["fix"] - hist[-2]["fix"]) / hist[-2]["fix"] * 100

    payload = {
        "serie": SERIE,
        "fuente": "Banco de México (SIE)",
        "fecha": fecha,
        "fix": valor,
        "variacion_pct": round(variacion_pct, 4) if variacion_pct is not None else None,
        "actualizado_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "historial": hist,
    }
    with open(JSON_LATEST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Publicado {JSON_LATEST} con {len(hist)} puntos de histórico.")


if __name__ == "__main__":
    main()
