# Felarx Fixed-Form Reload Loop

The v22 bake's last fast shard was Felarx fire mode 1. Read-only stack capture
found its replay at 21.66847237269771 seconds, repeatedly scheduling reload
completion without advancing time. Its reload count had exceeded one billion.

The base shell-reload configuration prevented immediate ammo refill, while the
fixed Incarnon form correctly skipped shell-loading events. With a zero reload
duration, those two rules formed an endless empty-pool loop.

The fix limits deferred shell loading to magazine forms. Fixed Incarnon pools
use the existing direct refill path. Base shell reloads and actual form-cycle
transitions keep their existing event behavior.

Evidence:

- `before-snapshot.json`: sanitized read-only stack and selected locals.
- `before-profile.txt`: 15-second sampling profile of the old worker.
- `before-expected-failures.xml`: three bounded tests reproducing the bug.
- `after-tests.xml`: 111 related regression tests, all passing.
- `felarx-search.json`: actual Riven search and exact returned-build replays.
- `summary.json`: validation summary with the current engine identity.
- `manifest.json`: exact SHA-256 and sizes of the evidence files.

The fixed fingerprint is `695e803101081cda`, cache contract 14. The former
`dcac3a99a2808ca8` reports and shards were preserved separately. This evidence
does not claim completion of the new full cache or game-ground-truth parity.
