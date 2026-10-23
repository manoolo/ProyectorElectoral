"""España en vivo: escrutinio provisional → formato canónico por municipio.

El canal del escrutinio del 29/11/2026 todavía no se conoce (en 2023 el Interior lo publicó en una
web y una app propias). Este conversor toma una tabla por municipio, CSV o el mismo zip de ficheros
.DAT del Interior (si se publica en ese formato), y hace el resto:

  CSV: una fila por municipio con `ine` (5 dígitos) o `prov` + `muni`, `escrutado` (fracción 0-1 o
       porcentaje de mesas) y una columna de votos por candidatura, con sus siglas como encabezado.

  python -m adapters.es_live parcial.csv data/es_actual.csv && python run_live.py es data/es_actual.csv

Las siglas se asignan a las candidaturas de config/es.json: primero por `live_names` (siglas tal
como vienen → candidatura), si no por el grupo de 2023 (adapters/es.py). Podemos va aparte de Sumar.
"""
import json, re, sys
from pathlib import Path
import pandas as pd
from adapters.es import group_of, _norm

ROOT = Path(__file__).resolve().parent.parent


def candidatura(siglas, cfg):
    names = cfg.get("live_names", {})
    s = _norm(siglas)
    for k, c in names.items():
        if _norm(k) == s:
            return c
    if re.search(r"PODEMOS", s) and "Podemos" in cfg["candidates"]:
        return "Podemos"
    g = group_of(siglas)
    return next((c for c, gg in cfg["candidates"].items() if gg == g), "Otros")


def convertir(parcial, salida):
    cfg = json.loads((ROOT / "config" / "es.json").read_text(encoding="utf-8"))
    df = pd.read_csv(parcial, dtype=str)
    unit = df["ine"].str.zfill(5) if "ine" in df else df["prov"].str.zfill(2) + df["muni"].str.zfill(3)
    frac = pd.to_numeric(df["escrutado"].str.replace(",", "."), errors="coerce").fillna(0)
    if frac.max() > 1.0001:
        frac = frac / 100
    out = pd.DataFrame({"unit": unit, "frac": frac.clip(0, 1)})
    for c in cfg["candidates"]:
        out[c] = 0.0
    sin = []
    for col in df.columns:
        if col in ("ine", "prov", "muni", "escrutado", "nombre", "municipio"):
            continue
        c = candidatura(col, cfg)
        if c == "Otros" and cfg["candidates"].get("Otros"):
            sin.append(col)
        out[c] += pd.to_numeric(df[col], errors="coerce").fillna(0)
    out = out.groupby("unit", as_index=False).agg({"frac": "max", **{c: "sum" for c in cfg["candidates"]}})
    out.to_csv(salida, index=False)
    print(f"{(out.frac > 0).sum()} municipios con datos → {salida}" + (f" · a Otros: {', '.join(sin[:8])}" if sin else ""))


if __name__ == "__main__":
    convertir(sys.argv[1], sys.argv[2])
