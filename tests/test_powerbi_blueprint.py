import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from powerbi_blueprint import blueprint, query_structure


class PowerBIBlueprintTests(unittest.TestCase):
    def test_removes_literals_credentials_rows_and_unselected_visuals(self):
        query = {'Version': 2, 'From': [{'Name': 'm', 'Entity': 'Medical', 'Type': 0}],
                 'Select': [{'Measure': {'Expression': {'SourceRef': {'Source': 'm'}},
                                        'Property': '% курьеров с ЛМК'}, 'Name': 'MedicalPercent'}],
                 'Where': [{'Condition': {'In': {'Values': [[{'Literal': {'Value': 'PRIVATE_PERSON'}}]]}}}],
                 'password': 'PRIVATE_PASSWORD', 'rows': [['PRIVATE_ROW']]}
        selected = {'config': json.dumps({'singleVisual': {'visualType': 'card',
                    'projections': {'Values': [{'queryRef': 'Medical.% курьеров с ЛМК'}]},
                    'prototypeQuery': query}}),
                    'query': json.dumps({'Commands': [{'SemanticQueryDataShapeCommand': {
                        'Query': query, 'Binding': {'Version': 1, 'Primary': {'Groupings': [{'Projections': [0]}]}}}}],
                        'CacheKey': 'PRIVATE_PERSON', 'accessToken': 'PRIVATE_TOKEN'})}
        payload = {'report_id': 'fd112002-03e7-47ce-9a80-aa770a911307', 'definition': {
            'models': [{'id': 42, 'accessToken': 'PRIVATE_TOKEN', 'connectionString': 'PRIVATE_CONNECTION'}],
            'exploration': {'sections': [{'visualContainers': [selected,
                {'config': json.dumps({'singleVisual': {'visualType': 'image'}})}]}]}}}
        result = blueprint(payload)
        text = json.dumps(result)
        for secret in ('PRIVATE_PERSON', 'PRIVATE_PASSWORD', 'PRIVATE_ROW', 'PRIVATE_TOKEN', 'PRIVATE_CONNECTION'):
            self.assertNotIn(secret, text)
        self.assertEqual(result['models'][0]['id'], 42)
        self.assertEqual(len(result['visuals']), 1)
        self.assertTrue(result['literal_values_redacted'])
        self.assertEqual(result['visuals'][0]['prototype_query']['From'], query['From'])
        self.assertEqual(result['visuals'][0]['query']['Commands'][0]['SemanticQueryDataShapeCommand']['Binding'],
                         {'Version': 1, 'Primary': {'Groupings': [{'Projections': [0]}]}})

    def test_unsupported_or_empty_definition_is_not_exported(self):
        for definition in ({}, {'exploration': {'sections': []}}):
            with self.assertRaises(ValueError):
                blueprint({'report_id': 'fd112002-03e7-47ce-9a80-aa770a911307', 'definition': definition})

    def test_limits_nesting_and_arrays(self):
        data = {'Query': None}
        for _ in range(45):
            data = {'Query': data}
        with self.assertRaises(ValueError):
            query_structure(data)
        with self.assertRaises(ValueError):
            query_structure([None] * 10001)


if __name__ == '__main__':
    unittest.main()
