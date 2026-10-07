# Hunter Munitions and fire-rate spin-up vs WFSim (2026-10-05)

Produced by `tools/validate_hunter_munitions.py` against the pinned WFSim
checkout `.local/wfsim-live-20261004` (release dc8413a8fab9). Body shots, Steel
Path Thrax Centurion level 170, 30 s, 100 runs, each build with and without
Hunter Munitions.

Harness corrections compared with the first run:

- A weapon with an Incarnon Genesis is always simulated locally with the
  community default route. WFSim's `evolutions: []` is the weapon without
  them. The same route is now sent as explicit evolutions, mapped by unique
  weapon/tier/icon identity. That mismatch was the entire 1.5-2x gap on Soma
  Prime and Burston Prime.
- A progenitor-style weapon (Coda Bubonico) gets the locally resolved innate
  element as `valence_element`/`valence_bonus`.

Model change: fire-rate spin-up (`FIRE_RATE_SPOOL_PROFILES`), which was the
remaining 9% on Prisma Gorgon and up to 13% on Gorgon.

Open: Coda Bubonico is still 1.057x. WFSim fires 85 shots with an 11 s empty
battery recharge (its listed 5.5 s `reload_seconds` plus between-shot regen at
9/s). The local record has no battery profile and a 2 s reload, so it fires
109 shots. Its Hunter Munitions gain is not comparable until cadence matches.
