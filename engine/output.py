"""Convierte la salida del motor en un 'frame' liviano para la página."""
r4 = lambda v: None if v is None else [round(float(x), 4) for x in v]


def frame(out: dict, ts: str | None = None) -> dict:
    f = dict(ts=ts, counted=round(out["counted_frac"], 4), units=[out["counted_units"], out["units"]],
             crude=r4(out["crude"]), proj=r4(out["proj"]), lo=r4(out.get("proj_lo")), hi=r4(out.get("proj_hi")),
             margin=out.get("margin"), rule=out.get("rule"), rule_point=out.get("rule_point"),
             regions=dict(counted=r4(out["region_counted"]), proj=[r4(x) for x in out["region_proj"]],
                          crude=[r4(x) for x in out["region_crude"]], votes=[round(v) for v in out["region_votes"]],
                          p_ahead=r4(out.get("region_p_a_ahead"))))
    return f
