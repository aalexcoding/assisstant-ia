# ¿Habría ganado más fichas siguiendo las recomendaciones actuales?

## Respuesta corta

Con el código actual, probablemente sí habría terminado con más fichas en
expectativa. Los datos no permiten reconstruir un stack final exacto, pero sí
identifican aproximadamente 5.235 fichas que no se habrían invertido en tres
manos finalmente abandonadas o perdidas.

Hay aproximadamente 600 fichas de ahorro bastante sólido en la última sesión
por dos calls que la versión actual marca como `fold`. A ellas se suman unas
4.635 fichas de la mano `Q5s` de `020108`: el motor actual reconoce varios
limpers, recomienda `fold` y la línea real acabó invirtiendo 51,5 BB para perder
el bote. La mayor diferencia potencial restante está en `KK` contra cuatro
rivales: la subida real fue a 2 BB y la recomendación actual es a 8 BB.

Las sesiones `014709`, `020108` y `022832` se tratan como el mismo torneo porque
sus stacks enlazan. `011143` parece una partida anterior y no se incluye en el
neto principal.

## Qué se puede calcular y qué no

Se compara la última recomendación preflop fiable anterior a la acción del hero
con la primera acción voluntaria observada.

Se consideran tres grados de certeza:

1. **Ahorro directo:** si el motor dice `fold`, se paga y después no hay otra
   inversión del hero, el importe pagado se habría conservado.
2. **Escenario condicionado:** se mantiene el board observado y se supone una
   cantidad concreta de callers. Sirve como sensibilidad, no como resultado
   histórico.
3. **Indeterminado:** una subida, fold o call diferente habría cambiado las
   respuestas rivales y toda la línea postflop.

No se reutiliza sin más el ganador observado. Las cartas comunitarias pueden
mantenerse como escenario, pero los rivales que habrían llegado al flop y el
tamaño del bote ya no serían los mismos.

## Última sesión: `sesion-2026-07-31_022832`

### Mano 6 — `KK`, BB, cuatro limpers

- Recomendación actual: `RAISE OVER LIMPERS (8 BB)`.
- Acción real: subida total a 2 BB.
- Resultado real: el hero ganó un bote de 3.042 fichas.
- Nivel observado: aproximadamente 180 fichas por BB.
- Bote antes de decidir: 5,9 BB.
- Tras la subida pequeña pagaron cuatro rivales.

El motor actual une los importes visibles con los calls positivos del historial:
así cuenta a la SB aunque su placa todavía muestre solo 0,5 BB. Antes de esta
corrección contaba tres limpers y proponía 7 BB.

La subida recomendada exige 6 BB más que la subida real. Si se conserva el mismo
board ganador, la variación debida solo a las aportaciones preflop de los
rivales sería:

| Rivales que pagan 7 BB | Diferencia de aportación rival frente a la mano real |
|---:|---:|
| 0 | los cuatro calls de 1 BB desaparecen |
| 1 | +3 BB, aproximadamente +540 fichas |
| 2 | +10 BB, aproximadamente +1.800 fichas |
| 3 | +17 BB, aproximadamente +3.060 fichas |
| 4 | +24 BB, aproximadamente +4.320 fichas |

Con cero callers se ganaría el bote preflop, pero menos que los aproximadamente
12,7 BB netos obtenidos en la línea real. Por tanto, esta mano no permite decir
“habrías ganado X”; sí muestra que el sizing de 2 BB dejó mucho valor potencial
sin cobrar cuando cuatro jugadores estaban dispuestos a continuar barato.

### Mano 8 — `87o`, BTN

- Recomendación actual: `MARGINAL OPEN RAISE (2 BB)`.
- Acción real: `fold`.
- Coste mínimo de seguir la recomendación: 2 BB, unas 400 fichas.
- Board observado: `7s 9c Jd 7h 3s`.
- Resultado observado: otro jugador ganó con escalera.

Manteniendo artificialmente ese board, el hero habría ligado trío de sietes
pero habría perdido contra la escalera mostrada. El fold real salió mejor en
ese runout. No demuestra que la apertura marginal sea negativa: una apertura
podía hacer foldear al ganador o cambiar por completo los jugadores que
llegaban al river.

### Mano 15 — `K7o`, CO

- Recomendación actual: `fold`.
- Acción real: `call` de 1 BB.
- No se observa otra inversión posterior del hero.
- Las cartas desaparecen antes del river, compatible con abandonar la mano.
- Ahorro por seguir la recomendación: aproximadamente 1 BB = 200 fichas.

Este es un ahorro contrafactual de confianza alta.

### Mano 17 — `97o`, BB contra all-in

- La recomendación antigua llegó a mostrar `CALL` y después
  `RAISE OVER LIMPERS`.
- La versión actual se abstiene al reconocer el all-in de HJ fuera de su tabla.
- Acción real: `fold`.

No hay diferencia de fichas que atribuir a “seguir” la versión actual, porque
la versión actual no prescribe fold; evita ofrecer un call falso. La acción
real fue prudente.

### Mano 18 — `T9s`, SB frente a apertura y caller

- La recomendación antigua volvió erróneamente a `OPEN RAISE`.
- La versión actual se abstiene porque el bote ya está abierto y no existe rango
  compatible de squeeze desde la ciega.

De nuevo, la mejora evita una acción falsa pero no prescribe una acción
alternativa. No se puede asignar una ganancia contrafactual.

### Manos 23 y 28 — `72o` y `A3s`, BB multi-limper

- Recomendación actual: `CHECK`, fallback legal de confianza baja.
- Acción real: `CHECK`.

Se siguió la recomendación. No existe diferencia preflop que simular.

### Mano 37 — `J3s`, HJ

- Recomendación actual: `fold`.
- Acción real: `call` de 1 BB.
- Después se observaron dos checks y ninguna inversión adicional.
- Las cartas desaparecen antes del final.
- Nivel observado: aproximadamente 400 fichas por BB.
- Ahorro por seguir la recomendación: aproximadamente 400 fichas.

Este es el segundo ahorro de confianza alta.

### Balance de la última sesión

- Ahorro directo bastante sólido: **+600 fichas** (`K7o` y `J3s`).
- Apertura marginal no realizada con `87o`: efecto indeterminado; inversión
  inicial de 400 fichas y runout observado desfavorable.
- Mayor subida con `KK`: efecto indeterminado, con escenarios desde ganar menos
  si todos foldean hasta varios miles de fichas adicionales si dos o más
  rivales pagan.

Conclusión para la última sesión: **es razonable pensar que la estrategia actual
tiene mejor expectativa**, sobre todo por los folds y el sizing de `KK`, pero
no es correcto convertirlo en un neto realizado exacto.

## Resto del torneo

### Mano 11 de `020108` — `Q5s`, BTN

- Recomendación con el código actual: `fold`.
- Acción real: call de 1 BB.
- Línea posterior: apuestas sucesivas hasta 51,5 BB comprometidas.
- Resultado: otro jugador ganó el bote de 9.673 fichas.
- Nivel comprobado por bote/BB: aproximadamente 90 fichas por BB.
- Inversión evitable siguiendo el fold: **51,5 BB = unas 4.635 fichas**.

Antes de corregir el conteo por historial, el motor solo veía parte de los
limpers y mostraba una subida marginal. Ahora los calls positivos endurecen
correctamente la fila hasta `fold`. Este es el mayor ahorro contrafactual
demostrable del torneo: retirarse preflop elimina necesariamente toda la
inversión posterior de una mano que acabó perdida.

Las desviaciones más claras de las sesiones anteriores son:

| Sesión / mano | Cartas | Recomendación | Acción real | Lectura del resultado |
|:---|:---:|:---|:---|:---|
| `014709` / 2 | `QTo` | subir sobre limper a 2 BB | call 1 BB | se perdió/fold en flop; subir podía aislar o costar más |
| `014709` / 5 | `77` | check en BB | raise | la desviación ganó el bote observado |
| `014709` / 11 | `98o` | open raise 2 BB | fold | resultado contrafactual desconocido |
| `020108` / 2 | `K7o` | fold | call y apuesta | la desviación ganó el bote observado de 500 fichas |
| `020108` / 10 | `KTo` | marginal call | fold | el board habría dado dobles parejas, pero no se conoce la mano rival |
| `020108` / 11 | `Q5s` | fold | call | se perdieron 51,5 BB; unas 4.635 fichas evitables |
| `020108` / 15 | `Q7o` | fold | call | ligó dama en flop; resultado contrafactual no aislable |
| `020108` / 26 | `K8s` | limp | raise | la desviación llegó a showdown/línea completa; efecto incierto |
| `020108` / 35 | `A7o` | fold | raise | efecto incierto; el board y las respuestas cambiarían |

Esto impide afirmar que seguir todas las recomendaciones habría producido más
fichas **realizadas** en esta muestra: varias desviaciones salieron bien por el
runout. La comparación relevante es de valor esperado a largo plazo, no si una
mano concreta terminó ganando.

## Conclusión del torneo

- **Resultado realizado exacto:** no calculable honestamente.
- **Ahorros demostrables:** alrededor de 5.235 fichas: 4.635 con `Q5s` y 600
  en los dos calls débiles de la última sesión.
- **Potencial adicional principal:** la subida de `KK`; probablemente positiva
  en expectativa, pero dependiente de cuántos limpers pagan 7 BB.
- **Veredicto:** probablemente las reglas actuales habrían mejorado la calidad
  y el valor esperado de las decisiones, pero los datos no demuestran que el
  stack final de este torneo concreto necesariamente hubiera sido mayor.

Para obtener un número de EV comparable hacen falta rangos de respuesta de los
rivales y una política postflop. Sin ellos, cualquier neto único sería una falsa
precisión.
