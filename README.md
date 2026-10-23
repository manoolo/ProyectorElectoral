# Proyector electoral

Proyección del resultado final a partir de un escrutinio parcial, para Brasil, Estados Unidos y Argentina. El motor es el mismo para los tres; cada país aporta su base, sus candidatos y su regla electoral.

## Cómo funciona

El escrutinio no llega al azar, así que el conteo crudo está sesgado. El modelo estima cómo van a votar las unidades que faltan (condados, municipios, circuitos) a partir de cuánto **cambió** el voto respecto de la elección anterior en las que ya se contaron.

La proyección es un **ensamble con pesos iguales** de dos métodos:

- **Modelo jerárquico** (`engine/model.py`). Cambio en escala log-ratio respecto de la fuerza más votada de la base. Ridge con features de la base (perfil de voto, tamaño) más efectos regionales encogidos hacia el nacional, más un término espacial con los residuos de vecinos ya contados. Modela también la participación y winsoriza los swings, para que un dato mal cargado no arrastre al resto.
- **Vecinos**: swing de las unidades contadas más cercanas y parecidas (tipo Schteingart).

El swing regional (tipo Quiroga) se calcula como comparación, pero quedó fuera del ensamble por lo que muestra el backtest (ver abajo).

Además:

- **Unidades parciales.** Lo observado pesa según la fracción escrutada.
- **Candidatos sin base propia.** Se reparten su grupo según los vecinos.
- **Incertidumbre.** Simulación con shocks nacional, regional y por unidad, estimados por validación cruzada y calibrados empíricamente por tramo de escrutinio. Además, un shock **por perfil** y **colas gruesas** (ver "Métodos tomados de Silver Bulletin").
- **Reglas electorales** (`engine/rules.py`): colegio electoral de EEUU, más del 50% de los válidos en Brasil, 45% o 40% + 10 puntos en Argentina.

## Validación con datos reales

Se re-escruta cada elección en 15 órdenes de llegada simulados, varios con sesgo fuerte, y se mide el error en el margen entre los dos primeros.

Error medio en puntos, promediando todos los cortes:

| | EEUU 2016→20 | EEUU 2020→24 | Argentina 2015→19 |
|---|---|---|---|
| Conteo crudo | 9,60 | 9,23 | 4,24 |
| Swing regional | 0,86 | 0,71 | 2,45 |
| Vecinos | 0,91 | 0,75 | **0,69** |
| Modelo jerárquico | 0,69 | 0,71 | 1,13 |
| **Ensamble modelo + vecinos** | **0,54** | 0,71 | 0,86 |

Ningún método es el mejor en todas. El ensamble elegido es el que menos se aleja del mejor en cada elección: como mucho, un 20% más de error.

Ojo con un sesgo de selección: la composición del ensamble se eligió mirando las tres elecciones, entre cuatro variantes. Los hiperparámetros del modelo se eligieron solo con 2016→2020.

**Ganador o escenario.**
- EEUU: el ensamble acertó el colegio electoral en el 100% de los cortes.
- Argentina: anticipó bien si había balotaje en el 98%.

**El intervalo es lo más frágil.** Con el shock por perfil y las colas gruesas:
- Calibrado con EEUU 2020, el del 90% cubrió el 63% en 2024 (antes, 53%).
- Calibrado con 2024, cubrió el 97% en 2020 (antes, 98%).
- Con la calibración conjunta de EEUU, cubrió el 97% en Argentina (igual que antes).

Cada país usa en vivo un promedio de la calibración de EEUU y la propia (`config/params_<país>.json`).

## Métodos tomados de Silver Bulletin

Nate Silver publica sobre todo modelos **previos** a la elección (promedios de encuestas, ratings de encuestadoras, simulaciones con errores correlacionados). De ahí se tomó lo que sirve para proyectar un escrutinio:

- **Errores correlacionados por perfil** (`tau_feat`, en `engine/model.py`). Silver correlaciona los errores entre estados parecidos por demografía, no sólo por cercanía. Acá, cada simulación agrega un error de pendiente sobre las features de la base (perfil partidario, tamaño): las unidades parecidas se equivocan juntas, y el error crece cuanto más se aleja una unidad del perfil de lo ya contado. La magnitud sale de una validación cruzada "dejando medio perfil afuera": se ajusta con las unidades de un lado de la mediana de cada feature y se predice el otro. Sólo ensancha: cada región se re-centra en la mediana sin este shock, así que el punto central no cambia.
- **Colas gruesas** (`t_df`). Los shocks nacional, regional y por perfil son t de Student con 5 grados de libertad y la misma varianza que la normal: los escenarios extremos son más probables, como en el modelo de Silver.
- **Promedio de encuestas** (`engine/polls.py`), según su metodología publicada: peso por nota de la encuestadora, tamaño de muestra con rendimientos decrecientes, recencia, tope por frecuencia, house effects iterativos que se descuentan según la muestra acumulada de cada firma, y un prior de 1,7 puntos para las encuestas partidarias.
- **Prior de encuestas** (opcional, apagado). Con `"polls_prior": true` en `config/<país>.json`, las simulaciones se re-ponderan por la verosimilitud del promedio de encuestas (t de Student, desvío de 3,5 puntos de margen). Pesa al principio y se diluye a medida que avanza el conteo.
- **Evaluación de probabilidades.** El backtest guarda la probabilidad asignada al ganador real (`p_regla`) y al primero en votos (`p_a`), para medir el Brier como evalúa Silver sus pronósticos.

**Resultados en el backtest** (mismos órdenes de llegada, antes → después):

| | Antes | Después |
|---|---|---|
| Error del margen, EEUU 2016→20 | 0,54 | 0,55 |
| Error del margen, EEUU 2020→24 | 0,75 | 0,75 |
| Error del margen, Argentina 2015→19 | 0,86 | 0,83 |
| Cobertura del 90% en 2024, calibrado con 2020 | 53% | 63% |
| Factor de calibración medio, 2020 / 2024 | 0,47 / 0,92 | 0,30 / 0,49 |
| Brier del colegio electoral 2020, calibrado con 2024 (8 órdenes) | 0,049 | 0,041 |

La calibración se traslada mejor entre elecciones: los factores de 2020 y 2024 ahora difieren 1,6 veces y no 2.

**El prior de encuestas no se activa por defecto, porque en estos backtests empeora la proyección.** Con los promedios finales (Biden +8,4 en 2020, Harris +1 en 2024) el error medio del margen sube de 0,61 a 0,75 puntos en 2020 y de 0,72 a 0,78 en 2024, y hasta el 20% escrutado, de 1,3 a 1,7 en 2020 y de 1,4 a 1,6 en 2024. Las encuestas erraron en la misma dirección en las tres elecciones (Argentina 2019: más de 15 puntos de ventaja para Fernández en las encuestas, contra 7,7 en el resultado). Conviene activarlo sólo si hay motivos para confiar en las encuestas de ese país. `config/<país>.json` acepta `polls` como lista de encuestas:

```json
"polls": [{"pollster": "X", "date": "2026-10-01", "n": 1200, "grade": "B+", "Lula": 44, "Flávio Bolsonaro": 38},
          {"pollster": "Y", "date": "2026-10-02", "n": 2000, "grade": "A", "partisan": "Lula", "Lula": 46, "Flávio Bolsonaro": 37}],
"polls_prior": false
```

o como shares ya promediados (el formato anterior).

## Métodos tomados de Cook Political Report

Cook no publica un modelo de escrutinio: publica el **PVI** (inclinación partidaria de cada estado y distrito) y **calificaciones** de cada carrera (Solid, Likely, Lean, Toss Up), con su historial de aciertos. Las dos cosas se probaron con el Senado 2022, re-escrutado condado por condado con la presidencial 2020 como base (`backtest_senado.py`, 13 carreras disputadas, 6 órdenes de llegada).

- **Calificaciones como prior por carrera** (`engine/ratings.py`). Cada calificación es una normal sobre el margen D-R, armada con el historial de Cook: el favorito gana el 97% de los Likely y el 94% de los Lean, y en los Toss Up los republicanos ganaron por 0,7 puntos en promedio. En la noche se combina, carrera por carrera, con lo que dicen las simulaciones del escrutinio (actualización normal-normal). Donde todavía se contó poco pesa la calificación, y a medida que se cuenta pesa el escrutinio. El intervalo se corre pero no se achica, porque el prior y el escrutinio miran el mismo ambiente nacional y no son independientes: achicándolo, el 90% cubría el 70%. Se activa con `"ratings"` en la config (`config/us_senado.json`).
- **Base estilo PVI** (`adapters/us_mid.py`, `pvi=True`): mezcla 75/25 de las dos últimas presidenciales en lugar de la última sola. **No se usa**, porque en el backtest empeoró un poco (error al 5% escrutado de 3,51 a 3,69 puntos).
- **API de Cook** (`adapters/cook.py`): baja las calificaciones con una cuenta con acceso a la API y actualiza la config. Sin credenciales, quedan las que están cargadas a mano.

**Resultados en el Senado 2022** (margen D-R por carrera disputada; sin → con calificaciones):

| | Sin | Con |
|---|---|---|
| Error medio del margen con 5% escrutado | 3,51 | 2,93 |
| Error medio del margen con 10% escrutado | 3,04 | 2,65 |
| Error medio del margen con 50% escrutado | 1,94 | 1,76 |
| Brier del ganador de cada carrera | 0,074 | 0,066 |
| Cobertura del 90%, carreras sin terminar de contar | 87% | 91% |
| Probabilidad media del control real (demócratas) con 5% escrutado | 60% | 49% |

Mejora cada carrera por separado, pero empeora la probabilidad del control. En 2022 las calificaciones se equivocaron todas para el mismo lado (los demócratas ganaron casi todos los Toss Up), y el prior arrastra ese error común. Es el mismo problema que el de las encuestas. La diferencia es que acá la ganancia por carrera es clara, y en el Senado disputado importan las carreras. Las calificaciones de 2022 son una reconstrucción: Wisconsin Lean R el 4/11 está confirmado, y el resto sale de las notas de esos días.

**La previa.** Antes de que haya votos, `python senado.py previa` arma el pronóstico sólo con las calificaciones, con un error nacional común de 3 puntos (t de Student). Con las del 20/10/2026, los republicanos controlan el Senado en el 59% de las simulaciones.

## Qué cambió (análisis del corrimiento)

Inspirado en el análisis de El Atlas sobre Brasil 2026 ("comparando los mismos municipios"), `engine/analysis.py` calcula, sólo sobre las unidades ya escrutadas y frente a la elección base:

- cuánto ganó o perdió cada candidato y cuánto se movió la diferencia entre los dos primeros;
- el corrimiento por región y por tamaño de la unidad (se muestra como gráfico de flechas);
- qué tan parejo fue: qué parte de las unidades se movió en el mismo sentido que el total y qué parte de la variación explica la región;
- las unidades que cambiaron de ganador y las "vulnerables", que el perjudicado había ganado por menos que el corrimiento nacional;
- la persistencia de la geografía: diferencia anterior contra actual;
- si en `config/<país>.json` hay `polls`, la distancia entre la proyección y el promedio de encuestas.

Se actualiza en cada corrida de `run_live.py` y está en las repeticiones (`python replay.py us ar`).

## Publicar

La página se publica en GitHub Pages con `.github/workflows/pages.yml` cada vez que cambia `site/` (en Settings → Pages, elegir "GitHub Actions" como fuente). La noche electoral, `python en_vivo.py br` (o `ar`) baja el escrutinio, proyecta y sube los datos cada 2 minutos; la página se refresca sola.

## Estructura

```
engine/    model.py (motor), rules.py, backtest.py, output.py
adapters/  us.py, ar.py (electorAr y DINE), br.py (TSE), canonical.py,
           br_live.py (feed del TSE 2026), ar_live.py (escrutinio provisorio)
config/    <país>.json (candidatos, colores, regla); params_<país>.json (parámetros y calibración)
site/      index.html + data/<país>.json  ← esto va a GitHub Pages
tune.py, evaluate.py (EEUU), backtest_pais.py (Argentina y Brasil), replay.py, run_live.py, build_demo.py
engine/analysis.py  análisis del corrimiento respecto de la elección base
engine/polls.py     promedio de encuestas estilo Silver Bulletin y prior opcional
```

## Uso

```bash
pip install numpy pandas scipy
python tune.py && python evaluate.py      # EEUU: parámetros, calibración y repetición de 2024
python backtest_pais.py ar                # Argentina 2015→2019 (los datos se bajan de GitHub)
python backtest_pais.py br                # Brasil 2018→2022 (baja los zips del TSE)
python build_demo.py                      # página con datos incrustados, para publicar sin servidor
```

### Balotaje en Brasil (2ª vuelta)

`config/br.json` está armado para la segunda vuelta: sólo Lula y Flávio, regla "gana quien tiene más votos" y, como base, la **primera vuelta 2026 municipio por municipio** (el mejor punto de partida: mismos candidatos y mismo año). La configuración de la primera vuelta quedó en `config/br_1t.json`.

```bash
python -m adapters.br_live data/br_1t_2026.csv --turno 1 --config br_1t   # 1ª vuelta 2026 completa (una vez)
python -m adapters.br base2t data/br_1t_2026.csv                         # → data/br_base_2t.csv
python backtest_pais.py br                                               # valida con 2022: 1ª → 2ª vuelta
python en_vivo.py br --turno 2                                           # la noche del balotaje
```

El backtest de Brasil re-escruta la segunda vuelta de 2022 con la primera como base, y deja `config/params_br.json` con la calibración propia.

### Noche electoral en Brasil

```bash
python -m adapters.br 2022                               # base 2022 por municipio (una vez)
python -m adapters.br_live data/br_actual.csv --uf RR    # probá primero con un estado chico
python -m adapters.br_live data/br_actual.csv && python run_live.py br data/br_actual.csv
```

`br_live` descubre la elección en `ele-c.json`, lista los municipios desde la configuración de secciones y baja un JSON por municipio (unos 5.570 pedidos, a 50 por segundo). Sigue la estructura que documentan las instrucciones de descarga del TSE 2026 y el proyecto `juliosaulo/como-meus-vizinhos-votam`. **No está probado contra el servidor real.** Las direcciones mal formadas (404) pueden bloquear la IP por 10 minutos, así que conviene probarlo antes.

### Argentina 2027

1. Bajar los resultados 2023 por mesa de la DINE y correr `python -m adapters.ar archivo.csv`. Guarda también la cantidad de mesas por circuito, que sirve para medir el avance.
2. Completar los candidatos y el mapeo de frentes en `config/ar.json` cuando se oficialicen.
3. El formato del escrutinio provisorio 2027 todavía no se conoce. `adapters/ar_live.py` supone filas por mesa como las de la DINE 2023.

## Pendiente

- **Backtest de Brasil.** El código está listo (`backtest_pais.py br`), pero el TSE no fue accesible desde donde se armó el proyecto, así que todavía no se corrió.
- **Más elecciones de calibración.** Por ejemplo, Argentina 2011→2015 o EEUU 2012→2016, para que el intervalo dependa menos de una sola elección.
- **Orden real de llegada.** Brasil lo publica en el "histórico de totalização"; usarlo haría el backtest más realista que los órdenes simulados.

## Página, mapas y elecciones

La página (`site/index.html` + `site/app.js`) muestra una elección por vez; las demás se eligen desde el menú "Elecciones", que lee `site/elecciones.json`. El buscador del menú acepta cualquier país: si no está configurado, explica qué hace falta para lanzarlo.

**Mapas.** `python build_maps.py` arma `site/geo/<país>.json` (país entero, con regiones y unidades) y `site/geo/<país>/<región>.json` (detalle, se baja al entrar a la región). Los trazos quedan proyectados y simplificados con mapshaper (Node), así que el navegador no necesita librerías. Fuentes: condados del Censo de EEUU (`data/counties.json`), departamentos del INDEC (`data/ar_deptos.geojson`, cruzados por nombre con las secciones electorales) y municipios del IBGE vía geodata-br (se bajan solos). Sólo hay que correrlo si cambia la geometría.

**Datos por unidad.** Con un bloque `geo` en `config/<país>.json` (`map`: carpeta de `site/geo`; `unit_key`: cuántas partes de la clave de unidad usar, p. ej. 2 en Argentina para pasar de circuito a departamento), `run_live.py`, `replay.py` y `backtest_pais.py` agregan a cada frame un `map` con, por unidad de mapa, la fracción escrutada, el reparto del voto contado y los votos contados. En la repetición sólo van las unidades que cambiaron desde el corte anterior; en vivo, sólo el último corte lleva mapa. El JSON también lleva `geo` con el resultado de la base por unidad, para el mapa de corrimientos.

**Sumar una elección:** base y adaptador, `config/<país>.json` con su bloque `geo`, `prep_<país>` en `build_maps.py`, feed en vivo y una entrada en `site/elecciones.json`.
