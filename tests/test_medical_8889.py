import sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from powerbi_medical import candidate_records
from medical_feed import validate
class Medical8889Tests(unittest.TestCase):
 def test_auto_collects_exact_shop_and_validates_feed(self):
  rows=[[str(s)+' ДС',10,8,2,.4] for s in (5818,7745,8889)]
  payload=candidate_records(rows,datetime(2026,11,11,12,tzinfo=timezone.utc))
  records=validate(payload)['records'];self.assertEqual(records[-1]['shop_id'],8889)
  self.assertEqual(records[-1]['value'],60)
 def test_missing_shop_does_not_become_zero_or_break_existing_shops(self):
  rows=[[str(s)+' ДС',10,8,2,.4] for s in (5818,7745,88890)]
  payload=candidate_records(rows,datetime(2026,11,11,12,tzinfo=timezone.utc))
  self.assertEqual([r['shop_id'] for r in payload['records']],[5818,7745])
