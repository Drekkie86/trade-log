# Supervisor cgroup memory classification — October 12, 2026

Status: Draft only. No production change, no limit changes, no deployment or broker actions.

## Live incident facts

- On 2026-10-12T19:17:53Z supervisor repeatedly failed while research daemon was HEALTHY and Theta READY.
- Only blocking check was daemon memory: MemoryCurrent 803,332,096 bytes versus warning 536,870,912 bytes.
- Effective systemd MemoryHigh 805,306,368 bytes; MemoryMax 1,342,177,280 bytes. Both retained.
- Read-only daemon process RSS 172,516 kB, anonymous RSS 108,216 kB.
- Cgroup memory.stat: anon 110,813,184 bytes; file 671,703,040 bytes; inactive_file 548,634,624 bytes. Working-set estimate current minus inactive_file = 254,697,472 bytes (~243 MiB), below 512 MiB warning.
- Cgroup memory.events: cumulative high=396, max=0, oom=0, oom_kill=0. Historical pressure is REAL but not a measured contemporary event rate; further sampling and performance review are necessary.

## Change

Apply the existing memory warning threshold to effective cgroup working set after deducting only validated inactive_file, not all file-backed memory. Only canonical Christiania resource-controlled services are allowed. If memory.stat is missing, unreadable, malformed or claims more inactive_file than current, retain the previous conservative raw-MemoryCurrent limit check.

Record both raw current and effective working-set memory, inactive_file, accounting basis, and cumulative memory.high event count. Keep the original MemoryHigh, MemoryMax, OOM policy and timeout checks. Do not increase memory limits or clear cache.

## Validation / outstanding safeguards

Local Python 3.13: 41 supervisor/resource regression tests passed, one skipped. Synthetic tests reproduce exact production values and prove cache-only PASS, unreclaimable-high FAIL, missing-stats conservative FAIL, invalid-cache FAIL, systemd policy drift FAIL.

Must still pass GitHub exact-SHA Windows/Ubuntu CI and a performance/release review before merging. Future improvement: record deltas of memory.events high in successive samples and profile latency to detect actual throttling. No cloud deploy and no green production declaration from synthetic data.

Other production blockers remain: audit.service repeatedly times out after 30 minutes, restore drill fails due to scratch-space deficit (~4.24 GiB), missing live research 6–9 Oct, and externally verified alert delivery.
