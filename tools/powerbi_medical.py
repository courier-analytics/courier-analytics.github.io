"""Read aggregate LMK counts; prepare a private candidate, never publish it."""
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
from uuid import UUID
from zoneinfo import ZoneInfo

from powerbi_access import HOST, corporate_interface, curl_credentials
from powerbi_blueprint import parsed
from prepare_openvpn import private_write

PROPERTIES = ('name_TT', 'Всего курьеров', 'Курьеров с ЛМК',
              'Курьеров, ЛМК просрочена', '% курьеров нет ЛМК или просроченные')
WINDOW = 5000
SHOPS = (5818, 7745)


def normalized(value):
    return ' '.join(value.split()) if isinstance(value, str) else None


def filter_queries(value):
    if value in (None, '', [], {}):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            raise ValueError('Report filter encoding needs review')
    if value is None:
        return []
    if isinstance(value, list):
        return [query for item in value for query in filter_queries(item)]
    if not isinstance(value, dict):
        raise ValueError('Unexpected report filter structure')
    if 'filter' in value:
        return filter_queries(value['filter'])
    if 'Where' in value or set(value).issubset({'Version', 'From'}):
        if value.get('Where') and not isinstance(value['Where'], list):
            raise ValueError('Unexpected report filter conditions')
        return [value] if value.get('Where') else []
    if 'Condition' in value:
        return [{'From': [], 'Where': [value]}]
    metadata_keys = {'name', 'expression', 'type', 'howCreated', 'isHiddenInViewMode',
                     'isLockedInViewMode', 'objects', 'restatement', 'displayName'}
    if 'expression' in value and set(value).issubset(metadata_keys):
        # A filter-pane field/card without a semantic filter is not an active predicate.
        return []
    raise ValueError('Unrecognized active report filter; no predicates ignored')


def scoped_conditions(query, scopes):
    root_sources = {item['Name']: item['Entity'] for item in query['From']}
    root_aliases = {entity: alias for alias, entity in root_sources.items()}
    predicates = []
    field_names = set()
    column_count = 0
    for scope in [{'From': query['From'], 'Where': query.get('Where', [])}] + scopes:
        aliases = {item['Name']: item['Entity'] for item in scope.get('From', [])}
        # Filter From lists may retain unused entities from the report template.
        # Validate every actual reference below; unused declarations are not added
        # to the aggregate query and do not change its scope.

        def rewrite(value, depth=0):
            nonlocal column_count
            if depth > 40:
                raise ValueError('Report scope nesting exceeds limit')
            if isinstance(value, list):
                return [rewrite(item, depth + 1) for item in value]
            if not isinstance(value, dict):
                return value
            if 'Measure' in value:
                raise ValueError('Aggregate measure filters require explicit denominator review')
            if 'Column' in value:
                prop = value['Column'].get('Property')
                if prop not in ('name_TT', 'format'):
                    raise ValueError('Medical coverage scope must not filter individual couriers or medical status')
                field_names.add(prop)
                column_count += 1
            result = {}
            for key, item in value.items():
                if key == 'SourceRef':
                    entity = item.get('Entity') or aliases.get(item.get('Source')) or root_sources.get(item.get('Source'))
                    if entity != 'main_mc06':
                        label = entity if isinstance(entity, str) and len(entity) < 256 else '<unresolved>'
                        raise ValueError('Unsupported referenced entity in medical report scope: ' + label)
                    result[key] = {'Source': root_aliases[entity]}
                else:
                    result[key] = rewrite(item, depth + 1)
            return result

        for predicate in scope.get('Where') or []:
            fields_before = column_count
            rewritten = rewrite(predicate)
            if column_count == fields_before:
                raise ValueError('Report scope has no supported shop or format field')
            predicates.append(rewritten)
    return predicates, sorted(field_names)


def build_request(saved, diagnostic=None):
    if not isinstance(saved, dict) or saved.get('literal_values_redacted'):
        raise ValueError('Use the original private report definition')
    UUID(saved['report_id'])
    definition = saved['definition']
    models = definition['models']
    if not isinstance(models, list) or len(models) != 1:
        raise ValueError('Expected one report model')
    model_id = models[0]['id']
    if not isinstance(model_id, (str, int)) or isinstance(model_id, bool):
        raise ValueError('Invalid report model identity')
    exploration = parsed(definition['exploration'])
    report_scopes = filter_queries(exploration.get('filters', []))
    skipped = {}
    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1
    for section in exploration.get('sections', []):
        section_scopes = report_scopes + filter_queries(section.get('filters', []))
        for visual in section.get('visualContainers', []):
            config = parsed(visual.get('config'))
            query_container = parsed(visual.get('query'))
            if not isinstance(config, dict):
                skip('config_missing')
                continue
            single = config.get('singleVisual', {})
            if not isinstance(single, dict) or single.get('visualType') not in ('tableEx', 'pivotTable'):
                skip('not_aggregate_table')
                continue
            commands = query_container.get('Commands', []) if isinstance(query_container, dict) else []
            query = None
            query_source = 'prototype'
            if len(commands) == 1 and isinstance(commands[0], dict):
                source_command = commands[0].get('SemanticQueryDataShapeCommand')
                query = source_command.get('Query') if isinstance(source_command, dict) else None
                if isinstance(query, dict):
                    query_source = 'compiled'
            if not isinstance(query, dict):
                query = parsed(single.get('prototypeQuery'))
            if not isinstance(query, dict):
                skip('query_and_prototype_missing')
                continue
            source_rows = query.get('From')
            if not isinstance(source_rows, list) or len(source_rows) != 2 or any(
                    not isinstance(item, dict) or not isinstance(item.get('Name'), str) or
                    not isinstance(item.get('Entity'), str) or item.get('Type') != 0 for item in source_rows):
                skip('unsupported_sources')
                continue
            sources = {item['Name']: item['Entity'] for item in source_rows}
            if len(sources) != 2 or set(sources.values()) != {'main_mc06', 'Меры'}:
                skip('unsupported_sources')
                continue
            selected = {}
            for item in query.get('Select', []):
                kind = 'Column' if 'Column' in item else 'Measure'
                expression = item.get(kind, {})
                prop = normalized(expression.get('Property'))
                source = expression.get('Expression', {}).get('SourceRef', {}).get('Source')
                entity = sources.get(source)
                expected = 'main_mc06' if prop == 'name_TT' else 'Меры'
                if prop in PROPERTIES and entity == expected and kind == ('Column' if prop == 'name_TT' else 'Measure'):
                    if prop in selected:
                        raise ValueError('Duplicate required medical field')
                    selected[prop] = copy.deepcopy(item)
            if set(selected) != set(PROPERTIES):
                skip('required_aggregate_fields_missing')
                continue
            scopes = section_scopes + filter_queries(visual.get('filters', [])) + filter_queries(config.get('filters', []))
            where, scope_fields = scoped_conditions(query, scopes)
            aggregate_query = copy.deepcopy(query)
            aggregate_query['Select'] = [selected[prop] for prop in PROPERTIES]
            aggregate_query.pop('OrderBy', None)
            if where:
                aggregate_query['Where'] = where
            else:
                aggregate_query.pop('Where', None)
            if diagnostic is not None:
                diagnostic.update({'query_source': query_source, 'scope_predicates': len(where),
                                   'scope_fields': scope_fields, 'selected_aggregate_columns': len(PROPERTIES)})
            command = {'Query': aggregate_query, 'Binding': {'Primary': {'Groupings': [
                {'Projections': list(range(len(PROPERTIES)))}]}, 'DataReduction': {
                'DataVolume': 3, 'Primary': {'Window': {'Count': WINDOW}}}, 'Version': 1},
                'ExecutionMetricsKind': 1}
            return {'version': '1.0.0', 'modelId': model_id, 'queries': [
                {'Query': {'Commands': [{'SemanticQueryDataShapeCommand': command}]}}],
                'cancelQueries': []}
    raise ValueError('No compatible medical aggregate table; selection diagnostics: ' + json.dumps(skipped))


def scope_summary(saved):
    """Describe filter entities and fields only; never emit literal values."""
    exploration = parsed(saved.get('definition', {}).get('exploration', {}))
    if not isinstance(exploration, dict):
        return [{'scope': 'report', 'definition_recognized': False}]
    contexts = [('report', exploration.get('filters', []))]
    for section in exploration.get('sections', []):
        for visual in section.get('visualContainers', []):
            config = parsed(visual.get('config'))
            single = config.get('singleVisual', {}) if isinstance(config, dict) else {}
            if isinstance(single, dict) and single.get('visualType') in ('tableEx', 'pivotTable'):
                contexts.extend([('section', section.get('filters', [])),
                                 ('visual', visual.get('filters', [])), ('config', config.get('filters', []))])
                container = parsed(visual.get('query'))
                commands = container.get('Commands', []) if isinstance(container, dict) else []
                source_command = commands[0].get('SemanticQueryDataShapeCommand') if commands and isinstance(commands[0], dict) else None
                query = source_command.get('Query') if isinstance(source_command, dict) else None
                if not isinstance(query, dict):
                    query = parsed(single.get('prototypeQuery'))
                if isinstance(query, dict):
                    contexts.append(('query', {'From': query.get('From', []), 'Where': query.get('Where', [])}))
                break
        else:
            continue
        break
    output = []
    for context, value in contexts:
        try:
            filters = filter_queries(value)
        except (ValueError, TypeError, AttributeError):
            output.append({'scope': context, 'filter_encoding_recognized': False})
            continue
        for query in filters:
            aliases = {item.get('Name'): item.get('Entity') for item in (query.get('From') or [])
                       if isinstance(item, dict) and isinstance(item.get('Name'), str)}
            refs, stack, visited = set(), [query.get('Where', [])], 0
            while stack and visited < 10000:
                item = stack.pop()
                visited += 1
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    for kind in ('Column', 'Measure'):
                        expression = item.get(kind)
                        if isinstance(expression, dict):
                            ref = expression.get('Expression', {}).get('SourceRef', {})
                            entity = ref.get('Entity') or aliases.get(ref.get('Source')) or '<unresolved>'
                            prop = expression.get('Property')
                            if isinstance(entity, str) and isinstance(prop, str):
                                refs.add((entity[:256], prop[:256]))
                    stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            output.append({'scope': context, 'declared_entities': sorted({v for v in aliases.values() if isinstance(v, str)}),
                           'referenced_fields': [{'entity': entity, 'field': prop} for entity, prop in sorted(refs)[:20]],
                           'truncated': bool(stack) or len(refs) > 20})
    return output


def preflight(private_folder=Path('/opt/courier-analytics/private')):
    saved = json.loads((private_folder / 'powerbi-report-definition.json').read_text())
    diagnostic = {}
    try:
        build_request(saved, diagnostic)
        print('Local medical structure check: ready; ' + json.dumps(diagnostic, ensure_ascii=False), flush=True)
        return True
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        print('Local medical structure check: ' + str(error), flush=True)
        print('Safe medical scope context: ' + json.dumps(scope_summary(saved), ensure_ascii=False, indent=2), flush=True)
        return False


def query_request(address, credentials, folder, base_path, payload):
    if base_path not in ('/powerbi', '/reports/powerbi'):
        raise ValueError('Unexpected report web-client base path')
    interface = corporate_interface(address)
    request_path, response_path = folder / 'medical-request.json', folder / 'medical-response.json'
    private_write(request_path, json.dumps(payload, ensure_ascii=False))
    private_write(response_path, '')
    command = ['curl', '--disable', '--config', '-', '--ntlm', '--http1.1',
               '--proxy', '', '--noproxy', '*', '--interface', interface, '--silent',
               '--connect-timeout', '5', '--max-time', '35', '--max-filesize', '8388608',
               '--resolve', f'{HOST}:80:{address}', '--header', 'Accept: application/json',
               '--header', 'Content-Type: application/json',
               '--header', f'Origin: http://{HOST}', '--referer', f'http://{HOST}{base_path}/',
               '--data-binary', '@' + str(request_path), '--output', str(response_path),
               '--write-out', '%{http_code}', f'http://{HOST}{base_path}/api/explore/querydata']
    try:
        result = subprocess.run(command, input=curl_credentials(credentials), capture_output=True,
                                text=True, timeout=40)
        code = result.stdout.strip()
        status = int(code) if re.fullmatch(r'[1-5][0-9]{2}', code) else None
        data = None
        if result.returncode == 0 and status == 200 and response_path.stat().st_size <= 8388608:
            try:
                data = json.loads(response_path.read_text(encoding='utf-8-sig'))
            except (ValueError, UnicodeError, RecursionError):
                pass
        return {'curl_exit': result.returncode, 'http_status': status}, data
    except subprocess.TimeoutExpired:
        return {'curl_exit': 28, 'http_status': None}, None
    finally:
        request_path.unlink(missing_ok=True)
        response_path.unlink(missing_ok=True)


def decode_rows(payload, select_names):
    results = payload.get('results') if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError('Unexpected query result envelope')
    data = results[0].get('result', {}).get('data', {})
    dsr = data.get('dsr', {})
    datasets = dsr.get('DS', [])
    if not isinstance(datasets, list) or len(datasets) != 1:
        raise ValueError('Unexpected DSR dataset count')
    dataset = datasets[0]
    partitions = dataset.get('PH', [])
    if len(partitions) != 1 or 'DM0' not in partitions[0]:
        raise ValueError('Expected a flat aggregate partition')
    if dataset.get('RT') or partitions[0].get('RT'):
        raise ValueError('Query requires pagination; no partial import')
    encoded = partitions[0]['DM0']
    if not isinstance(encoded, list) or len(encoded) >= WINDOW:
        raise ValueError('Aggregate row window may be truncated')
    dictionaries = dataset.get('ValueDicts', dsr.get('ValueDicts', {}))
    descriptors = data.get('descriptor', {}).get('Select', [])
    field_names = {}
    for descriptor in descriptors:
        value = descriptor.get('Value')
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
            value = value[0].get('Source')
        if descriptor.get('Name') in select_names and isinstance(value, str):
            field_names[descriptor['Name']] = value
    expected_schema = ['G0', 'M0', 'M1', 'M2', 'M3']
    schema, previous, decoded = None, None, []
    for row in encoded:
        if any(re.fullmatch(r'DM\d+', key) for key in row):
            raise ValueError('Hierarchical aggregates are not supported')
        if 'S' in row:
            schema = row['S']
        if not isinstance(schema, list) or len(schema) != len(PROPERTIES):
            raise ValueError('Aggregate column schema is missing or changed')
        names = [column.get('N') for column in schema]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate aggregate columns')
        if len(field_names) == len(PROPERTIES):
            try:
                order = [names.index(field_names[name]) for name in select_names]
            except ValueError:
                raise ValueError('Descriptor does not match the aggregate schema')
        elif not descriptors and names == expected_schema:
            order = list(range(len(PROPERTIES)))
        else:
            raise ValueError('Unrecognized aggregate projection mapping')
        repeat, nulls = row.get('R', 0), row.get('Ø', 0)
        if any(not isinstance(mask, int) or isinstance(mask, bool) or mask < 0 or mask >= 1 << len(schema)
               for mask in (repeat, nulls)) or repeat & nulls:
            raise ValueError('Invalid aggregate masks')
        cells, current, position = row.get('C', []), [], 0
        if not isinstance(cells, list):
            raise ValueError('Invalid aggregate cells')
        for i, column in enumerate(schema):
            if repeat & (1 << i):
                if previous is None:
                    raise ValueError('Repeated value without a previous row')
                value = previous[i]
            elif nulls & (1 << i):
                value = None
            else:
                if position >= len(cells):
                    raise ValueError('Aggregate cells are incomplete')
                value = cells[position]
                position += 1
                dictionary = column.get('DN')
                if dictionary is not None:
                    values = dictionaries.get(dictionary)
                    if (not isinstance(values, list) or not isinstance(value, int) or
                            isinstance(value, bool) or not 0 <= value < len(values)):
                        raise ValueError('Invalid aggregate dictionary index')
                    value = values[value]
            current.append(value)
        if position != len(cells):
            raise ValueError('Unexpected extra aggregate cells')
        decoded.append([current[index] for index in order])
        previous = current
    return decoded


def candidate_records(rows, observed_at, shops=SHOPS):
    if observed_at.tzinfo is None:
        raise ValueError('Observation time must have a timezone')
    if not shops or len(set(shops)) != len(shops) or set(shops) - set(SHOPS):
        raise ValueError('Unexpected medical DS scope')
    result = []
    for shop in shops:
        matches = [row for row in rows if isinstance(row[0], str) and
                   re.search(r'(?<!\d)' + str(shop) + r'(?!\d)', row[0])]
        if len(matches) != 1:
            raise ValueError(f'DS {shop}: expected one unambiguous Power BI shop label, got {len(matches)}')
        label, total, has_book, expired, invalid_percent = matches[0]
        counts = (total, has_book, expired)
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n)
               or n < 0 or n > 9007199254740991 or int(n) != n for n in counts):
            raise ValueError(f'DS {shop}: invalid medical counts; nulls are not zero')
        total, has_book, expired = map(int, counts)
        if not total or not 0 <= expired <= has_book <= total:
            raise ValueError(f'DS {shop}: invalid medical denominator or count relationship')
        if isinstance(invalid_percent, bool) or not isinstance(invalid_percent, (int, float)) or not math.isfinite(invalid_percent):
            raise ValueError(f'DS {shop}: missing source cross-check percentage')
        valid = has_book - expired
        missing_or_expired = (total - valid) / total
        if not (math.isclose(invalid_percent, missing_or_expired, rel_tol=1e-8, abs_tol=1e-6) or
                math.isclose(invalid_percent, missing_or_expired * 100, rel_tol=1e-8, abs_tol=1e-4)):
            raise ValueError(f'DS {shop}: source missing-or-expired percentage does not confirm the valid-book calculation')
        record = {'date': observed_at.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat(),
                  'shop_id': shop, 'numerator': valid, 'denominator': total,
                  'value': round(valid / total * 100, 2), 'source': 'powerbi_lmk',
                  'basis': 'present_and_not_expired_lmk', 'reported_at': observed_at.isoformat()}
        print('Medical aggregate: ' + json.dumps({'shop_id': shop, 'shop_label': label,
              'total': total, 'with_lmk': has_book, 'expired': expired,
              'valid': valid, 'percent': record['value']}, ensure_ascii=False), flush=True)
        result.append(record)
    return {'schema_version': 1, 'records': result}


def response_shape(payload):
    if not isinstance(payload, dict):
        return {'json_object': False}
    result = {'root_keys': sorted(payload.keys())[:30]}
    try:
        data = payload['results'][0]['result']['data']
        dataset = data['dsr']['DS'][0]
        result.update({'data_keys': sorted(data.keys())[:30],
                       'dataset_keys': sorted(dataset.keys())[:30],
                       'descriptor': data.get('descriptor')})
        rows = dataset['PH'][0].get('DM0', [])
        result['row_count'] = len(rows)
        result['first_schema'] = rows[0].get('S') if rows else None
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    return result


def collect_candidate(address, credentials, folder, private_folder, shops=SHOPS):
    definition = json.loads((private_folder / 'powerbi-report-definition.json').read_text())
    diagnostic = {}
    try:
        request = build_request(definition, diagnostic)
    except ValueError:
        print('Safe medical scope context: ' + json.dumps(scope_summary(definition), ensure_ascii=False, indent=2), flush=True)
        raise
    print('Medical aggregate source context: ' + json.dumps(diagnostic, ensure_ascii=False), flush=True)
    status, data = query_request(address, credentials, folder, definition['base_path'], request)
    print('Power BI aggregate query: ' + json.dumps({**status, 'json_received': isinstance(data, dict)}), flush=True)
    if status['curl_exit'] or status['http_status'] != 200 or not isinstance(data, dict):
        return False
    private_write(private_folder / 'powerbi-medical-query-response.json', json.dumps(data, ensure_ascii=False))
    query = request['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']['Query']
    try:
        rows = decode_rows(data, [item['Name'] for item in query['Select']])
        candidate = candidate_records(rows, datetime.now(timezone.utc), shops=shops)
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        print('Aggregate validation: ' + str(error), flush=True)
        print('Safe response shape: ' + json.dumps(response_shape(data), ensure_ascii=False), flush=True)
        return False
    private_write(private_folder / 'medical-books-candidate.json', json.dumps(candidate, ensure_ascii=False))
    print('Validated medical candidate saved privately. Dashboard and timers unchanged.', flush=True)
    return True
