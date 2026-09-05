import argparse,json
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from src.decision.risk_lifecycle import record_risk_assessment
def minor(v): return None if v is None else int((Decimal(v)*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def tri(v): return None if v is None else v=='true'
p=argparse.ArgumentParser(); p.add_argument('--candidate-id',type=int,required=True); p.add_argument('--pnl-eur'); p.add_argument('--observed-at'); p.add_argument('--thesis-invalidated',choices=['true','false']); p.add_argument('--event-risk-active',choices=['true','false'])
a=p.parse_args(); at=a.observed_at or datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'); r=record_risk_assessment(candidate_id=a.candidate_id,observed_at=at,mark_net_pnl_eur_minor=minor(a.pnl_eur),thesis_invalidated=tri(a.thesis_invalidated),event_risk_active=tri(a.event_risk_active)); print(json.dumps(r.as_dict(),indent=2,sort_keys=True)); print('BROKER ORDER PATH: FALSE')
