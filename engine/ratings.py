"""
Métodos de Cook Political Report: PVI y calificaciones de carreras (Solid, Likely, Lean, Toss Up).

PVI (cookpolitical.com/cook-pvi): inclinación partidaria de un estado o distrito, medida como su
participación demócrata en el voto de los dos partidos en las dos últimas presidenciales, promediadas
75/25 (la más reciente pesa más), menos la nacional. Acá se usa para armar la base: en lugar de
la última presidencial sola, `pvi_base` mezcla las dos últimas con esos pesos (ver adapters/us_mid.py).

Calificaciones como prior por carrera. Cook publica qué tan seguido gana el favorito en cada
categoría (cookpolitical.com/analysis/national/cpr-archives/how-accurate-are-cook-political-reports-race-ratings):
Solid casi 100%, Likely 97%, Lean 94%; en los Toss Up los republicanos ganaron por 0,7 puntos en
promedio y el 98% se definió por menos de 10. De ahí sale una normal para el margen D-R de cada
categoría (RATING). Los márgenes medios que publica Cook son sobre todo de la Cámara; para el Senado
se usan más chicos, con desvíos que mantienen esas probabilidades del favorito.

En la noche, el prior se combina por carrera con lo que dicen las simulaciones del escrutinio
(actualización normal-normal sobre el margen D-R de la región): cuando en un estado no se contó nada,
la proyección mezcla el swing nacional con la calificación; a medida que se cuenta, el desvío de las
simulaciones se achica y la calificación deja de pesar sola.
"""
from __future__ import annotations
import numpy as np

# margen D-R esperado (en proporción de votos) y desvío, por calificación
RATING = {
    "Solid D": (0.25, 0.10), "Likely D": (0.12, 0.065), "Lean D": (0.06, 0.045),
    "Toss Up": (-0.007, 0.05),
    "Lean R": (-0.06, 0.045), "Likely R": (-0.12, 0.065), "Solid R": (-0.25, 0.10),
}


def prior(rating: str):
    r = rating.strip().replace("Leans", "Lean").replace("Toss-up", "Toss Up").replace("Tossup", "Toss Up")
    return RATING[r]


def adjust(RS, C, regions, ratings, dem, gop, weight=1.0, narrow=False):
    """RS[sims, R, C]: votos simulados por región. ratings: {región: calificación}.
    dem, gop: índices en C de los candidatos de cada partido. Devuelve RS con el margen D-R de
    cada región calificada corrido y achicado según el posterior normal-normal.
    weight < 1 achica la precisión del prior (para probar cuánto conviene creerle).
    narrow: si además se achica el desvío al del posterior. Por defecto no: en el backtest 2022 el
    intervalo achicado cubrió el 70% en lugar del 90% (el prior y el modelo no son independientes:
    ambos miran el mismo ambiente nacional)."""
    RS = RS.copy()
    tot = RS.sum(2)
    M = (RS[..., dem] - RS[..., gop]) / np.maximum(tot, 1e-9)
    for r, reg in enumerate(regions):
        if reg not in ratings:
            continue
        mu_c, sd_c = prior(ratings[reg])
        m = M[:, r]
        mu_m = np.median(m)
        sd_m = max((np.quantile(m, 0.84) - np.quantile(m, 0.16)) / 2, 1e-4)
        pc, pm = weight / sd_c ** 2, 1 / sd_m ** 2
        mu = (mu_m * pm + mu_c * pc) / (pm + pc)
        sd = (pm + pc) ** -0.5
        m2 = mu + (m - mu_m) * (sd / sd_m if narrow else 1.0)
        d = (m2 - m) / 2 * tot[:, r]                  # votos que pasan de un partido al otro
        d = np.clip(d, -RS[:, r, dem], RS[:, r, gop])
        RS[:, r, dem] += d
        RS[:, r, gop] -= d
    return RS
