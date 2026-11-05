import io,json,sys,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from training import parse,evaluate,collect,configured,BASIS
from calculate_metrics import MOSCOW,metric
from refresh_dashboard import merge_feed

class TrainingTests(unittest.TestCase):
 def setUp(self):
  self.day='2026-11-05';self.now=datetime(2026,11,5,12,tzinfo=MOSCOW)
  self.roster={'verified':True,'date':self.day,'courier_ids':['111111','222222','333333'],
    'names':{'111111':'ТЕСТ Ёж Иванович','222222':'Тест Другой Иванович','333333':'Тест Третий Иванович'}}
  self.text='\ufeffОтметка времени,ФИО курьера ,Оценка\r\n04.11.2026 10:00:00,Тест  Еж Иванович,Не знает\r\n05.11.2026 10:00:00,Тест Еж Иванович,Знает\r\n06.11.2026 10:00:00,Тест Другой Иванович,Знает\r\n04.11.2026 10:00:00,Тест Третий,Знает\r\n04.11.2026 10:00:00,Вне Базы Иванович,Знает\r\n'
 def test_unique_active_intersection_uses_earliest_training_date_and_not_scores(self):
  result=evaluate(self.day,self.roster,parse(self.text),self.now)
  self.assertEqual((result['metric']['numerator'],result['metric']['denominator']),(1,3))
  self.assertEqual(result['metric']['value'],33.33)
  groups=result['detail']['groups'];self.assertEqual([g['count'] for g in groups],[1,2,2])
  self.assertEqual(groups[0]['couriers'][0]['training_date'],'2026-11-04T10:00:00+03:00')
  self.assertTrue(result['detail']['reconciled'])
 def test_ambiguous_full_names_do_not_assign_training_to_multiple_ids(self):
  self.roster['names']['222222']='Тест Еж Иванович'
  result=evaluate(self.day,self.roster,parse(self.text),self.now)
  self.assertEqual(result['metric']['numerator'],0)
  self.assertIn('Неоднозначное',str(result['detail']['groups'][-1]))
 def test_training_date_cutoff_is_moscow_and_future_events_are_not_counted(self):
  records=[{'name':'Тест Еж Иванович','trained_at':'2026-11-04T22:30:00+00:00'}]
  yesterday={**self.roster,'date':'2026-11-04'}
  self.assertEqual(evaluate('2026-11-04',yesterday,records,self.now)['metric']['value'],0)
  self.assertEqual(evaluate(self.day,self.roster,records,self.now)['metric']['numerator'],1)
  records[0]['trained_at']='2026-11-05T23:30:00+03:00'
  self.assertEqual(evaluate(self.day,self.roster,records,self.now)['metric']['numerator'],0)
 def test_missing_or_wrong_dated_roster_and_missing_names_are_not_zero(self):
  for roster in (None,{**self.roster,'date':'2026-11-04'}):
   self.assertIsNone(evaluate(self.day,roster,[],self.now)['metric']['value'])
  del self.roster['names']['333333']
  self.assertEqual(evaluate(self.day,self.roster,[],self.now)['metric']['reason'],'training_roster_names_missing')
 def test_invalid_csv_header_empty_or_malformed_dates_are_rejected(self):
  for text in ('<html>Login</html>','Отметка времени,ФИО курьера\n',
      'Отметка времени,ФИО курьера\n31.02.2026 10:00:00,Тест Имя\n',
      'Отметка времени,ФИО курьера\n05.11.2026 10:00:00,Тест Имя,extra\n',
      'Отметка времени,ФИО курьера,ФИО курьера\n'):
   with self.subTest(text=text),self.assertRaises(ValueError):parse(text)
 def test_collect_validates_download_and_caches_only_private_csv(self):
  class Response(io.BytesIO):
   status=200;headers={'Content-Type':'text/csv; charset=utf-8'}
  with tempfile.TemporaryDirectory() as directory:
   config={'spreadsheet_id':'test_id','gid':123}
   with patch('training.urlopen',return_value=Response(self.text.encode())) as request:
    result=collect(self.day,self.roster,config,Path(directory),self.now)
   self.assertEqual(result['metric']['numerator'],1)
   self.assertEqual(request.call_args.kwargs['timeout'],20)
   saved=Path(directory)/'training/latest.csv';self.assertEqual(saved.stat().st_mode&0o777,0o600)
   before=saved.read_bytes()
   with patch('training.urlopen',side_effect=OSError('PRIVATE_ERROR')):
    failed=collect(self.day,self.roster,config,Path(directory),self.now)
   self.assertIsNone(failed['metric']['value']);self.assertEqual(saved.read_bytes(),before)
   self.assertNotIn('PRIVATE_ERROR',str(failed))
 def test_configuration_is_optional_scoped_and_bad_config_is_isolated(self):
  with tempfile.TemporaryDirectory() as directory:
   config=Path(directory)/'config.json'
   with patch('training.collect') as source:
    self.assertIsNone(configured(self.day,self.roster,Path(directory),config));source.assert_not_called()
    config.write_text(json.dumps({'start_date':'2026-11-05'}))
    self.assertIsNone(configured('2026-11-04',self.roster,Path(directory),config));source.assert_not_called()
   config.write_text('BROKEN')
   self.assertEqual(configured(self.day,self.roster,Path(directory),config)['metric']['reason'],'training_source_unavailable')
 def test_public_training_metric_preserves_last_success_on_transient_failure(self):
  def feed(value):
   return {'schema_version':1,'records':[{'date':self.day,'shop_id':7745,'booked_places':1,'capacity':2,'fill_percent':50,
    'source':'slots_export','reported_at':'2026-11-05T08:00:00+00:00','metrics':{'training':value}}]}
  good=evaluate(self.day,self.roster,parse(self.text),self.now)['metric'];good['PRIVATE_NAME']='MUST_NOT_PUBLISH'
  initial=merge_feed(None,feed(good));self.assertNotIn('PRIVATE_NAME',str(initial));self.assertNotIn('MUST_NOT_PUBLISH',str(initial))
  result=merge_feed(initial,feed(metric(reason='training_source_unavailable',basis=BASIS)))['records'][0]['metrics']['training']
  self.assertEqual(result['value'],33.33);self.assertEqual(result['stale_reason'],'training_source_unavailable')
 def test_pipeline_publishes_counts_and_puts_named_training_only_in_private_details(self):
  from refresh_all_shops import refresh
  from enrich_slots import atomic_json
  result=evaluate(self.day,self.roster,parse(self.text),self.now)
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);private=root/'private';feed=root/'public.json'
   def audit(day,token,proxy,folder,**kwargs):
    atomic_json(folder/'all-shops-observations.json',{'shops':[{'shop_id':7745,'slots':[]}]});return {}
   with patch('refresh_all_shops.audit',side_effect=audit),patch('refresh_all_shops.resolve_overnight',return_value=([],{})),patch('training.configured',return_value=result):
    refresh(self.day,'secret',None,private,feed)
   public=json.loads(feed.read_text());self.assertEqual(public['records'][0]['metrics']['training']['value'],33.33)
   self.assertNotIn('Иванович',feed.read_text());self.assertNotIn('courier_id',feed.read_text())
   detail=json.loads((private/'details'/f'{self.day}-7745.json').read_text())
   self.assertTrue(detail['metrics']['training']['reconciled']);self.assertIn('111111',str(detail))
