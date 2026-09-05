import argparse,json
from decimal import Decimal,ROUND_HALF_UP
from src.decision.risk_lifecycle import create_frozen_risk_plan
def minor(v): return int((Decimal(v)*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
p=argparse.ArgumentParser(); p.add_argument('--candidate-id',type=int,required=True); p.add_argument('--max-defined-loss-eur',required=True); p.add_argument('--reserved-risk-eur',required=True); p.add_argument('--stop-loss-fraction',type=float); p.add_argument('--time-stop-at'); p.add_argument('--thesis-rule'); p.add_argument('--event-rule'); p.add_argument('--notes')
a=p.parse_args(); r=create_frozen_risk_plan(candidate_id=a.candidate_id,max_defined_loss_eur_minor=minor(a.max_defined_loss_eur),reserved_risk_eur_minor=minor(a.reserved_risk_eur),stop_loss_fraction=a.stop_loss_fraction,time_stop_at=a.time_stop_at,thesis_invalidation_rule=a.thesis_rule,event_stop_rule=a.event_rule,entry_assumption={'source':'OPERATOR_FROZEN'},notes=a.notes); print(json.dumps(r.as_dict(),indent=2,sort_keys=True)); print('BROKER ORDER PATH: FALSE')
