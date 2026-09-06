# Hosted RC0 Acceptance Matrix

| Area | Test | Gate |
|---|---|---|
| Release | exact deployed commit marker | blocking |
| DB | schema v27 | blocking |
| DB | WAL | blocking |
| DB | quick_check | blocking deep gate |
| DB | foreign_key_check | blocking deep gate |
| Runtime | Theta service active | blocking |
| Runtime | daemon active + heartbeat healthy | blocking |
| Runtime | app active | blocking |
| Runtime | all operational timers enabled | blocking |
| Backup | backup file freshness | blocking supervisor |
| Backup | verified backup | blocking deep gate |
| Recovery | restore drill | blocking before unattended week |
| Disk | >= 15 GiB and >= 15% free by default | blocking |
| Network | 8501/25503/4180 not wildcard-bound | blocking |
| Security | HTTPS/OIDC edge | blocking before internet exposure |
| Science | decision/admission remains disabled | existing release gate |
| Execution | no broker-order route | existing architecture gate |
| Failure injection | app restart recovery | blocking |
| Failure injection | daemon restart recovery | blocking |
| Monitoring | supervisor every 5m | blocking |
| Integrity | deep health every 6h | blocking |
