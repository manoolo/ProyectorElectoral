"""EEUU, elecciones de medio término: Senado y gobernaciones por condado.

Resultados 2022 por precinto de MEDSL (github.com/MEDSL/2022-elections-official, un zip por estado),
agregados por condado. La base es la presidencial por condado del ciclo anterior (adapters/us.py).

  python -m adapters.us_mid senado 2022 carpeta_zips      # arma data/us_sen2022.csv (para el backtest)
  python -m adapters.us_mid base 2024                      # base 2026: presidencial 2024 por condado

Cada carrera es una región (el estado; las especiales llevan sufijo, p. ej. OK-E). Los candidatos se
agrupan por partido: gop, dem y oth. Si una carrera no tiene demócrata (Utah 2022 con McMullin,
Nebraska 2026 con Osborn), el independiente más votado ocupa el lugar del demócrata.
"""
import sys, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from adapters.us import load_year, centroids, GROUPS

DATA = Path(__file__).resolve().parent.parent / "data"
OFFICES = {"senado": "US SENATE", "gobernador": "GOVERNOR"}
SKIP = {"AK"}          # Alaska: voto por ranking y sin condados
# MEDSL no trae el Senado 2022 de California (sí la gobernación)


def medsl_state(zpath, office):
    """Votos por condado y candidato de una carrera estatal, con el grupo de cada candidato."""
    z = zipfile.ZipFile(zpath)
    cols = ["office", "party_simplified", "mode", "votes", "county_fips", "candidate", "stage", "special", "state_po"]
    d = pd.read_csv(z.open(z.namelist()[0]), dtype=str, usecols=cols, low_memory=False)
    d = d[(d.office == office) & (d.stage == "GEN") & d.county_fips.notna()].copy()
    if d.empty:
        return d
    d["votes"] = pd.to_numeric(d.votes, errors="coerce").fillna(0)
    d["party_simplified"] = d.party_simplified.fillna("OTHER")
    d["candidate"] = d.candidate.fillna("OTROS")
    d["county_fips"] = d.county_fips.str.zfill(5)
    # modos: si un condado informa TOTAL, sólo ese; si no, la suma de los modos
    has_tot = d.groupby("county_fips")["mode"].transform(lambda m: (m == "TOTAL").any())
    d = d[~has_tot | (d["mode"] == "TOTAL")]
    # filas que no son votos a candidatos (NY trae contadores de boletas como si fueran candidatos)
    junk = d.candidate.str.upper().str.contains(r"OVER ?VOTE|UNDER ?VOTE|BLANK|VOID|COUNTER|AFFIDAVIT|ABSENTEE|MILITARY|"
                                                r"REGISTERED|BALLOTS CAST|TOTAL VOTES|^TOTAL$", regex=True)
    d = d[~junk]
    st = d.state_po.iloc[0]
    d["race"] = np.where(d.special.str.upper() == "TRUE", st + "-E", st)
    # grupo del candidato: demócrata o republicano si alguna de sus líneas lo es (fusión en NY, CT)
    pc = d.groupby(["race", "candidate", "party_simplified"]).votes.sum().unstack(fill_value=0)
    grp = pd.Series("oth", index=pc.index)
    for p, g in (("REPUBLICAN", "gop"), ("DEMOCRAT", "dem")):
        if p in pc:
            grp[pc[p] > 0] = g
    tot = pc.sum(axis=1)
    for race in grp.index.get_level_values(0).unique():
        r = grp.loc[race]
        if not (r == "dem").any():                       # sin demócrata: el independiente más votado
            alt = tot.loc[race][r != "gop"]
            if len(alt):
                grp.loc[(race, alt.idxmax())] = "dem"
    g = grp.to_dict()
    d["group"] = [g.get((r, c), "oth") for r, c in zip(d.race, d.candidate)]
    return d


def races(zdir, office, year=2022):
    """Todas las carreras de un cargo: unit (fips, con sufijo si es especial), region (carrera), gop, dem, oth."""
    rows, names = [], {}
    for zp in sorted(Path(zdir).glob(f"{year}-*-local-precinct-general.zip")):
        d = medsl_state(zp, OFFICES[office])
        if d.empty or d.state_po.iloc[0] in SKIP:
            continue
        rows.append(d.groupby(["race", "county_fips", "group"]).votes.sum().unstack(fill_value=0).reset_index())
        top = d.groupby(["race", "group", "candidate"]).votes.sum().reset_index().sort_values("votes")
        for r, g, c in top[["race", "group", "candidate"]].itertuples(index=False):
            names[(r, g)] = c.title()
    df = pd.concat(rows, ignore_index=True).fillna(0)
    for g in GROUPS:
        if g not in df:
            df[g] = 0.0
    df["unit"] = df.county_fips + np.where(df.race.str.endswith("-E"), "e", "")
    df = df.rename(columns={"race": "region"})[["unit", "region"] + GROUPS]
    return df, names


def pvi_year(year, prev=None, w=0.75):
    """Presidencial por condado con el criterio del PVI de Cook: shares de la última (`year`) y la
    anterior mezclados 75/25, con el volumen de votos de la última. prev=None: la de 4 años antes."""
    b = load_year(year).set_index("unit")
    b[GROUPS] = b[GROUPS].astype(float)
    if prev is False:
        return b.reset_index()
    a = load_year(prev or year - 4).set_index("unit")
    common = b.index.intersection(a.index)
    sb = b.loc[common, GROUPS].div(b.loc[common, GROUPS].sum(axis=1), axis=0)
    sa = a.loc[common, GROUPS].div(a.loc[common, GROUPS].sum(axis=1), axis=0)
    mix = (w * sb + (1 - w) * sa.fillna(sb)).mul(b.loc[common, GROUPS].sum(axis=1), axis=0)
    b.loc[common, GROUPS] = mix.to_numpy()
    return b.reset_index()


def pair(base_year, target: pd.DataFrame, pvi=False):
    """Base presidencial por condado alineada con las carreras de `target` (misma lógica que adapters.us.pair:
    los condados que no existen en ambos lados se juntan en un 'resto' por carrera)."""
    b = pvi_year(base_year) if pvi else load_year(base_year)
    out_b, out_t = [], []
    for race, t in target.groupby("region"):
        st = race.split("-")[0]
        bb = b[b.region == st].copy()
        suf = "e" if race.endswith("-E") else ""
        bb["unit"] = bb.unit + suf
        bb["region"] = race
        t = t.copy()
        common = set(bb.unit) & set(t.unit)
        for d in (bb, t):
            m = ~d.unit.isin(common)
            d.loc[m, "unit"] = race + "-resto"
        bb = bb.groupby(["unit", "region"], as_index=False)[GROUPS].sum()
        t = t.groupby(["unit", "region"], as_index=False)[GROUPS].sum()
        keep = set(bb.unit) & set(t.unit)
        out_b.append(bb[bb.unit.isin(keep)]); out_t.append(t[t.unit.isin(keep)])
    b, t = pd.concat(out_b, ignore_index=True), pd.concat(out_t, ignore_index=True)
    b = add_coords(b)
    t["frac"] = 1.0
    t = t.set_index("unit").loc[b.unit].reset_index()
    return b, t


def add_coords(b):
    cen = centroids()
    key = b.unit.str[:5]
    b = b.assign(_k=key).merge(cen.rename(columns={"unit": "_k"}), on="_k", how="left").drop(columns="_k")
    st = b.groupby("region")[["lat", "lon"]].transform("mean")
    b[["lat", "lon"]] = b[["lat", "lon"]].fillna(st)
    return b


def base_2026(year=2024, states=None, pvi=False):
    """Base para 2026: presidencial `year` por condado de los estados con carrera.
    states: lista de carreras ('OH', 'FL', ...); Nebraska y demás van igual, con el grupo dem como 'no republicano'."""
    b = pvi_year(year) if pvi else load_year(year)
    out = []
    for race in states:
        bb = b[b.region == race.split("-")[0]].copy()
        if race.endswith("-E"):
            bb["unit"] = bb.unit + "e"
        bb["region"] = race
        out.append(bb)
    return add_coords(pd.concat(out, ignore_index=True))


if __name__ == "__main__":
    if sys.argv[1] in OFFICES:
        office, year, zdir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
        df, names = races(zdir, office, year)
        key = {"senado": "sen", "gobernador": "gob"}[office]
        df.to_csv(DATA / f"us_{key}{year}.csv", index=False)
        pd.DataFrame([(r, g, c) for (r, g), c in names.items()], columns=["region", "group", "candidate"]) \
          .to_csv(DATA / f"us_{key}{year}_candidatos.csv", index=False)
        print(f"{len(df)} condados en {df.region.nunique()} carreras → data/us_{key}{year}.csv")
