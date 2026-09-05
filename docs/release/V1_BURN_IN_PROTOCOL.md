# Christiania V1 Burn-In Protocol

The release candidate must accumulate at least 72 hours of unattended production-VM observation before V1.0 promotion.

The `christiania-burn-in.timer` records a health snapshot every 15 minutes. A passing report requires:

- database ready on every snapshot;
- daemon `HEALTHY` on every snapshot;
- Theta `READY` on every snapshot;
- at least one valid verified backup throughout;
- no observation gap above 30 minutes;
- total observed duration at least 72 hours.

A reboot during burn-in is allowed and is counted by Linux boot-ID changes. It must not create unhealthy snapshots or an excessive observation gap.
