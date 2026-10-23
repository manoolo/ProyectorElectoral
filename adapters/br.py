"""Brasil: arma la base canónica (presidente, 1er turno 2022) por municipio.

Fuentes que entiende:
  1) CSV por municipio con columnas votos_<candidato> y codigo_ibge/latitude/longitude
     (formato del gist BurgosNY/7c43bf0786b3535d213dc9f498523fbe, datos del G1 al 100%).
  2) CSV oficial del TSE 'votacao_candidato_munzona_2022_BR.csv' (Portal de Dados Abertos),
     separador ';', latin-1. Se agrega por municipio y se cruza con coordenadas IBGE.
     Revisá los nombres de columnas si el TSE cambió el formato.
Grupos base: lula, bolsonaro, otros.
"""
from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
UF = {11: 'RO', 12: 'AC', 13: 'AM', 14: 'RR', 15: 'PA', 16: 'AP', 17: 'TO', 21: 'MA', 22: 'PI', 23: 'CE', 24: 'RN',
      25: 'PB', 26: 'PE', 27: 'AL', 28: 'SE', 29: 'BA', 31: 'MG', 32: 'ES', 33: 'RJ', 35: 'SP', 41: 'PR', 42: 'SC',
      43: 'RS', 50: 'MS', 51: 'MT', 52: 'GO', 53: 'DF'}
GROUPS = ["lula", "bolsonaro", "otros"]


def from_gist(path):
    df = pd.read_csv(path)
    vcols = [c for c in df.columns if c.startswith("votos_")]
    lula = [c for c in vcols if "Lula" in c]
    bolso = [c for c in vcols if "Bolsonaro" in c]
    out = pd.DataFrame({"unit": df["codigo_ibge"].astype(str), "region": df["codigo_uf"].map(UF),
                        "lat": df["latitude"], "lon": df["longitude"],
                        "lula": df[lula].sum(1), "bolsonaro": df[bolso].sum(1)})
    out["otros"] = df[vcols].sum(1) - out.lula - out.bolsonaro
    return out


TSE_ZIP = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_{y}.zip"


def descargar(year: int) -> Path:
    """Baja el zip oficial del TSE (votação nominal por município e zona). Correr en tu máquina:
    desde el entorno donde se armó este proyecto el dominio del TSE está bloqueado."""
    import urllib.request
    dest = DATA / f"votacao_candidato_munzona_{year}.zip"
    if not dest.exists():
        print(f"bajando {TSE_ZIP.format(y=year)} …")
        urllib.request.urlretrieve(TSE_ZIP.format(y=year), dest)
    return dest


def _read_tse(path) -> pd.DataFrame:
    """Lee el CSV del TSE; acepta el zip completo (usa el archivo _BR si está, si no junta las UF)."""
    import zipfile
    path = Path(path)
    if path.suffix != ".zip":
        return pd.read_csv(path, sep=";", encoding="latin-1", dtype=str)
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        br = [n for n in names if n.upper().endswith("_BR.CSV")]
        use = br or names
        return pd.concat([pd.read_csv(z.open(n), sep=";", encoding="latin-1", dtype=str) for n in use], ignore_index=True)


def from_tse(path, turno=1):
    df = _read_tse(path)
    df = df[(df["DS_CARGO"].str.upper() == "PRESIDENTE") & (df["NR_TURNO"] == str(turno))]
    col = "QT_VOTOS_NOMINAIS_VALIDOS" if "QT_VOTOS_NOMINAIS_VALIDOS" in df else "QT_VOTOS_NOMINAIS"
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    nm = df["NM_URNA_CANDIDATO"].str.upper()
    df["g"] = "otros"
    df.loc[nm.str.contains("LULA") | nm.str.contains("HADDAD"), "g"] = "lula"     # PT: Haddad en 2018
    df.loc[nm.str.contains("BOLSONARO"), "g"] = "bolsonaro"
    df = df[df["SG_UF"] != "ZZ"]                            # exterior: fuera del modelo
    piv = df.pivot_table(index=["CD_MUNICIPIO", "SG_UF"], columns="g", values=col, aggfunc="sum", fill_value=0).reset_index()
    xw = pd.read_csv(DATA / "br_tse_ibge.csv", dtype=str)   # betafcc/Municipios-Brasileiros-TSE
    geo = pd.read_csv(DATA / "br_municipios.csv", dtype={"codigo_ibge": str})  # kelvins/municipios-brasileiros
    piv["CD_MUNICIPIO"] = piv["CD_MUNICIPIO"].str.lstrip("0")
    xw["codigo_tse"] = xw["codigo_tse"].str.lstrip("0")
    piv = piv.merge(xw[["codigo_tse", "codigo_ibge"]], left_on="CD_MUNICIPIO", right_on="codigo_tse", how="left")
    piv = piv.merge(geo[["codigo_ibge", "nome", "latitude", "longitude"]], on="codigo_ibge", how="left")
    return pd.DataFrame({"unit": piv["codigo_ibge"].fillna("tse" + piv["CD_MUNICIPIO"]), "region": piv["SG_UF"],
                         "name": piv["nome"].fillna(piv["CD_MUNICIPIO"]),
                         "lat": piv["latitude"], "lon": piv["longitude"],
                         "lula": piv.get("lula", 0), "bolsonaro": piv.get("bolsonaro", 0), "otros": piv.get("otros", 0)})


GROUPS_2T = ["lula", "bolsonaro"]


def pair_turnos(year: int = 2022):
    """Base = 1er turno, objetivo = 2º turno del mismo año, por municipio (para el backtest del balotaje).
    Sólo los dos finalistas: el cambio que se modela es el de su reparto y el de la participación."""
    z = descargar(year)
    b, t = from_tse(z, 1), from_tse(z, 2)
    common = set(b.unit) & set(t.unit)
    b, t = b[b.unit.isin(common)].reset_index(drop=True), t[t.unit.isin(common)].reset_index(drop=True)
    t = t[["unit", *GROUPS_2T]].copy(); t["frac"] = 1.0
    return b.drop(columns="otros"), t


def base_2t(primera_vuelta_csv, salida=DATA / "br_base_2t.csv"):
    """Base para el balotaje 2026: el 1er turno 2026 por municipio (bajado con
    `python -m adapters.br_live data/br_1t_2026.csv --turno 1`) con región y coordenadas de br_base.csv."""
    cur = pd.read_csv(primera_vuelta_csv, dtype={"unit": str})
    geo = pd.read_csv(DATA / "br_base.csv", dtype={"unit": str})[["unit", "region", "lat", "lon"]]
    b = cur.merge(geo, on="unit", how="inner")
    if len(b) < 0.95 * len(cur):
        print(f"aviso: sólo {len(b)} de {len(cur)} municipios cruzaron con br_base.csv")
    if (cur["frac"] < 0.999).any():
        print(f"aviso: {(cur['frac'] < 0.999).sum()} municipios no estaban escrutados al 100%")
    nomes = pd.read_csv(DATA / "br_municipios.csv", dtype={"codigo_ibge": str}).set_index("codigo_ibge")["nome"]
    out = pd.DataFrame({"unit": b.unit, "region": b.region, "name": b.unit.map(nomes).fillna(b.unit),
                        "lat": b.lat, "lon": b.lon, "lula": b["Lula"], "bolsonaro": b["Flávio Bolsonaro"]})
    out.to_csv(salida, index=False)
    print(f"{len(out)} municipios → {salida} (Lula {out.lula.sum():,.0f}, Flávio {out.bolsonaro.sum():,.0f})")


def pair(base_year: int = 2018, target_year: int = 2022):
    """Base y resultado final por municipio (1er turno), con los zips del TSE en data/."""
    b = from_tse(descargar(base_year))
    t = from_tse(descargar(target_year))
    common = set(b.unit) & set(t.unit)
    b, t = b[b.unit.isin(common)].reset_index(drop=True), t[t.unit.isin(common)].reset_index(drop=True)
    t = t[["unit", *GROUPS]].copy(); t["frac"] = 1.0
    return b, t


if __name__ == "__main__":
    # python -m adapters.br 2022            baja el zip del TSE y arma data/br_base.csv
    # python -m adapters.br archivo.csv      usa un archivo ya bajado (TSE o gist del G1)
    # python -m adapters.br base2t data/br_1t_2026.csv   arma data/br_base_2t.csv para el balotaje
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "2022"
    if arg == "base2t":
        base_2t(sys.argv[2]); sys.exit()
    if arg.isdigit():
        base = from_tse(descargar(int(arg)))
    else:
        src = Path(arg)
        base = from_tse(src) if "munzona" in src.name else from_gist(src)
    base.to_csv(DATA / "br_base.csv", index=False)
    print(f"{len(base)} municipios → data/br_base.csv")
