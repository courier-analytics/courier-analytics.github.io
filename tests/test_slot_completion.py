from datetime import datetime
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from calculate_metrics import current_slot_completion
from build_dashboard_feed import validate_metrics

NOW = datetime.fromisoformat('2026-10-26T14:00:00+03:00')


def slot(end='2026-10-25T15:00:00+03:00', identity='1', state='Вышел раньше на час'):
    return {'date': '2026-10-25', 'time_from': '06:00', 'time_to': '16:00',
            'couriers': [{'courier_id': identity, 'shift_status': state, 'shift_end': end}]}


class CompletionTests(unittest.TestCase):
    def test_user_card_one_hour_early_is_not_completed(self):
        result = current_slot_completion([slot()], NOW)
        self.assertEqual((result['numerator'], result['denominator'], result['value']), (0, 1, 0))
        validate_metrics({'planned_completion': result})

    def test_tolerance_and_all_slots_per_unique_courier(self):
        done = slot('2026-10-25T15:50:00+03:00')
        self.assertEqual(current_slot_completion([done, done], NOW)['value'], 100)
        self.assertEqual(current_slot_completion([done, slot()], NOW)['value'], 0)

    def test_night_shift_uses_next_day_and_waits_until_finished(self):
        night = slot('2026-10-26T07:55:00+03:00')
        night.update(time_from='20:00', time_to='08:00')
        self.assertEqual(current_slot_completion([night], NOW)['value'], 100)
        self.assertIsNone(current_slot_completion([night], datetime.fromisoformat('2026-10-26T07:00:00+03:00'))['value'])

    def test_missing_end_never_implies_failed_or_finished(self):
        for end in (None, 'invalid', '2026-10-25T16:00:00'):
            result = current_slot_completion([slot(end)], NOW)
            self.assertIsNone(result['value'])
            self.assertEqual(result['reason'], 'shift_end_or_final_status_missing')
        self.assertEqual(current_slot_completion([slot(None, state='Не вышел')], NOW)['reason'], 'zero_denominator')

    def test_empty_population_has_no_percentage(self):
        self.assertEqual(current_slot_completion([], NOW)['reason'], 'zero_denominator')

    def test_denominator_is_only_arrived_unique_couriers(self):
        done=[slot('2026-10-25T16:00:00+03:00',str(i)) for i in range(12)]
        early=[slot(identity=str(i)) for i in range(12,15)]
        absent=[slot(None,str(i),'Не вышел') for i in range(15,20)]
        waiting=[slot(None,'20','Ожидается')]
        result=current_slot_completion(done+early+absent+waiting,NOW)
        self.assertEqual((result['numerator'],result['denominator'],result['value']),(12,15,80))
        # Missing another booking is not an unfinished shift the courier worked.
        same_person_absent=slot(None,'0','Не вышел')
        self.assertEqual(current_slot_completion([done[0],same_person_absent],NOW)['value'],100)

    def test_future_no_show_and_waiting_do_not_block_completed_arrivals(self):
        done=slot('2026-10-25T16:00:00+03:00')
        future=slot(None,'2','Не вышел');future['date']='2026-10-27'
        waiting=slot(None,'3','Ожидается');waiting['date']='2026-10-27'
        self.assertEqual(current_slot_completion([done,future,waiting],NOW)['value'],100)

    def test_private_groups_use_the_same_arrived_denominator(self):
        from courier_details import build
        from calculate_metrics import metric
        done=slot('2026-10-25T16:00:00+03:00','1')
        absent=slot(None,'2','Не вышел')
        slots=[]
        for i,s in enumerate((done,absent)):
            slots.append({**s,'slot_id':i+1,'slot_type':'limited','scope_id':7745,'capacity':2})
        m=current_slot_completion(slots,NOW)
        detail=build('2026-10-25',{'shop_id':7745,'slots':slots},{'slot_fill':metric(1,4),'planned_completion':m},completion_slots=slots)
        completion=detail['metrics']['planned_completion']
        self.assertTrue(completion['reconciled'])
        self.assertEqual([g['count'] for g in completion['groups']],[1,0,0])

    def test_old_denominator_is_not_retained_as_new_formula_on_failure(self):
        from refresh_dashboard import merge_feed
        from calculate_metrics import metric
        from completion_reporting import BASIS
        def feed(m):
            return {'schema_version':1,'records':[{'date':'2026-10-25','shop_id':7745,'source':'slots_export','reported_at':'2026-10-26T10:00:00Z','booked_places':1,'capacity':2,'fill_percent':50,'metrics':{'planned_completion':m}}]}
        old=metric(12,20,basis='slot_completion_by_actual_night_end_date')
        missing=metric(reason='completion_history_incomplete',basis=BASIS)
        result=merge_feed(feed(old),feed(missing))['records'][0]['metrics']['planned_completion']
        self.assertIsNone(result['value'])
        same=metric(12,15,basis=BASIS)
        result=merge_feed(feed(same),feed(missing))['records'][0]['metrics']['planned_completion']
        self.assertEqual(result['value'],80)
        self.assertEqual(result['stale_reason'],'completion_history_incomplete')
