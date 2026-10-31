from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from report_attendance import observations,status,render

class AttendanceTests(unittest.TestCase):
    def test_manual_and_limited_records_unique_vs_multiple_slots(self):
        slots=[]
        for i,kind in enumerate(('manual','limited')):
            slots.append({'slot_id':i,'name':'ДС','slot_type':kind,'time_from':'08:00','time_to':'20:00',
             'couriers':[{'courier_id':'1','name':'Курьер','shift_status':'Опоздал на 15 минут','shift_start':'08:15','shift_end':None},
                         {'courier_id':'2','name':'Ожидаемый','shift_status':'Ожидается','shift_start':None,'shift_end':None}]})
        totals,flagged=observations({'shop_id':7745,'slots':slots})
        self.assertEqual((totals['late_unique'],totals['late_records'],totals['no_show_records'],totals['expected_records']),(1,2,0,2))
        self.assertEqual({r['slot_type'] for r in flagged},{'manual','limited'})

    def test_no_show_requires_source_status(self):
        self.assertEqual(status(None),'unknown')
        self.assertEqual(status('Не вышел'),'no_show')
        self.assertEqual(status('no_show'),'no_show')
        self.assertEqual(status('Ожидается'),'expected')

    def test_missing_scope_not_zero_and_html_escaped(self):
        text,page,csv=render('2026-10-31','now',[{'shop_id':8889,'available':False,'reason':'<missing>'}])
        self.assertIn('данные недоступны',text)
        self.assertIn('&lt;missing&gt;',page)
        self.assertTrue(csv.startswith('\ufeff'))
