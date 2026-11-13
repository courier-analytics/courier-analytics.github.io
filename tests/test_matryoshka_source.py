import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from matryoshka_source import employment

class EmploymentTests(unittest.TestCase):
    def test_blank_partner_means_self_employed(self):
        for value in (None, '', ' ', '-', '—', '–'):
            self.assertEqual(employment({'courier_kontr': value, 'id_courier_kontr': None}), 'self_employed')

    def test_named_partner_is_not_self_employed(self):
        self.assertEqual(employment({'courier_kontr': 'Подрядчик', 'id_courier_kontr': '00210'}), 'partner')

    def test_missing_or_conflicting_fields_are_unknown(self):
        for row in ({}, {'courier_kontr': None}, {'courier_kontr': None, 'id_courier_kontr': '00210'}):
            self.assertEqual(employment(row), 'unknown')
