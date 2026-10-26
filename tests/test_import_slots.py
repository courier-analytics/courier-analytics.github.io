import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from import_slots import parse_rows, summarize

HEADERS = ['Дата', 'Код ТТ', 'ID кластера', 'ID слота', 'Тип слота',
           'Начало', 'Окончание', 'Записалось', 'ID курьера',
           'Статус смены', 'Начало смены', 'Окончание смены']


def row(slot=1, cluster='', occupancy='2 из 3', ids='11, 12'):
    return ['2026-10-25', '5818', cluster, slot, 'Лимитированный',
            '07:00', '19:00', occupancy, ids, 'Вышел', '07:00', '19:00']


class ImportTests(unittest.TestCase):
    def test_group_does_not_copy_shared_shift_facts(self):
        slots = parse_rows(HEADERS, [row()])
        self.assertEqual(len(slots[0]['couriers']), 2)
        self.assertTrue(all(c['shift_status'] is None and c['shift_end'] is None
                            for c in slots[0]['couriers']))
        self.assertEqual(summarize(slots)[0]['records_requiring_api'], 2)

    def test_direct_and_cluster_slots_count_places_not_unique_people(self):
        slots = parse_rows(HEADERS, [row(), row(2, '7332', '1 из 2', '11')])
        summary = summarize(slots)[0]
        self.assertEqual(summary['fill_percent'], 60)
        self.assertEqual(summary['unique_couriers'], 2)
        self.assertEqual(summary['courier_slot_records'], 3)
        self.assertEqual(summary['cluster_ids'], [7332])

    def test_empty_capacity_is_unknown_not_full(self):
        summary = summarize(parse_rows(HEADERS, [row(occupancy='0 из 0', ids='')]))[0]
        self.assertIsNone(summary['fill_percent'])

    def test_duplicate_and_count_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            parse_rows(HEADERS, [row(), row()])
        with self.assertRaises(ValueError):
            parse_rows(HEADERS, [row(occupancy='1 из 3')])


if __name__ == '__main__':
    unittest.main()
