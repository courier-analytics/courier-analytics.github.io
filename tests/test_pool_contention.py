import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import matryoshka_pools

class Contention(unittest.TestCase):
 def test_busy_resource_stops_batch_without_retrying_remaining_people(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   root.joinpath('matryoshka-monitor.json').write_text(json.dumps({'verified':True,'participants':[
    {'courier_id':'123','name':'Test One','last_shop':9107},
    {'courier_id':'124','name':'Test Two','last_shop':9107}]}))
   with patch.object(matryoshka_pools,'ROOT',root),patch('matryoshka_command_report.membership',return_value={}),patch.object(matryoshka_pools.subprocess,'run',return_value=SimpleNamespace(returncode=75)) as run:
    self.assertEqual(matryoshka_pools.main(),75)
    self.assertEqual(run.call_count,1)
    self.assertEqual(run.call_args.args[0][:5],['flock','-w','0','-E','75'])
