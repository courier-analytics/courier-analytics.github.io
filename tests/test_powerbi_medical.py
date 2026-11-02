import contextlib
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from powerbi_medical import build_request, decode_rows, candidate_records, query_request, PROPERTIES, WINDOW


def definition():
    selected = []
    for i, prop in enumerate(PROPERTIES):
        selected.append({('Column' if i == 0 else 'Measure'): {
            'Expression': {'SourceRef': {'Source': 'a' if i == 0 else 'm'}},
            'Property': prop if i != 4 else prop.replace('% ', '%  ', 1)}, 'Name': 'field' + str(i)})
    selected.append({'Column': {'Expression': {'SourceRef': {'Source': 'a'}},
                                'Property': 'name'}, 'Name': 'PRIVATE_COURIER_FIELD'})
    query = {'Version': 2, 'From': [{'Name': 'a', 'Entity': 'main_mc06', 'Type': 0},
                                   {'Name': 'm', 'Entity': 'Меры', 'Type': 0}], 'Select': selected}
    return {'report_id': 'fd112002-03e7-47ce-9a80-aa770a911307', 'base_path': '/powerbi',
            'definition': {'models': [{'id': '123'}], 'exploration': {'sections': [{
                'visualContainers': [{'config': json.dumps({'singleVisual': {'visualType': 'tableEx'}}),
                'query': json.dumps({'Commands': [{'SemanticQueryDataShapeCommand': {'Query': query}}]})}]}]}}}


def response():
    return {'results': [{'result': {'data': {'dsr': {'DS': [{'PH': [{'DM0': [
        {'S': [{'N': 'G0', 'DN': 'D0'}] + [{'N': 'M' + str(i)} for i in range(4)],
         'C': [0, 100, 90, 10, .2]},
        {'R': 2, 'C': [1, 90, 5, .15]}]}],
        'ValueDicts': {'D0': ['ДС 5818', 'ДС 7745']}}]}}}}]}


class PowerBIMedicalTests(unittest.TestCase):
    def test_query_uses_source_aggregate_fields_and_excludes_courier_fields(self):
        source = definition()
        original = copy.deepcopy(source)
        request = build_request(source)
        command = request['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']
        self.assertEqual(request['modelId'], '123')
        self.assertEqual(len(command['Query']['Select']), 5)
        self.assertNotIn('PRIVATE_COURIER_FIELD', json.dumps(request))
        self.assertEqual(command['Binding']['Primary']['Groupings'], [{'Projections': [0, 1, 2, 3, 4]}])
        self.assertEqual(command['Binding']['DataReduction']['Primary']['Window']['Count'], WINDOW)
        self.assertEqual(source, original)

    def test_rejects_redacted_definitions_and_unreviewed_report_filters(self):
        source = definition()
        source['literal_values_redacted'] = True
        with self.assertRaises(ValueError):
            build_request(source)
        source = definition()
        source['definition']['exploration']['filters'] = '[{"filter":"unreviewed"}]'
        with self.assertRaises(ValueError):
            build_request(source)
        source['definition']['exploration']['filters'] = 'unrecognized-encoding'
        with self.assertRaises(ValueError):
            build_request(source)

    def test_inactive_filter_cards_do_not_exclude_an_aggregate_table(self):
        source = definition()
        inactive = [{'name': 'filter-card', 'expression': {'Column': {
            'Expression': {'SourceRef': {'Entity': 'main_mc06'}}, 'Property': 'format'}},
            'type': 'Categorical'}]
        source['definition']['exploration']['sections'][0]['filters'] = json.dumps(inactive)
        source['definition']['exploration']['sections'][0]['visualContainers'][0]['filters'] = json.dumps(inactive)
        request = build_request(source)
        query = request['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']['Query']
        self.assertNotIn('Where', query)

    def test_prototype_is_used_when_optional_compiled_query_is_absent(self):
        source = definition()
        visual = source['definition']['exploration']['sections'][0]['visualContainers'][0]
        config = json.loads(visual['config'])
        config['singleVisual']['prototypeQuery'] = json.loads(visual['query'])['Commands'][0]['SemanticQueryDataShapeCommand']['Query']
        visual['config'] = json.dumps(config)
        visual['query'] = None
        diagnostic = {}
        request = build_request(source, diagnostic)
        self.assertEqual(diagnostic['query_source'], 'prototype')
        self.assertEqual(len(request['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']['Query']['Select']), 5)

    def test_format_filter_is_preserved_with_source_alias_rewritten(self):
        source = definition()
        scoped = {'Version': 2, 'From': [{'Name': 'different', 'Entity': 'main_mc06', 'Type': 0}],
                  'Where': [{'Condition': {'Comparison': {'ComparisonKind': 0,
                      'Left': {'Column': {'Expression': {'SourceRef': {'Source': 'different'}}, 'Property': 'format'}},
                      'Right': {'Literal': {'Value': "'DS'"}}}}}]}
        source['definition']['exploration']['filters'] = json.dumps([{'filter': scoped}])
        original = copy.deepcopy(source)
        diagnostic = {}
        query = build_request(source, diagnostic)['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']['Query']
        self.assertEqual(query['Where'][0]['Condition']['Comparison']['Left']['Column']['Expression']['SourceRef'], {'Source': 'a'})
        self.assertEqual(query['Where'][0]['Condition']['Comparison']['Right']['Literal']['Value'], "'DS'")
        self.assertEqual(diagnostic['scope_fields'], ['format'])
        self.assertEqual(source, original)

    def test_filters_on_people_or_medical_status_cannot_change_coverage_denominator(self):
        for prop in ('name', 'Есть ЛМК', 'ЛМК просрочена_'):
            source = definition()
            scope = {'Where': [{'Condition': {'In': {'Expressions': [{'Column': {
                'Expression': {'SourceRef': {'Entity': 'main_mc06'}}, 'Property': prop}}],
                'Values': [[{'Literal': {'Value': "'value'"}}]]}}}]}
            source['definition']['exploration']['filters'] = json.dumps([{'filter': scope}])
            with self.subTest(prop=prop), self.assertRaises(ValueError):
                build_request(source)

    def test_decodes_dictionary_and_repeat_masks_before_calculating_valid_books(self):
        rows = decode_rows(response(), ['field' + str(i) for i in range(5)])
        self.assertEqual(rows, [['ДС 5818', 100, 90, 10, .2], ['ДС 7745', 100, 90, 5, .15]])
        with contextlib.redirect_stdout(io.StringIO()):
            result = candidate_records(rows, datetime(2026, 11, 1, 22, tzinfo=timezone.utc))
        self.assertEqual([r['value'] for r in result['records']], [80, 85])
        self.assertEqual([r['numerator'] for r in result['records']], [80, 85])
        self.assertEqual({r['date'] for r in result['records']}, {'2026-11-02'})
        self.assertEqual({r['basis'] for r in result['records']}, {'present_and_not_expired_lmk'})
        self.assertNotIn('shop_label', result['records'][0])

    def test_descriptor_can_map_reordered_schema(self):
        payload = response()
        data = payload['results'][0]['result']['data']
        data['descriptor'] = {'Select': [
            {'Name': 'field0', 'Value': [{'Source': 'G0'}]}] + [
            {'Name': 'field' + str(i + 1), 'Value': 'M' + str(i)} for i in range(4)]}
        rows = data['dsr']['DS'][0]['PH'][0]['DM0']
        rows[:] = [{'S': [{'N': 'M2'}, {'N': 'G0', 'DN': 'D0'}, {'N': 'M0'}, {'N': 'M1'}, {'N': 'M3'}],
                    'C': [10, 0, 100, 90, .2]}]
        self.assertEqual(decode_rows(payload, ['field' + str(i) for i in range(5)]),
                         [['ДС 5818', 100, 90, 10, .2]])

    def test_null_count_is_not_converted_to_zero(self):
        payload = response()
        payload['results'][0]['result']['data']['dsr']['DS'][0]['PH'][0]['DM0'][:] = [
            {'S': [{'N': 'G0', 'DN': 'D0'}] + [{'N': 'M' + str(i)} for i in range(4)],
             'Ø': 8, 'C': [0, 100, 90, .1]}]
        rows = decode_rows(payload, ['field' + str(i) for i in range(5)])
        self.assertIsNone(rows[0][3])
        with self.assertRaises(ValueError):
            candidate_records(rows, datetime.now(timezone.utc), shops=(5818,))

    def test_rejects_partial_invalid_or_ambiguous_aggregates(self):
        for mutate in (
            lambda ds: ds['PH'][0].update({'RT': ['continuation']}),
            lambda ds: ds['PH'][0].update({'DM0': [ds['PH'][0]['DM0'][0]] * WINDOW}),
            lambda ds: ds['PH'][0]['DM0'][0].update({'R': 1}),
            lambda ds: ds['PH'][0]['DM0'][0]['C'].append(123),
            lambda ds: ds['PH'][0]['DM0'][0]['C'].__setitem__(0, 999)):
            payload = response()
            mutate(payload['results'][0]['result']['data']['dsr']['DS'][0])
            with self.assertRaises(ValueError):
                decode_rows(payload, ['field' + str(i) for i in range(5)])
        with self.assertRaises(ValueError):
            candidate_records([['ДС 17745', 100, 90, 10, .2]], datetime.now(timezone.utc), shops=(7745,))
        with self.assertRaises(ValueError):
            candidate_records([['ДС 7745', 100, 90, 10, .2]] * 2, datetime.now(timezone.utc), shops=(7745,))

    def test_counts_must_agree_with_source_invalid_book_percentage(self):
        now = datetime.now(timezone.utc)
        for row in (['ДС 7745', 100, 90, 10, .1], ['ДС 7745', 0, 0, 0, 0],
                    ['ДС 7745', 100, 10, 20, .5], ['ДС 7745', 100, None, 0, .1],
                    ['ДС 7745', True, 1, 0, 0], ['ДС 7745', 100, 90, 10, float('nan')]):
            with self.subTest(row=row), self.assertRaises(ValueError):
                candidate_records([row], now, shops=(7745,))
        with contextlib.redirect_stdout(io.StringIO()):
            result = candidate_records([['ДС 7745', 100, 90, 10, 20]], now, shops=(7745,))
        self.assertEqual(result['records'][0]['value'], 80)

    @patch('powerbi_medical.corporate_interface', return_value='tun0')
    @patch('powerbi_medical.subprocess.run')
    def test_read_query_keeps_secrets_on_stdin_and_cleans_up_files(self, run, interface):
        payload = build_request(definition())
        credentials = {'username': 'EXAMPLE\\user', 'password': 'fake-password'}
        def execute(command, **kwargs):
            self.assertEqual(command[-1], 'http://izb-dwh-ssrs01.izbenka.local/powerbi/api/explore/querydata')
            self.assertNotIn('fake-password', ' '.join(command))
            self.assertNotIn('--location', command)
            self.assertEqual(command[command.index('--interface') + 1], 'tun0')
            body = Path(command[command.index('--data-binary') + 1][1:])
            self.assertEqual(json.loads(body.read_text()), payload)
            self.assertEqual(body.stat().st_mode & 0o777, 0o600)
            Path(command[command.index('--output') + 1]).write_text(json.dumps(response()))
            self.assertIn('fake-password', kwargs['input'])
            return subprocess.CompletedProcess(command, 0, '200', '')
        run.side_effect = execute
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            status, data = query_request('10.20.30.40', credentials, folder, '/powerbi', payload)
            self.assertEqual(status['http_status'], 200)
            self.assertEqual(len(decode_rows(data, ['field' + str(i) for i in range(5)])), 2)
            self.assertEqual(list(folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
