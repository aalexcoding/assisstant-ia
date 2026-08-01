# Simulación preflop sobre las sesiones recientes

La simulación reutiliza el estado reconocido que quedó guardado en cada frame y ejecuta el motor actual. No vuelve a hacer OCR y no estima un bankroll contrafactual: una acción distinta habría cambiado las respuestas rivales y el desarrollo posterior.

## sesion-2026-07-31_011143

11 ventanas de mano seguidas por la app; 2 con alguna diferencia de acción o procedencia frente a la versión grabada.

| Mano | Frames | Cartas | Pos. | Motor actual | Diferencias |
|---:|:---:|:---:|:---:|:---|:---|
| 1 | 0001-0019 | 73o | SB | fold (f. 0001-0004) | sin cambios |
| 2 | 0020-0026 | A3o | BTN | OPEN RAISE (2 BB) (f. 0021-0026) | sin cambios |
| 3 | 0027-0045 | 99 | CO | OPEN RAISE (2 BB) (f. 0028-0030); OPEN RAISE ALL IN (f. 0031) | sin cambios |
| 4 | 0046-0078 | K2o | HJ | fold (f. 0047-0048) | sin cambios |
| 5 | 0079-0113 | AA | BB | RAISE OVER LIMPERS (4 BB) (f. 0079-0083); 3BET (9 BB) (f. 0084-0095) | 3BET (9 BB) → sin recomendación (se observaron 2 agresiones preflop; la ultima es de CO, por lo que hay una resubida antes de la decision del hero. Las tablas disponibles solo cubren open_raise y respuesta a una apertura, no cold-call/4bet frente a una resubida; sin recomendacion estrategica fiable) (f. 0096-0098); RAISE OVER LIMPERS (4 BB) → sin recomendación (se observaron 2 agresiones preflop; la ultima es de CO, por lo que hay una resubida antes de la decision del hero. Las tablas disponibles solo cubren open_raise y respuesta a una apertura, no cold-call/4bet frente a una resubida; sin recomendacion estrategica fiable) (f. 0100-0102) |
| 6 | 0114-0139 | Q4s | SB | LIMP (f. 0114-0123) | sin cambios |
| 7 | 0140-0187 | T8o | BTN | OPEN RAISE (2 BB) (f. 0140-0145) | sin cambios |
| 8 | 0188-0217 | Q9o | CO | MARGINAL OPEN RAISE (f. 0189-0200) | sin cambios |
| 9 | 0218-0229 | 95o | HJ | fold (f. 0218-0219) | sin cambios |
| 10 | 0230-0275 | A8o | BB | ALL IN (f. 0230-0233) | ALL IN → sin recomendación (1 rival ya ha pagado la subida de CO: el spot es un squeeze/multiway, pero no existe un rango digitalizado ni un donante compatible para BB. La tabla threebet_call disponible es heads-up y no se reutiliza con jugadores adicionales) (f. 0234-0244) |
| 11 | 0276-0290 | no leída | no leída | sin recomendación fiable | sin cambios |

## sesion-2026-07-31_014709

13 ventanas de mano seguidas por la app; 0 con alguna diferencia de acción o procedencia frente a la versión grabada.

| Mano | Frames | Cartas | Pos. | Motor actual | Diferencias |
|---:|:---:|:---:|:---:|:---|:---|
| 1 | 0001-0024 | A5s | SB | LIMP (f. 0002-0009) | sin cambios |
| 2 | 0025-0047 | QTo | BTN | OPEN RAISE (2 BB) (f. 0026); RAISE OVER LIMPERS (2 BB) (f. 0027-0028, 0030) | sin cambios |
| 3 | 0048-0063 | KTo | CO | OPEN RAISE (2 BB) (f. 0048-0049) | sin cambios |
| 4 | 0064-0073 | 53o | HJ | fold (f. 0064) | sin cambios |
| 5 | 0074-0090 | 77 | BB | CHECK (f. 0075-0078) | sin cambios |
| 6 | 0091-0126 | 83o | SB | fold (f. 0092-0095) | sin cambios |
| 7 | 0127-0163 | Q3o | BTN | fold (f. 0128-0129) | sin cambios |
| 8 | 0164-0183 | 63s | CO | sin recomendación fiable | sin cambios |
| 9 | 0184-0211 | T3o | HJ | fold (f. 0186-0187) | sin cambios |
| 10 | 0212-0256 | 42o | SB | fold (f. 0213-0217) | sin cambios |
| 11 | 0257-0267 | 98o | BTN | OPEN RAISE (2 BB) (f. 0258-0261) | sin cambios |
| 12 | 0268-0311 | Q4o | CO | sin recomendación fiable | sin cambios |
| 13 | 0312-0371 | no leída | no leída | sin recomendación fiable | sin cambios |

## sesion-2026-07-31_020108

38 ventanas de mano seguidas por la app; 9 con alguna diferencia de acción o procedencia frente a la versión grabada.

| Mano | Frames | Cartas | Pos. | Motor actual | Diferencias |
|---:|:---:|:---:|:---:|:---|:---|
| 1 | 0001-0025 | KTo | SB | LIMP (f. 0005-0006); MARGINAL CALL (f. 0007-0009) | sin recomendación → MARGINAL CALL (f. 0007) |
| 2 | 0026-0052 | K7o | BTN | MARGINAL OPEN RAISE (f. 0026-0028); fold (f. 0031-0032, 0034-0036) | sin cambios |
| 3 | 0053-0070 | 64o | CO | fold (f. 0053-0058) | sin cambios |
| 4 | 0071-0086 | 96o | HJ | fold (f. 0071-0074) | sin cambios |
| 5 | 0087-0092 | 73s | BB | RAISE OVER LIMPERS (4 BB) (f. 0087-0091) | sin cambios |
| 6 | 0093-0100 | 43o | SB | fold (f. 0093-0096) | sin cambios |
| 7 | 0101-0117 | 98o | BTN | OPEN RAISE (2 BB) (f. 0101-0102); fold (f. 0103-0106) | OPEN RAISE (2 BB) → fold (f. 0103) |
| 8 | 0118-0131 | T6o | CO | sin recomendación fiable | sin cambios |
| 9 | 0132-0145 | 63o | BB | CHECK (f. 0133) | sin cambios |
| 10 | 0146-0172 | KTo | SB | LIMP (f. 0148-0150); MARGINAL CALL (f. 0151-0156) | sin cambios |
| 11 | 0173-0204 | Q5s | BTN | OPEN RAISE (2 BB) (f. 0174); RAISE OVER LIMPERS (2 BB) (f. 0175); MARGINAL RAISE OVER LIMPERS (f. 0176-0177); fold (f. 0178-0180) | MARGINAL RAISE OVER LIMPERS → fold (f. 0178-0180) |
| 12 | 0205-0218 | K9o | CO | MARGINAL OPEN RAISE (f. 0206-0211) | sin cambios |
| 13 | 0219-0236 | J3o | HJ | fold (f. 0221-0222) | sin cambios |
| 14 | 0237-0264 | 43o | BB | CHECK (f. 0237-0239); MARGINAL CALL (f. 0240) | sin cambios |
| 15 | 0265-0285 | Q7o | SB | LIMP (f. 0266-0268); fold (f. 0270-0274) | LIMP → sin recomendación (el historial vigente vio a un rival SUBIR, o sea que el bote NO esta sin abrir, pero no se ha podido atribuir la subida a ningun asiento (sin_to_call); sin defensa fiable. No se recomienda como si nadie hubiera subido) (f. 0275) |
| 16 | 0286-0308 | 97o | BTN | fold (f. 0287-0296) | sin cambios |
| 17 | 0309-0326 | J4o | CO | fold (f. 0310-0313) | sin cambios |
| 18 | 0327-0347 | 62o | HJ | fold (f. 0327-0330) | sin cambios |
| 19 | 0348-0365 | K6s | BB | CHECK (f. 0348-0350) | CHECK → sin recomendación (1 rival ya ha pagado la subida de BTN: el spot es un squeeze/multiway, pero no existe un rango digitalizado ni un donante compatible para BB. La tabla threebet_call disponible es heads-up y no se reutiliza con jugadores adicionales) (f. 0352-0353) |
| 20 | 0366-0386 | T8o | SB | LIMP (f. 0366-0372) | sin cambios |
| 21 | 0387-0430 | QTo | BTN | MARGINAL RAISE OVER LIMPERS (f. 0391-0394) | sin cambios |
| 22 | 0431-0438 | no leída | no leída | sin recomendación fiable | sin cambios |
| 23 | 0439-0454 | QTo | HJ | MARGINAL OPEN RAISE (f. 0439-0442) | sin cambios |
| 24 | 0455-0482 | Q2o | HJ | fold (f. 0455-0456) | sin cambios |
| 25 | 0483-0522 | J2o | BB | CHECK (f. 0483-0484); fold (f. 0485-0488) | sin recomendación → fold (f. 0486-0487); CHECK → fold (f. 0488); CHECK → sin recomendación (1 rival ya ha pagado la subida de MP2: el spot es un squeeze/multiway, pero no existe un rango digitalizado ni un donante compatible para BB. La tabla threebet_call disponible es heads-up y no se reutiliza con jugadores adicionales) (f. 0489-0492); CHECK → sin recomendación (2 rivales ya han pagado la subida de MP2: el spot es un squeeze/multiway, pero no existe un rango digitalizado ni un donante compatible para BB. La tabla threebet_call disponible es heads-up y no se reutiliza con jugadores adicionales) (f. 0493) |
| 26 | 0523-0552 | K8s | SB | LIMP (f. 0523-0529) | sin cambios |
| 27 | 0553-0573 | 43s | BTN | fold (f. 0553-0559) | sin cambios |
| 28 | 0574-0604 | T4s | CO | fold (f. 0574-0578) | sin recomendación → fold (f. 0576-0578) |
| 29 | 0605-0621 | 93o | HJ | fold (f. 0607-0609) | sin cambios |
| 30 | 0622-0654 | K4o | MP2 | fold (f. 0624) | sin cambios |
| 31 | 0655-0684 | 52s | BB | sin recomendación fiable | CHECK → sin recomendación (el historial vigente vio a un rival SUBIR, o sea que el bote NO esta sin abrir, pero no se ha podido atribuir la subida a ningun asiento (sin_to_call); sin defensa fiable. No se recomienda como si nadie hubiera subido) (f. 0662-0663) |
| 32 | 0685-0716 | Q7o | SB | fold (f. 0692-0694) | sin cambios |
| 33 | 0717-0756 | J2o | BTN | fold (f. 0721-0722) | sin cambios |
| 34 | 0757-0765 | K3o | CO | fold (f. 0758-0762) | sin cambios |
| 35 | 0766-0805 | A7o | HJ | fold (f. 0767-0772) | sin cambios |
| 36 | 0806-0820 | 97o | MP2 | fold (f. 0808-0809) | sin cambios |
| 37 | 0821-0830 | no leída | no leída | sin recomendación fiable | sin cambios |
| 38 | 0831-0839 | J5o | BB | CHECK (f. 0831); fold (f. 0832-0838) | sin recomendación → fold (f. 0832-0837); CHECK → fold (f. 0838); CHECK → sin recomendación (1 rival ya ha pagado la subida de MP2: el spot es un squeeze/multiway, pero no existe un rango digitalizado ni un donante compatible para BB. La tabla threebet_call disponible es heads-up y no se reutiliza con jugadores adicionales) (f. 0839) |

## sesion-2026-07-31_022832

39 ventanas de mano seguidas por la app; 7 con alguna diferencia de acción o procedencia frente a la versión grabada.

| Mano | Frames | Cartas | Pos. | Motor actual | Diferencias |
|---:|:---:|:---:|:---:|:---|:---|
| 1 | 0001-0019 | T3o | SB | sin recomendación fiable | sin cambios |
| 2 | 0020-0055 | 86o | BTN | fold (f. 0020-0028) | sin cambios |
| 3 | 0056-0091 | T9o | CO | fold (f. 0061-0063) | sin cambios |
| 4 | 0092-0126 | J9o | HJ | fold (f. 0094, 0096-0097) | sin cambios |
| 5 | 0127-0167 | K2o | MP2 | fold (f. 0128-0131) | sin cambios |
| 6 | 0168-0213 | KK | BB | RAISE OVER LIMPERS (8 BB) [guía pública; confianza media] (f. 0184-0187) | CHECK (BB option) → RAISE OVER LIMPERS (8 BB) [guía pública; confianza media] (f. 0184-0187) |
| 7 | 0214-0243 | K4o | SB | LIMP (f. 0215-0219) | sin cambios |
| 8 | 0244-0266 | 87o | BTN | MARGINAL OPEN RAISE (f. 0244-0252) | sin cambios |
| 9 | 0267-0271 | 43o | CO | fold (f. 0268) | sin cambios |
| 10 | 0272-0291 | 43o | CO | sin recomendación fiable | sin cambios |
| 11 | 0292-0309 | 97s | HJ | OPEN RAISE (2 BB) (f. 0293-0296) | sin cambios |
| 12 | 0310-0333 | 93o | BB | CHECK (f. 0311-0313, 0315); CHECK [fallback legal; confianza baja] (f. 0314) | CHECK → CHECK [fallback legal; confianza baja] (f. 0314) |
| 13 | 0334-0360 | AJo | SB | LIMP (f. 0335-0337, 0339-0340) | sin cambios |
| 14 | 0361-0384 | T7s | BTN | OPEN RAISE (2 BB) (f. 0361-0367) | sin cambios |
| 15 | 0385-0416 | K7o | CO | fold (f. 0386-0394) | sin cambios |
| 16 | 0417-0441 | T9o | HJ | fold (f. 0417-0419) | sin cambios |
| 17 | 0442-0450 | 97o | BB | RAISE OVER LIMPERS (4 BB) (f. 0442-0445) | CALL → sin recomendación (HJ fue all-in como primera agresion observada. Hay tabla suplementaria CALL VS OPEN-PUSH solo para mesa 8-max; esta mesa declara 6 plazas y no se traslada un rango entre formatos) (f. 0446); RAISE OVER LIMPERS (4 BB) → sin recomendación (HJ fue all-in como primera agresion observada. Hay tabla suplementaria CALL VS OPEN-PUSH solo para mesa 8-max; esta mesa declara 6 plazas y no se traslada un rango entre formatos) (f. 0447-0448) |
| 18 | 0451-0488 | T9s | SB | OPEN RAISE (4 BB) (f. 0452-0453) | OPEN RAISE (4 BB) → sin recomendación (el historial vigente vio a un rival SUBIR, o sea que el bote NO esta sin abrir, pero no se ha podido atribuir la subida a ningun asiento (sin_to_call); sin defensa fiable. No se recomienda como si nadie hubiera subido) (f. 0455-0460) |
| 19 | 0489-0496 | K3o | BTN | sin recomendación fiable | sin cambios |
| 20 | 0497-0525 | 75o | CO | sin recomendación fiable | sin cambios |
| 21 | 0526-0541 | 76o | HJ | sin recomendación fiable | sin cambios |
| 22 | 0542-0562 | J3s | HJ | fold (f. 0545) | sin cambios |
| 23 | 0563-0586 | 72o | BB | CHECK (f. 0564-0566); CHECK [fallback legal; confianza baja] (f. 0567-0568) | CHECK (BB option) → CHECK [fallback legal; confianza baja] (f. 0567-0568) |
| 24 | 0587-0612 | JTo | SB | LIMP (f. 0587-0590) | sin cambios |
| 25 | 0613-0641 | Q2s | BTN | OPEN RAISE (2 BB) (f. 0613-0615); fold (f. 0616-0617) | sin cambios |
| 26 | 0642-0654 | 82o | CO | fold (f. 0642-0644) | sin cambios |
| 27 | 0655-0683 | 88 | HJ | OPEN RAISE (2 BB) (f. 0655-0658) | sin cambios |
| 28 | 0684-0703 | A3s | BB | CHECK (f. 0685-0689); CHECK [fallback legal; confianza baja] (f. 0690) | CHECK (BB option) → CHECK [fallback legal; confianza baja] (f. 0690) |
| 29 | 0704-0734 | K5s | SB | LIMP (f. 0704-0708) | sin cambios |
| 30 | 0735-0747 | 94s | BTN | fold (f. 0735-0736) | sin cambios |
| 31 | 0748-0771 | T5o | CO | fold (f. 0749-0750) | sin cambios |
| 32 | 0772-0802 | K8o | HJ | fold (f. 0776) | sin cambios |
| 33 | 0803-0834 | T8s | BB | CHECK (f. 0805-0809); CHECK [fallback legal; confianza baja] (f. 0810-0811) | CHECK → CHECK [fallback legal; confianza baja] (f. 0810-0811) |
| 34 | 0835-0861 | 63o | SB | fold (f. 0835-0841) | sin cambios |
| 35 | 0862-0882 | J3o | BTN | fold (f. 0863-0870) | sin cambios |
| 36 | 0883-0889 | 65o | CO | fold (f. 0885) | sin cambios |
| 37 | 0890-0916 | J3s | HJ | fold (f. 0893-0894) | sin cambios |
| 38 | 0917-0948 | K7s | BB | CHECK (f. 0918-0921); CALL (f. 0922-0925) | sin cambios |
| 39 | 0949-1012 | no leída | no leída | sin recomendación fiable | sin cambios |

## Totales

- 4 sesiones.
- 101 ventanas de mano.
- 18 manos con al menos una diferencia frente a lo grabado.

Una ventana sin cartas o sin recomendación no se rellena por analogía: significa que el estado almacenado no permite una decisión fiable con las tablas disponibles.
