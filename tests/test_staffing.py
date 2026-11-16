import gzip
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from staffing.core import analyse, working_seconds, week, need, weighted
from run_staffing_report import load
D=datetime(2026,10,12)

def row(identity=1,**kw):
    x={'id_order':identity,'shopno':8889,'date_supply':'2026-10-12T10:00:00',
       'date_delivery_start':'2026-10-12T10:00:00','date_delivered':'2026-10-12T11:00:00',
       'order_closed_offline_dttm':None,'status_name':'Успешно завершен',
       'delivery_type_group':'Курьеры','id_courier_type':'2','courier_type':'Вело','courier':' Тест ИВАН  '}
    x.update(kw);return x

class StaffingTests(unittest.TestCase):
    def test_methodology_example(self):
        intervals=[(D.replace(hour=a,minute=b),D.replace(hour=c,minute=d)) for a,b,c,d in [(9,0,9,30),(10,0,10,40),(12,0,12,40),(13,0,14,0)]]
        self.assertEqual(working_seconds(intervals),3*3600+40*60)

    def test_gap_exact_boundary_and_overlap(self):
        self.assertEqual(working_seconds([(D,D+timedelta(hours=1)),(D+timedelta(hours=2),D+timedelta(hours=3))]),10800)
        self.assertEqual(working_seconds([(D,D+timedelta(hours=1)),(D+timedelta(hours=2,seconds=1),D+timedelta(hours=3))]),7199)
        self.assertEqual(working_seconds([(D,D+timedelta(hours=3)),(D+timedelta(hours=1),D+timedelta(hours=2))]),10800)

    def test_fifty_hours_is_side_and_names_merge(self):
        rows=[]
        for i in range(5):
            day=D+timedelta(days=i)
            rows.append(row(i+1,courier='тест иван' if i%2 else ' ТЕСТ  ИВАН ',date_supply=day.isoformat(),date_delivery_start=day.replace(hour=8).isoformat(),date_delivered=day.replace(hour=18).isoformat()))
        w=analyse(rows)['shops']['8889']['weeks'][0]
        self.assertEqual(w['staff'],1);self.assertEqual(w['groups']['side']['staff'],1)
        self.assertEqual(w['shifts'],5)
        rows.append(row(6,date_delivery_start='2026-10-17T08:00:00',date_delivered='2026-10-17T09:00:00',date_supply='2026-10-17T08:00:00'))
        self.assertEqual(analyse(rows)['shops']['8889']['weeks'][0]['groups']['core']['staff'],1)

    def test_workload_includes_cancelled_mobile_and_nameless(self):
        rows=[row(1),row(2,status_name='Отменен'),row(3,id_courier_type='9'),row(4,courier='')]
        report=analyse(rows);w=report['shops']['8889']['weeks'][0]
        self.assertEqual(w['load_orders'],4);self.assertEqual(w['groups']['side']['orders'],1)
        self.assertEqual(w['shifts'],1)

    def test_exact_dedup_and_conflicting_versions(self):
        self.assertEqual(analyse([row(),row()])['unique_shop_orders'],1)
        with self.assertRaises(ValueError):analyse([row(),row(status_name='Отменен')])

    def test_overnight_belongs_to_start_day(self):
        r=row(date_supply='2026-10-18T23:00:00',date_delivery_start='2026-10-18T23:00:00',date_delivered='2026-10-19T01:00:00')
        w=analyse([r])['shops']['8889']['weeks'][0]
        self.assertEqual(w['groups']['side']['seconds'],7200);self.assertEqual(w['shifts'],1)

    def test_bad_weather_keeps_same_staff(self):
        n=need(1000)
        self.assertEqual(n['staff'],38)
        self.assertAlmostEqual(n['bad']['shifts']/n['good']['shifts'],4/3)

    def test_week_boundaries(self):
        self.assertEqual(week(date(2026,10,12)),910)
        self.assertEqual(week(date(2026,11,15)),914)
        self.assertEqual(week(date(2026,11,16)),915)

    def test_offline_end_and_anomaly(self):
        r=row(order_closed_offline_dttm='2026-10-12T12:00:00')
        self.assertEqual(analyse([r])['shops']['8889']['weeks'][0]['groups']['side']['seconds'],7200)
        r['order_closed_offline_dttm']='2026-10-13T12:00:00'
        self.assertEqual(analyse([r])['exclusions']['over_12h_quarantined_hours_excluded'],1)

    def test_unverified_export_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.gz'
            with gzip.open(p,'wt') as f:json.dump({'complete':False},f)
            with self.assertRaises(ValueError):load(p)

    def test_weighted_totals_do_not_average_percentages(self):
        from staffing.core import group_totals
        a=group_totals([{'group':'core','seconds':51*3600,'shifts':7,'orders':100}])
        b=group_totals([{'group':'side','seconds':3600,'shifts':1,'orders':2} for _ in range(9)])
        total=weighted([a,b])
        self.assertEqual(total['groups']['core']['staff_percent'],10)
        self.assertAlmostEqual(total['groups']['core']['shift_percent'],7/16*100)

    def test_same_courier_is_classified_per_shop_and_week(self):
        report=analyse([row(1),row(2,shopno=9107),row(3,date_supply='2026-10-19T10:00:00',date_delivery_start='2026-10-19T10:00:00',date_delivered='2026-10-19T11:00:00')])
        self.assertEqual(report['combined']['staff_weeks'],3)
