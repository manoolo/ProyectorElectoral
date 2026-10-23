"""Reglas electorales. Cada regla recibe votos[R, C] por región y candidato y devuelve un dict
con strings (se resumen como probabilidades), bools (probabilidad) o números (mediana e intervalo)."""
import numpy as np

# Votos electorales por estado. 2024-2028 (censo 2020) y 2012-2020 (censo 2010).
EV_2024 = dict(AL=9, AK=3, AZ=11, AR=6, CA=54, CO=10, CT=7, DE=3, DC=3, FL=30, GA=16, HI=4, ID=4, IL=19,
               IN=11, IA=6, KS=6, KY=8, LA=8, ME=4, MD=10, MA=11, MI=15, MN=10, MS=6, MO=10, MT=4, NE=5,
               NV=6, NH=4, NJ=14, NM=5, NY=28, NC=16, ND=3, OH=17, OK=7, OR=8, PA=19, RI=4, SC=9, SD=3,
               TN=11, TX=40, UT=6, VT=3, VA=13, WA=12, WV=4, WI=10, WY=3)
EV_2012 = dict(EV_2024, CA=55, CO=9, FL=29, IL=20, MI=16, MT=3, NY=29, NC=15, OH=18, OR=7, PA=20, TX=38, WV=5)
assert sum(EV_2024.values()) == 538 and sum(EV_2012.values()) == 538


def us_electoral_college(ev):
    """Ganador se lleva todo por estado. Aproximación: Maine y Nebraska reparten por distrito,
    pero con datos por condado no se puede reconstruir el distrito congresional."""
    def rule(V, C, regions):
        tally = dict.fromkeys(C, 0)
        for r, reg in enumerate(regions):
            tally[C[int(np.argmax(V[r]))]] += ev.get(reg, 0)
        out = {f"ev_{c}": int(v) for c, v in tally.items()}
        w = max(tally, key=tally.get)
        out["ganador"] = w if tally[w] >= 270 else "sin mayoría"
        return out
    return rule


def _two_round(V, C, win):
    tot = V.sum(0)
    s = tot / tot.sum()
    o = np.argsort(s)[::-1]
    a, b = C[o[0]], C[o[1]]
    if win(s[o[0]], s[o[1]]):
        return {"resultado": f"Gana {a} en primera vuelta", "balotaje": False}
    return {"resultado": f"Balotaje {a} vs {b}", "balotaje": True}


def brasil():
    """Presidente: más del 50% de los votos válidos (sin blancos ni nulos)."""
    return lambda V, C, regions: _two_round(V, C, lambda a, b: a > 0.5)


def argentina():
    """Art. 97 y 98 de la Constitución: 45% de los votos afirmativos válidos,
    o 40% con 10 puntos de diferencia sobre el segundo."""
    return lambda V, C, regions: _two_round(V, C, lambda a, b: a >= 0.45 or (a >= 0.40 and a - b >= 0.10))


def segunda_vuelta():
    """Balotaje: gana quien tiene más votos válidos."""
    def rule(V, C, regions):
        tot = V.sum(0)
        return {"ganador": C[int(np.argmax(tot))]}
    return rule



def senado(fijas: dict, desempate: str, total=100, indep: dict | None = None):
    """Control del Senado de EEUU. `fijas`: bancas que no se eligen (o que no se modelan) por fuerza;
    `desempate`: la fuerza del vicepresidente, que desempata 50-50. Cada carrera (región) la gana
    el más votado (Georgia va a segunda vuelta si nadie pasa el 50%: se informa aparte).
    `indep`: {región: nombre} para carreras donde el lugar del demócrata lo ocupa un independiente
    que no dijo con quién va a votar (Nebraska 2026, Osborn): su banca se cuenta aparte.
    Devuelve el control, las bancas de cada fuerza y el ganador de cada carrera."""
    indep = indep or {}
    def rule(V, C, regions):
        tally = {c: fijas.get(c, 0) for c in C}
        ind = 0
        out = {}
        for r, reg in enumerate(regions):
            w = C[int(np.argmax(V[r]))]
            if reg in indep and w != desempate:
                ind += 1
                out[f"gana_{reg}"] = indep[reg]
            else:
                tally[w] += 1
                out[f"gana_{reg}"] = w
            if reg.startswith("GA"):
                out["balotaje_GA"] = bool(V[r].max() / max(V[r].sum(), 1) <= 0.5)
        for c in C:                                  # siempre las mismas claves: se resumen entre simulaciones
            out[f"bancas_{c}"] = int(tally[c])
        if indep:
            out["bancas_Independientes"] = ind
        half = total // 2
        w = max(tally, key=tally.get)
        if tally[w] > half or (tally[w] == half and w == desempate):
            out["control"] = w
        elif ind and tally[w] + ind > half:
            out["control"] = "Depende de " + "/".join(sorted(set(indep.values())))
        else:
            out["control"] = "Sin mayoría propia"
        return out
    return rule


# Congreso de los Diputados, 29/11/2026 (Real Decreto 806/2026): igual que 2023 salvo Madrid 38 (+1) y Cádiz 8 (−1).
# Clave: código INE de la provincia (Ceuta 51 y Melilla 52 eligen un diputado cada una).
ES_SEATS_2023 = {"01": 4, "02": 4, "03": 12, "04": 6, "05": 3, "06": 5, "07": 8, "08": 32, "09": 4, "10": 4, "11": 9,
                 "12": 5, "13": 5, "14": 6, "15": 8, "16": 3, "17": 6, "18": 7, "19": 3, "20": 6, "21": 5, "22": 3,
                 "23": 5, "24": 4, "25": 4, "26": 4, "27": 4, "28": 37, "29": 11, "30": 10, "31": 5, "32": 4, "33": 7,
                 "34": 3, "35": 8, "36": 7, "37": 4, "38": 7, "39": 5, "40": 3, "41": 12, "42": 2, "43": 6, "44": 3,
                 "45": 6, "46": 16, "47": 5, "48": 8, "49": 3, "50": 7, "51": 1, "52": 1}
ES_SEATS_2026 = dict(ES_SEATS_2023, **{"28": 38, "11": 8})
assert sum(ES_SEATS_2023.values()) == 350 and sum(ES_SEATS_2026.values()) == 350


def dhondt_seats(votes, seats, threshold=0.0, valid=None):
    """D'Hondt en una circunscripción: votos por lista -> escaños por lista. Las listas por debajo
    del umbral (fracción de `valid`, que en España incluye el voto en blanco) no entran al reparto.
    Empates: gana la lista con más votos (art. 163 LOREG; el sorteo no se modela)."""
    v = np.asarray(votes, float)
    tot = v.sum() if valid is None else valid
    ok = v >= threshold * tot
    q = (v[ok][:, None] / np.arange(1, seats + 1)[None]).ravel()
    who = np.repeat(np.flatnonzero(ok), seats)
    out = np.zeros(len(v), int)
    if seats and len(q):
        top = np.lexsort((-v[who], -q))[:seats]
        np.add.at(out, who[top], 1)
    return out


def espana_congreso(seats=ES_SEATS_2026, threshold=0.03, blank=0.0126, majority=176, blocs=None, no_seats=("Otros",), bloc_labels=None):
    """Congreso: D'Hondt por provincia con umbral del 3% de los votos válidos (art. 163 LOREG).
    Los válidos incluyen el voto en blanco, que el modelo no proyecta: se suma como una fracción
    fija `blank` (1,26% en 2023). "Otros" agrupa listas chicas y no recibe escaños.
    `blocs`: {nombre: [listas]} → probabilidad de que cada bloque sume `majority`; `bloc_labels` es para la página."""
    blocs = blocs or {}
    def rule(V, C, regions):
        elig = np.array([c not in no_seats for c in C])
        tally = np.zeros(len(C), int)
        by = {}
        for r, reg in enumerate(regions):
            v = np.where(elig, V[r], 0.0)
            s = dhondt_seats(v, seats.get(reg, 0), threshold, valid=V[r].sum() / (1 - blank))
            tally += s
            by[reg] = s.tolist()
        out = {f"esc_{c}": int(tally[i]) for i, c in enumerate(C) if elig[i]}
        for name, members in blocs.items():
            out[f"may_{name}"] = bool(sum(tally[C.index(m)] for m in members if m in C) >= majority)
        out["primero"] = C[int(np.argmax(tally))]
        out["por_region"] = by            # sólo en el punto central (summarize ignora listas/dicts)
        return out
    return rule


RULES = {"us_ec_2024": lambda: us_electoral_college(EV_2024),
         "us_ec_2012": lambda: us_electoral_college(EV_2012),
         "brasil": brasil, "brasil_2t": segunda_vuelta, "argentina": argentina,
         # Senado 2026: no se eligen 31 republicanas y 34 demócratas (incluye a King y Sanders);
         # Vance desempata. 2022 (backtest): sin CA ni AK en los datos, quedan fijas 37 D y 30 R
         "us_senado_2026": lambda: senado({"Republicanos": 31, "Demócratas": 34}, "Republicanos",
                                          indep={"NE": "Osborn"}),
         "us_senado_2022": lambda: senado({"gop": 30, "dem": 37}, "dem"),
         "espana_congreso": espana_congreso,
         "espana_congreso_2023": lambda **kw: espana_congreso(**{"seats": ES_SEATS_2023, **kw})}
