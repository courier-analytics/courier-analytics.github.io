import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from medical_feed import validate, merge


def feed(day='2026-11-02'):
    return {'schema_version': 1, 'records': [{
        'date': day, 'shop_id': 7745, 'numerator': 36, 'denominator': 44,
        'value': 81.82, 'source': 'powerbi_lmk', 'basis': 'present_and_not_expired_lmk',
        'reported_at': day + 'T14:00:00+00:00', 'private_field': 'never public'}]}


class MedicalFeedTests(unittest.TestCase):
    def test_public_whitelist_and_observation_date(self):
        self.assertNotIn('private_field', validate(feed())['records'][0])
        for field, value in [('numerator', 45), ('denominator', 0), ('value', 84.1),
                             ('reported_at', '2026-11-01T14:00:00+00:00'),
                             ('source', 'slots_export')]:
            payload = feed()
            payload['records'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(payload)

    def test_history_is_preserved_and_older_observation_cannot_replace_newer(self):
        previous = feed()
        older = copy.deepcopy(previous)
        older['records'][0].update(numerator=35, value=79.55, reported_at='2026-11-02T13:00:00+00:00')
        self.assertEqual(merge(previous, older)['records'][0]['numerator'], 36)
        self.assertEqual(len(merge(previous, feed('2026-11-03'))['records']), 2)
