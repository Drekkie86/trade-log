# Christiania V1.0 Release Candidate Acceptance

V1.0 RC is a deployment state, not a scientific-edge claim.

A production candidate must prove all of the following on the clean Linux VM:

1. exact release manifest generated from a clean Git checkout;
2. database v25, WAL, integrity and FK health;
3. Theta READY and daemon HEALTHY;
4. secure HTTPS/OIDC edge READY with Streamlit loopback-only;
5. verified backup and isolated restore drill PASS;
6. a genuine Linux reboot proven by a changed kernel boot ID;
7. unattended service recovery after that reboot;
8. at least 72 hours continuous burn-in with no unhealthy snapshots and no >30-minute monitoring gap;
9. Theta timestamp semantics independently live-validated before final V1.0 promotion;
10. no model has decision/admission authority and no broker-order path exists.

The first eight items establish product/runtime readiness. Item nine closes the remaining provider-time contract uncertainty. Scientific calibration maturity remains separate.
