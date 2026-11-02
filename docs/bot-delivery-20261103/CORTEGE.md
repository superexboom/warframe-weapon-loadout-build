# Cortege firefield audit — 2026-11-03

This delivery retains the existing impact/death-explosion model. The incomplete firefield is not added to production damage. No core changes or new tests were made for this continuation.

## Pinned evidence

- Client build: `2026.10.22.13.12`.
- Original EXE SHA256: `eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d`.
- Preserved ThanotechArchgun bytecode SHA256: `35dc689324bd96ca125913066a71fa5a1a266fce6c25a156f8793647cd14278a`.
- Prior query, packet and victim routing: `.local/delivery/mechanics-static-completion-20261028/cortege/FIRE-FIELD-ROUTING.md` and its `evidence/` directory.
- New closure and explicit limits: `.local/delivery/mechanics-followthrough-20261103/cortege/FINDINGS.md`, `closure-contract.json`, `manifest.json`.
- Opcode map: `.local/delivery/mechanics-followthrough-20261102/script-payloads/opcode-map-native-extended.json`.

These are preserved local research artifacts; `.local` is not part of the published runtime. This is static original-image evidence, not a claim of live-game parity or a newer client audit.

## Closed scope

- The projectile query selects EmbedDeathAttack. Under the previously documented neutral ordinary-mod subset, each accepted field hit uses `Heat(trunc_int32(float32(2000 * B)))`, where B is the verified ordinary base-damage multiplier. The Lua bridge drops ordinary elemental shares and does not copy weapon critical/status values. The field has its own status chance `0.699999988079071`.
- Re-decoding the preserved script with the native-backed opcode00/JUMPBACK mapping yields five protos, zero unknown instructions and zero invalid jumps. See `luau-native-closed/ThanotechArchgun.json` under the new evidence directory.
- P1 pc50 jumps to16: instigator acquisition is bounded by five attempts, each decrementing its counter and yielding with `wait(0)`.
- P2 pc12 jumps to1: DestroyElement initializes a 12-second countdown, subtracts the shared frame clock, yields, and destroys the field after the countdown becomes nonpositive if the field still exists. This closes the nominal finite self-cleanup path; the exact endpoint remains frame-quantized.
- Clock atom3022047322 binds through `0x1419186f0` to shared f32 `0x14270ef48`; wait binds through `0x1419185f0`; destroy binds through `0x14196e520` to self vtable+0x418. See `lifetime-binding-candidates.json` and `lifetime-native-bindings.json`.
- ProcExtraTime=-3 encodes to packet+0x269 byte108. Native uses a zero=>255 sentinel, otherwise clamps to[-30,30], computes `extra*4+120`, and truncates. Guarded-state copying is identified; this does not close final Heat duration. See `extra-proc-consumers.json` and `duration-state-consumers.json`.

## Remaining boundaries

- Final Heat proc duration and DoT expiry consumer. `6-3=3 seconds` remains an unverified hypothesis and is not admitted.
- Radius atom binding to the exact field class, physical volume/contact, overlapping fields and target entry/exit.
- Exact hit count at the nominal12s endpoint. Native contact-cache expiry uses strict `last+DamageTick < now` and clears after damage attempts; twelve or thirteen ticks cannot be asserted from the default1s interval alone.
- External creator/entity cleanup. The countdown does not read the creator or original victim, but other engine callbacks may destroy the field sooner.
- Nonneutral instigator/global/gameplay damage multipliers and complete victim-class behavior.

A future direct-only estimate would require explicit field count, continuous-contact/frame-order and neutral-global assumptions and must omit unverified Heat proc damage. This audit does not authorize a complete firefield DPS contribution or three automatically overlapping fields in the current delivery.
