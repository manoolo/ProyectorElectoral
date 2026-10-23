"""Argentina en vivo: escrutinio provisorio parcial → formato canónico por circuito.

El formato del escrutinio provisorio 2027 todavía no se conoce. Este conversor supone lo
mismo que publicó la DINE en 2023: filas por mesa y agrupación, con columnas de distrito,
sección, circuito, mesa, cargo, agrupación, tipo de voto y cantidad. Si el feed cambia,
alcanza con pasar los nombres de columna correctos (ver `from_dine`).

  python -m adapters.ar_live parcial.csv data/ar_actual.csv && python run_live.py ar data/ar_actual.csv

El avance por circuito (frac) es mesas escrutadas / mesas del circuito en la base. Para eso
la base tiene que haberse armado con `python -m adapters.ar <csv DINE 2023>`, que guarda la
cantidad de mesas por circuito.
"""
import json, sys
from pathlib import Path
import pandas as pd
from adapters.ar import from_dine

ROOT = Path(__file__).resolve().parent.parent


def convertir(parcial, salida, **cols):
    cfg = json.loads((ROOT / "config" / "ar.json").read_text())
    base = pd.read_csv(ROOT / cfg["base"], dtype={"unit": str})
    if "mesas" not in base:
        raise SystemExit("La base no tiene la cantidad de mesas por circuito; rearmala con python -m adapters.ar <csv DINE>.")
    cur = from_dine(parcial, party_map=cfg["party_map"], **cols)
    cur = cur.merge(base[["unit", "mesas"]].rename(columns={"mesas": "mesas_base"}), on="unit", how="left")
    cur["frac"] = (cur["mesas"] / cur["mesas_base"]).clip(0, 1).fillna(1.0)
    inv = {g: c for c, g in cfg["candidates"].items()}
    cur = cur.rename(columns=inv)
    cur[["unit", "frac", *cfg["candidates"]]].to_csv(salida, index=False)
    print(f"{len(cur)} circuitos con datos → {salida}")


if __name__ == "__main__":
    convertir(sys.argv[1], sys.argv[2])
