"""EEUU: resultados presidenciales por condado (repo tonmcg/US_County_Level_Election_Results_08-24)
y centroides de condados (plotly/datasets geojson-counties-fips.json)."""
import json
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = "https://raw.githubusercontent.com/tonmcg/US_County_Level_Election_Results_08-24/master/{y}_US_County_Level_Presidential_Results.csv"

ABBR = {'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO',
        'Connecticut': 'CT', 'Delaware': 'DE', 'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA',
        'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
        'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA',
        'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT',
        'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM',
        'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
        'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD',
        'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
        'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY'}
GROUPS = ["gop", "dem", "oth"]


def load_year(y: int) -> pd.DataFrame:
    f = DATA / f"{y}_US_County_Level_Presidential_Results.csv"
    df = pd.read_csv(f if f.exists() else RAW.format(y=y), dtype=str)
    if "combined_fips" in df.columns:          # formato 2016
        df = df.rename(columns={"combined_fips": "fips", "state_abbr": "region"})
        df = df.drop_duplicates(subset=["region", "votes_gop", "votes_dem"])  # Alaska repetida
    else:
        df = df.rename(columns={"county_fips": "fips"})
        df["region"] = df["state_name"].map(ABBR)
    df["fips"] = df["fips"].str.zfill(5)
    for c in ["votes_gop", "votes_dem", "total_votes"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    nm = df["county_name"] if "county_name" in df else df.get("county_name", df["fips"])
    out = pd.DataFrame({"unit": df["fips"], "region": df["region"], "name": nm.fillna(df["fips"]),
                        "gop": df["votes_gop"], "dem": df["votes_dem"],
                        "oth": (df["total_votes"] - df["votes_gop"] - df["votes_dem"]).clip(lower=0)})
    return out.groupby(["unit", "region"], as_index=False).agg({"name": "first", "gop": "sum", "dem": "sum", "oth": "sum"})


def centroids() -> pd.DataFrame:
    g = json.loads((DATA / "counties.json").read_text())
    rows = []
    for ft in g["features"]:
        geom = ft["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        pts = np.concatenate([np.asarray(poly[0], float) for poly in polys])
        rows.append((ft["id"], pts[:, 1].mean(), pts[:, 0].mean()))
    return pd.DataFrame(rows, columns=["unit", "lat", "lon"])


def pair(base_year: int, target_year: int):
    """Base y resultado final alineados. Unidades que no existen en ambos años
    (Alaska, nuevas regiones de Connecticut, etc.) se agrupan en una unidad 'resto' por estado."""
    b, t = load_year(base_year), load_year(target_year)
    prefix = pd.concat([b, t]).assign(p=lambda d: d.unit.str[:2]).groupby("region").p.agg(lambda x: x.mode()[0])
    common = set(b.unit) & set(t.unit)
    for d in (b, t):
        m = ~d.unit.isin(common)
        d.loc[m, "unit"] = d["region"] + "-resto"
        d.loc[m, "name"] = "Resto de " + d["region"]
    agg = {"name": "first", "gop": "sum", "dem": "sum", "oth": "sum"}
    b = b.groupby(["unit", "region"], as_index=False).agg(agg)
    t = t.groupby(["unit", "region"], as_index=False).agg(agg)
    b = b[b.unit.isin(t.unit)]
    t = t[t.unit.isin(b.unit)]
    cen = centroids()
    b = b.merge(cen, on="unit", how="left")
    st = b.groupby("region")[["lat", "lon"]].transform("mean")
    b[["lat", "lon"]] = b[["lat", "lon"]].fillna(st)
    cen["p"] = cen.unit.str[:2]
    stc = cen.groupby("p")[["lat", "lon"]].mean()
    miss = b.lat.isna()
    b.loc[miss, ["lat", "lon"]] = stc.loc[b.loc[miss, "region"].map(prefix)].to_numpy()
    t["frac"] = 1.0
    return b.reset_index(drop=True), t.reset_index(drop=True)
