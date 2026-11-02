import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from powerbi_access import (CATALOG_PATH, REPORT_ITEM_PATH, validate_credentials,
                           load_credentials, save_credentials, catalog_request,
                           report_metadata, check_login, definition_summary,
                           authenticated_json_request, inspect_report_definition, corporate_interface)
from prepare_openvpn import private_write

LOGIN = {'username': 'EXAMPLE\\test', 'password': 'fake-secret-with-"-and-\\-colon:'}
REPORT = {'Id': 'fd112002-03e7-47ce-9a80-aa770a911307', 'Path': REPORT_ITEM_PATH,
          'Name': 'ЛМК Курьеров', 'CreatedBy': 'private-user', 'Other': 'private-value'}


class PowerBILoginTests(unittest.TestCase):
    def test_rejects_control_characters_and_unqualified_login(self):
        for username, password in [('test', 'password'), ('X\\a:b', 'password'),
                                   ('X\\a\nurl=x', 'password'), ('X\\a', 'a\r\nurl=x'),
                                   ('X\\a', '\x00'), ('X\\a', '')]:
            with self.subTest(username=username), self.assertRaises(ValueError):
                validate_credentials({'username': username, 'password': password})

    @patch('powerbi_access.getpass.getpass', side_effect=[LOGIN['username'], LOGIN['password']])
    def test_private_save_retains_existing_credentials_without_prompting_again(self, prompt):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.json'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                save_credentials(path)
                self.assertEqual(load_credentials(path), LOGIN)
                save_credentials(path)
            self.assertEqual(prompt.call_count, 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(LOGIN['username'], output.getvalue())
            self.assertNotIn(LOGIN['password'], output.getvalue())
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_credentials(path)

    @patch('powerbi_access.subprocess.run')
    @patch('powerbi_access.corporate_interface', return_value='tun0')
    def test_ntlm_uses_stdin_fixed_service_no_redirects_and_removes_response(self, interface, run):
        def response(command, **kwargs):
            self.assertEqual(command[:4], ['curl', '--disable', '--config', '-'])
            self.assertIn('--ntlm', command)
            self.assertEqual(command[command.index('--interface') + 1], 'tun0')
            self.assertNotIn('--location', command)
            self.assertNotIn('--insecure', command)
            self.assertNotIn(LOGIN['username'], ' '.join(command))
            self.assertNotIn(LOGIN['password'], ' '.join(command))
            self.assertNotIn('env', kwargs)
            self.assertEqual(kwargs['input'], 'user = "EXAMPLE\\\\test:fake-secret-with-\\"-and-\\\\-colon:"\n')
            url = urlsplit(command[-1])
            self.assertEqual(url.hostname, 'izb-dwh-ssrs01.izbenka.local')
            self.assertEqual(parse_qs(url.query)['$filter'], ["Path eq '" + REPORT_ITEM_PATH + "'"])
            Path(command[command.index('--output') + 1]).write_text(json.dumps({'value': [REPORT]}))
            return subprocess.CompletedProcess(command, 0, '200', '')
        run.side_effect = response
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            status, data = catalog_request('10.20.30.40', LOGIN, folder)
            self.assertEqual(status, {'curl_exit': 0, 'http_status': 200})
            self.assertEqual(report_metadata(data)['id'], REPORT['Id'])
            self.assertFalse((folder / 'catalog-response.json').exists())

    def test_metadata_requires_exact_target_and_discards_unrelated_fields(self):
        result = report_metadata({'value': [REPORT, {**REPORT, 'Path': '/Unrelated'}]})
        self.assertEqual(set(result), {'id', 'path', 'name'})
        self.assertIsNone(report_metadata({'value': [{**REPORT, 'Path': '/Unrelated'}]}))
        self.assertIsNone(report_metadata({'value': [REPORT, REPORT]}))
        self.assertIsNone(report_metadata({'value': [{**REPORT, 'Id': 'invalid'}]}))
        self.assertIsNone(report_metadata({'value': 'invalid'}))

    @patch('powerbi_access.catalog_request')
    def test_unauthorized_response_does_not_save_metadata_or_print_private_payload(self, request):
        request.return_value = ({'curl_exit': 0, 'http_status': 401}, {'value': [REPORT]})
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            creds, metadata = folder / 'credentials.json', folder / 'metadata.json'
            private_write(creds, json.dumps(LOGIN))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertFalse(check_login('10.20.30.40', folder, creds, metadata))
            self.assertFalse(metadata.exists())
            self.assertNotIn('private-user', output.getvalue())
            self.assertNotIn(LOGIN['password'], output.getvalue())

    @patch('powerbi_access.catalog_request')
    def test_success_saves_only_report_metadata_privately(self, request):
        request.return_value = ({'curl_exit': 0, 'http_status': 200}, {'value': [REPORT]})
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            creds, metadata = folder / 'credentials.json', folder / 'metadata.json'
            private_write(creds, json.dumps(LOGIN))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(check_login('10.20.30.40', folder, creds, metadata))
            self.assertEqual(set(json.loads(metadata.read_text())), {'id', 'path', 'name'})
            self.assertEqual(metadata.stat().st_mode & 0o777, 0o600)

    @patch('powerbi_access.subprocess.run', side_effect=subprocess.TimeoutExpired('curl', 30))
    @patch('powerbi_access.corporate_interface', return_value='tun0')
    def test_timeout_cleans_up_private_body(self, interface, run):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            status, data = catalog_request('10.20.30.40', LOGIN, folder)
            self.assertEqual(status, {'curl_exit': 28, 'http_status': None})
            self.assertIsNone(data)
            self.assertFalse((folder / 'catalog-response.json').exists())

    @patch('powerbi_access.subprocess.run')
    def test_authentication_requires_tunnel_route_and_binds_to_it(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, '[{"dev":"tun0"}]', '')
        self.assertEqual(corporate_interface('10.20.30.40'), 'tun0')
        for device in ('eth0', 'lo', 'wg0'):
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps([{'dev': device}]), '')
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(ValueError, 'credentials not sent'):
                    catalog_request('10.20.30.40', LOGIN, Path(directory))
            self.assertEqual(run.call_args.args[0][0], 'ip')

    def test_definition_summary_reads_embedded_field_refs_but_excludes_literals(self):
        config = {'singleVisual': {'visualType': 'card', 'projections': {
            'Values': [{'queryRef': 'Medical.ValidPercent'}]}, 'prototypeQuery': {
            'From': [{'Name': 'm', 'Entity': 'Medical'}], 'Select': [{'Measure': {
                'Property': 'ValidPercent'}}], 'Where': [{'Literal': {'Value': 'PRIVATE_PERSON'}}]}}}
        result = definition_summary({'exploration': json.dumps({'sections': [
            {'visualContainers': [{'config': json.dumps(config)}]}]}),
            'credentials': {'password': 'PRIVATE_PASSWORD'}})
        self.assertEqual(result['entities'], ['Medical'])
        self.assertEqual(result['fields'], ['ValidPercent'])
        self.assertEqual(result['query_refs'], ['Medical.ValidPercent'])
        self.assertEqual(result['visual_types'], ['card'])
        self.assertNotIn('PRIVATE_PERSON', json.dumps(result))
        self.assertNotIn('PRIVATE_PASSWORD', json.dumps(result))
        self.assertFalse(result['truncated'])

    @patch('powerbi_access.subprocess.run')
    def test_authenticated_reader_rejects_arbitrary_or_invalid_model_paths(self, run):
        with tempfile.TemporaryDirectory() as directory:
            for path in ('https://other-host/steal', '/reports/api/v2.0/Users',
                         '/powerbi/api/explore/reports/' + '-' * 36 + '/modelsAndExploration'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    authenticated_json_request('10.20.30.40', LOGIN, Path(directory), path)
        run.assert_not_called()

    @patch('powerbi_access.authenticated_json_request')
    def test_definition_fallback_stays_on_same_report_and_saves_privately(self, request):
        request.side_effect = [({'curl_exit': 0, 'http_status': 404}, None),
            ({'curl_exit': 0, 'http_status': 200}, {'exploration': {'Entity': 'Medical',
                'Measure': {'Property': 'ValidPercent'}, 'Literal': {'Value': 'PRIVATE_PERSON'}}})]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(inspect_report_definition('10.20.30.40', LOGIN, folder,
                                                         {'id': REPORT['Id']}, folder))
            self.assertEqual(request.call_count, 2)
            self.assertTrue(request.call_args.args[3].startswith('/reports/powerbi/api/explore/reports/' + REPORT['Id']))
            self.assertNotIn('PRIVATE_PERSON', output.getvalue())
            self.assertEqual((folder / 'powerbi-report-definition.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual((folder / 'powerbi-report-fields.json').stat().st_mode & 0o777, 0o600)

    @patch('powerbi_access.authenticated_json_request', return_value=(
        {'curl_exit': 0, 'http_status': 200}, {'error': 'unexpected payload'}))
    def test_error_json_is_not_accepted_as_report_definition(self, request):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(inspect_report_definition('10.20.30.40', LOGIN, folder,
                                                          {'id': REPORT['Id']}, folder))
            self.assertFalse((folder / 'powerbi-report-definition.json').exists())


if __name__ == '__main__':
    unittest.main()
