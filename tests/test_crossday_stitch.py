"""Calendar-clipped shift facts must be stitched without inventing another shift."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from overnight_completion import resolve
from completion_reporting import pending,choose,collect
from calculate_metrics import current_slot_completion
from shift_reporting_day import reporting_day

NOW=datetime.fromisoformat('2026-11-06T12:00:00+03:00')
START='2026-11-03T20:17:00+03:00'
BOUNDARY='2026-11-03T23:59:59+03:00'
MIDNIGHT='2026-11-04T00:00:00+03:00'
END='2026-11-04T08:00:00+03:00'


def origin(start=START,end=BOUNDARY,identity='111111',slot_id=10,day='2026-11-03',time_from='20:00',time_to='08:00'):
    return {'date':day,'slot_id':slot_id,'slot_type':'limited','scope_kind':'shopno','scope_id':7745,
            'time_from':time_from,'time_to':time_to,'capacity':1,
            'couriers':[{'courier_id':identity,'shift_status':'Вышел','shift_start':start,'shift_end':end}]}


def raw(start,end,identity='111111',slot_id=20,day='2026-11-04',time_from='20:00',time_to='08:00'):
    return {'date':day,'slot_id':slot_id,'slot_type':'limited','shopno_cluster_id':7745,
            'time_from':time_from,'time_to':time_to,'courier_limits':1,'occupied':1,
            'couriers':[{'id':identity,'shift_status':'Вышел','shift_start':start,'shift_end':end}]}


class CrossDayStitchTests(unittest.TestCase):
    def resolve_with(self,slots,by_day,**kwargs):
        def response(scope,*unused):
            return {'items':deepcopy(by_day.get(scope[0],[]))}
        with patch('overnight_completion.fetch',side_effect=response):
            return resolve(slots,'private-token','',NOW,**kwargs)

    def test_boundary_is_revisited_even_when_end_is_present_and_input_is_immutable(self):
        slots=[origin()];before=deepcopy(slots)
        result,report=self.resolve_with(slots,{'2026-11-04':[raw(START,END)]})
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_end'],END)
        self.assertEqual(person['shift_end_raw'],BOUNDARY)
        self.assertEqual(person['shift_end_source_date'],'2026-11-04')
        self.assertEqual(slots,before)
        self.assertEqual(reporting_day(result[0],person),'2026-11-04')

    def test_reset_midnight_start_can_continue_unique_boundary_with_repeated_night_booking(self):
        # Native daily facts can reset to00:00 while the booking is still20–08.
        result,_=self.resolve_with([origin()],{'2026-11-04':[raw(MIDNIGHT,END)]})
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_start'],START)
        self.assertEqual(person['shift_end'],END)
        self.assertEqual(person['shift_end_raw'],BOUNDARY)

    def test_independent_new_shift_is_not_joined_by_courier_id_alone(self):
        result,_=self.resolve_with([origin()],{'2026-11-04':[raw('2026-11-04T06:00:00+03:00','2026-11-04T18:00:00+03:00')]})
        person=result[0]['couriers'][0]
        self.assertIsNone(person['shift_end'])
        self.assertEqual(person['shift_end_raw'],BOUNDARY)
        self.assertIsNone(reporting_day(result[0],person))

    def test_other_courier_and_conflicting_midnight_ends_remain_unconfirmed(self):
        for rows in ([raw(MIDNIGHT,END,identity='222222')],
                     [raw(MIDNIGHT,END),raw(MIDNIGHT,'2026-11-04T07:00:00+03:00',slot_id=21)]):
            with self.subTest(rows=len(rows)):
                result,_=self.resolve_with([origin()],{'2026-11-04':rows})
                self.assertIsNone(result[0]['couriers'][0]['shift_end'])

    def test_competing_overlapping_actual_start_blocks_reset_join(self):
        rows=[raw(MIDNIGHT,END),raw('2026-11-04T01:00:00+03:00','2026-11-04T06:00:00+03:00',slot_id=21)]
        result,_=self.resolve_with([origin()],{'2026-11-04':rows})
        self.assertIsNone(result[0]['couriers'][0]['shift_end'])

    def test_later_separate_shift_after_continuation_end_does_not_block_join(self):
        rows=[raw(MIDNIGHT,END),raw('2026-11-04T10:00:00+03:00','2026-11-04T18:00:00+03:00',slot_id=21)]
        result,_=self.resolve_with([origin()],{'2026-11-04':rows})
        self.assertEqual(result[0]['couriers'][0]['shift_end'],END)

    def test_multiple_possible_previous_starts_are_not_assigned_the_same_midnight_fragment(self):
        slots=[origin(),origin(start='2026-11-03T19:00:00+03:00',slot_id=11)]
        result,_=self.resolve_with(slots,{'2026-11-04':[raw(MIDNIGHT,END)]})
        self.assertTrue(all(s['couriers'][0]['shift_end'] is None for s in result))

    def test_midnight_start_is_restored_from_unique_previous_boundary_fact(self):
        today=origin(start=MIDNIGHT,end=END,day='2026-11-04',time_from='00:00',time_to='08:00')
        yesterday=raw(START,BOUNDARY,day='2026-11-03')
        result,_=self.resolve_with([today],{'2026-11-03':[yesterday]})
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_start'],START)
        self.assertEqual(person['shift_start_raw'],MIDNIGHT)
        self.assertEqual(person['shift_end'],END)

    def test_unresolved_boundary_remains_pending_and_is_recoverable_on_later_poll(self):
        self.assertTrue(pending(origin()))
        unresolved,_=self.resolve_with([origin()],{})
        self.assertIsNone(unresolved[0]['couriers'][0]['shift_end'])
        self.assertTrue(pending(unresolved[0]))
        recovered,_=self.resolve_with(unresolved,{'2026-11-04':[raw(MIDNIGHT,END)]})
        self.assertEqual(recovered[0]['couriers'][0]['shift_end'],END)

    def test_intermediate_next_day_boundary_can_continue_into_second_following_day(self):
        final='2026-11-05T08:00:00+03:00'
        rows={'2026-11-04':[raw(START,'2026-11-04T23:59:59+03:00')],
              '2026-11-05':[raw(START,final,day='2026-11-05')]}
        result,_=self.resolve_with([origin()],rows)
        self.assertEqual(result[0]['couriers'][0]['shift_end'],final)
        self.assertEqual(result[0]['couriers'][0]['shift_end_source_date'],'2026-11-05')

    def test_shared_source_cache_avoids_repeated_daily_fetch(self):
        cache={}
        def response(scope,*unused):return {'items':[raw(START,END)] if scope[0]=='2026-11-04' else []}
        with patch('overnight_completion.fetch',side_effect=response) as request:
            resolve([origin()],'private-token','',NOW,source_cache=cache)
            resolve([origin()],'private-token','',NOW,source_cache=cache)
        next_day_calls=[c for c in request.call_args_list if c.args[0][0]=='2026-11-04']
        self.assertEqual(len(next_day_calls),1)

    def test_real_end_before_calendar_boundary_is_preserved(self):
        real='2026-11-03T23:30:00+03:00'
        with patch('overnight_completion.fetch') as request:
            result,_=resolve([origin(end=real)],'private-token','',NOW)
        self.assertEqual(result[0]['couriers'][0]['shift_end'],real)
        request.assert_not_called()

    def test_multiday_chain_consumes_only_pure_calendar_fragments(self):
        middle_end='2026-11-04T23:59:59+03:00'
        final_end='2026-11-05T08:00:00+03:00'
        sources={
            '2026-11-03':[raw(START,BOUNDARY,day='2026-11-03',slot_id=10)],
            '2026-11-04':[{**raw(MIDNIGHT,middle_end,slot_id=21,time_from='00:00',time_to='23:59'),'slot_type':'manual'}],
            # Morning facts under a later repeated night header are a projection.
            '2026-11-05':[raw('2026-11-05T00:00:00+03:00',final_end,day='2026-11-05',slot_id=22)],
        }
        stitched,_=self.resolve_with([origin()],sources)
        self.assertEqual(stitched[0]['couriers'][0]['shift_end'],final_end)
        middle=origin(start=MIDNIGHT,end=middle_end,day='2026-11-04',slot_id=21,time_from='00:00',time_to='23:59')
        middle['slot_type']='manual'
        final=origin(start='2026-11-05T00:00:00+03:00',end=final_end,day='2026-11-05',slot_id=22)
        combined=stitched+[middle,final]
        self.assertEqual(choose(combined,'2026-11-04'),[])
        chosen=choose(combined,'2026-11-05')
        self.assertEqual(len(chosen),1)
        self.assertEqual(chosen[0]['slot_id'],10)

    def test_unconfirmed_night_lower_bound_is_not_an_early_finish_but_daytime_end_can_be_proven(self):
        for clear in (False,True):
            with self.subTest(clear=clear):
                night=origin()
                day=origin(time_from='20:00',time_to='23:00')
                if clear:
                    for slot in (night,day):
                        slot['couriers'][0]['shift_end']=None
                        slot['couriers'][0]['shift_end_raw']=BOUNDARY
                        slot['couriers'][0]['shift_end_lower_bound']=BOUNDARY
                self.assertIsNone(current_slot_completion([night],NOW)['value'])
                self.assertEqual(current_slot_completion([day],NOW)['value'],100)

    def test_consumed_reference_does_not_hide_new_work_reusing_same_booking_identity(self):
        original=origin(end=END)
        original['couriers'][0]['shift_continuation_facts']=[{
            'date':'2026-11-04','slot_id':20,'slot_type':'limited',
            'scope_kind':'shopno','scope_id':7745,'shift_start':MIDNIGHT,'shift_end':END}]
        later=origin(start='2026-11-04T10:00:00+03:00',end='2026-11-04T18:00:00+03:00',
            day='2026-11-04',slot_id=20,time_from='09:00',time_to='21:00')
        selected=choose([original,later],'2026-11-04')
        self.assertEqual(len(selected),2)
        self.assertEqual(current_slot_completion(selected,NOW)['value'],0)

    def test_restored_midnight_alias_does_not_conflict_with_its_own_raw_start(self):
        middle_end='2026-11-04T23:59:59+03:00'
        final_end='2026-11-05T08:00:00+03:00'
        middle=origin(start=MIDNIGHT,end=middle_end,day='2026-11-04',slot_id=21,time_from='00:00',time_to='23:59')
        sources={
            '2026-11-03':[raw(START,BOUNDARY,day='2026-11-03',slot_id=10)],
            '2026-11-04':[raw(MIDNIGHT,middle_end,slot_id=21,time_from='00:00',time_to='23:59')],
            '2026-11-05':[raw('2026-11-05T00:00:00+03:00',final_end,day='2026-11-05',slot_id=22,time_from='00:00',time_to='08:00')],
        }
        result,_=self.resolve_with([middle],sources)
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_start'],START)
        self.assertEqual(person['shift_start_raw'],MIDNIGHT)
        self.assertEqual(person['shift_end'],final_end)

    def test_later_export_cannot_move_end_before_confirmed_calendar_lower_bound(self):
        result,_=self.resolve_with([origin()],{'2026-11-04':[raw(START,'2026-11-03T22:00:00+03:00')]})
        person=result[0]['couriers'][0]
        self.assertIsNone(person['shift_end'])
        self.assertEqual(person['shift_end_raw'],BOUNDARY)


    def test_new_midnight_booking_remains_an_independent_completion_obligation(self):
        original_start='2026-11-03T14:00:00+03:00'
        actual_end='2026-11-04T06:00:00+03:00'
        for next_start in (MIDNIGHT,original_start):
            with self.subTest(next_start=next_start):
                before=origin(start=original_start,time_from='14:00',time_to='00:00')
                following=origin(start=next_start,end=actual_end,day='2026-11-04',
                    slot_id=20,time_from='00:00',time_to='08:00')
                sources={
                    '2026-11-03':[raw(original_start,BOUNDARY,day='2026-11-03',
                        slot_id=10,time_from='14:00',time_to='00:00')],
                    '2026-11-04':[raw(next_start,actual_end,time_from='00:00',time_to='08:00')],
                }
                stitched,_=self.resolve_with([before,following],sources)
                # Continuous physical work can be recovered, but the next booked
                # 00–08 commitment is not discharged by completing14–00.
                self.assertEqual(stitched[0]['couriers'][0]['shift_end'],actual_end)
                selected=choose(stitched,'2026-11-04')
                self.assertEqual({slot['slot_id'] for slot in selected},{10,20})
                self.assertEqual(current_slot_completion(selected,NOW)['value'],0)

    def test_prior_day_overlapping_actual_start_blocks_forward_midnight_join(self):
        sources={
            '2026-11-03':[
                raw(START,BOUNDARY,day='2026-11-03',slot_id=10),
                raw('2026-11-03T23:55:00+03:00',END,day='2026-11-03',slot_id=11),
            ],
            '2026-11-04':[raw(MIDNIGHT,END)],
        }
        result,_=self.resolve_with([origin()],sources)
        person=result[0]['couriers'][0]
        self.assertIsNone(person['shift_end'])
        self.assertEqual(person['shift_end_raw'],BOUNDARY)

    def test_prior_day_overlapping_actual_start_blocks_backward_start_recovery(self):
        sources={
            '2026-11-03':[
                raw(START,BOUNDARY,day='2026-11-03',slot_id=10),
                raw('2026-11-03T23:55:00+03:00',END,day='2026-11-03',slot_id=11),
            ],
        }
        current=origin(start=MIDNIGHT,end=END,day='2026-11-04',
            slot_id=20,time_from='00:00',time_to='08:00')
        result,_=self.resolve_with([current],sources)
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_start'],MIDNIGHT)
        self.assertNotIn('shift_start_raw',person)
        self.assertEqual(person['shift_end'],END)

    def test_completed_separate_day_shift_does_not_conflict_with_night_continuation(self):
        sources={
            '2026-11-03':[
                raw('2026-11-03T08:00:00+03:00','2026-11-03T18:00:00+03:00',
                    day='2026-11-03',slot_id=11,time_from='08:00',time_to='18:00'),
                raw(START,BOUNDARY,day='2026-11-03',slot_id=10),
            ],
            '2026-11-04':[raw(MIDNIGHT,END)],
        }
        forward,_=self.resolve_with([origin()],sources)
        self.assertEqual(forward[0]['couriers'][0]['shift_end'],END)
        current=origin(start=MIDNIGHT,end=END,day='2026-11-04',
            slot_id=20,time_from='00:00',time_to='08:00')
        backward,_=self.resolve_with([current],sources)
        self.assertEqual(backward[0]['couriers'][0]['shift_start'],START)
        self.assertEqual(backward[0]['couriers'][0]['shift_start_raw'],MIDNIGHT)
        self.assertEqual(backward[0]['couriers'][0]['shift_end'],END)


    def test_collect_refetches_legacy_closed_boundary_and_reconciles_private_details(self):
        from courier_details import build as build_details
        previous='2026-11-03';day='2026-11-04'
        sources={previous:[raw(START,BOUNDARY,day=previous,slot_id=10)],
                 day:[raw(MIDNIGHT,END)]}
        def limited_response(scope,*unused):
            self.assertEqual(scope,(previous,'shopno',7745,'limited'))
            return {'items':deepcopy(sources[previous])}
        def daily_response(scope,*unused):
            self.assertEqual(scope[-1],'all')
            return {'items':deepcopy(sources.get(scope[0],[]))}
        current=origin(start=MIDNIGHT,end=END,day=day,slot_id=20)
        with tempfile.TemporaryDirectory() as folder:
            state_dir=Path(folder)
            state_path=state_dir/'completion-night-state'/'7745.json'
            state_path.parent.mkdir()
            state_path.write_text(json.dumps({'days':{previous:{
                'scopes':[['shopno',7745]],'slots':[origin()]}}}))
            with patch.dict('completion_reporting.FIRST_DAYS',{7745:day}), \
                 patch('completion_reporting.fetch',side_effect=limited_response) as limited_request, \
                 patch('overnight_completion.fetch',side_effect=daily_response) as daily_request:
                result,_=collect(day,7745,{'cluster_ids':[]},[current],
                    'private-token','',state_dir,NOW)
            limited_request.assert_called_once_with(
                (previous,'shopno',7745,'limited'),'private-token','')
            self.assertEqual({call.args[0][0] for call in daily_request.call_args_list},
                {previous,day})
            self.assertEqual(result['value'],100)
            self.assertEqual(result['denominator'],1)
            saved=json.loads(state_path.read_text())
            self.assertEqual(saved['days'][previous]['cross_day_version'],2)
            self.assertEqual(saved['days'][previous]['slots'][0]['couriers'][0]['shift_end'],END)
            selected=choose(saved['days'][previous]['slots']+saved['days'][day]['slots'],day)
            self.assertEqual([slot['slot_id'] for slot in selected],[10])
            with patch('courier_details.datetime',wraps=datetime) as clock:
                clock.now.return_value=NOW
                details=build_details(day,{'shop_id':7745,'slots':[]},
                    {'slot_fill':{},'planned_completion':result},completion_slots=selected)
            completion=details['metrics']['planned_completion']
            self.assertTrue(completion['reconciled'])
            fact=completion['groups'][0]['couriers'][0]['slots'][0]
            self.assertEqual(fact['actual_start'],START)
            self.assertEqual(fact['actual_end'],END)
            self.assertEqual(fact['shift_end_source_date'],day)

    def test_old_same_start_boundary_does_not_hide_valid_midnight_continuation(self):
        sources={'2026-11-04':[raw(START,BOUNDARY,slot_id=20),
            raw(MIDNIGHT,END,slot_id=21)]}
        result,_=self.resolve_with([origin()],sources)
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_end'],END)
        self.assertEqual(person['shift_end_raw'],BOUNDARY)
        self.assertEqual(person['shift_end_source_date'],'2026-11-04')

    def test_old_same_start_boundary_does_not_stop_multiday_reset_chain(self):
        middle_end='2026-11-04T23:59:59+03:00'
        final_end='2026-11-05T08:00:00+03:00'
        sources={
            '2026-11-04':[raw(START,BOUNDARY,slot_id=20),
                raw(MIDNIGHT,middle_end,slot_id=21)],
            '2026-11-05':[raw('2026-11-05T00:00:00+03:00',final_end,
                day='2026-11-05',slot_id=22)],
        }
        result,_=self.resolve_with([origin()],sources)
        person=result[0]['couriers'][0]
        self.assertEqual(person['shift_end'],final_end)
        self.assertEqual(person['shift_end_raw'],BOUNDARY)
        self.assertEqual(person['shift_end_source_date'],'2026-11-05')
