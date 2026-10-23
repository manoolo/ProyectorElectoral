"""Formato común que entiende el motor.

base.csv     unit, region, [lat, lon], <grupo_1>, <grupo_2>, ...   (votos válidos de la elección base)
current.csv  unit, frac, <candidato_1>, <candidato_2>, ...          (escrutinio en curso; frac = 0-1)

`unit` tiene que ser la misma clave en ambos archivos. `frac` es la fracción de mesas/secciones
escrutadas de esa unidad (1 si está completa). Sin lat/lon, el motor busca vecinos por parecido.
"""
import pandas as pd


def load_base(path, groups):
    df = pd.read_csv(path, dtype={"unit": str, "region": str})
    miss = {"unit", "region", *groups} - set(df.columns)
    if miss:
        raise ValueError(f"Faltan columnas en la base: {sorted(miss)}")
    return df


def load_current(path, candidates):
    df = pd.read_csv(path, dtype={"unit": str})
    miss = {"unit", "frac", *candidates} - set(df.columns)
    if miss:
        raise ValueError(f"Faltan columnas en el escrutinio: {sorted(miss)}")
    return df
