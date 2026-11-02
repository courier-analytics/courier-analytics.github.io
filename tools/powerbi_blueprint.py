"""Export report query structure without credentials, filter values, or data rows."""
import json
import os
from pathlib import Path
from uuid import UUID

from prepare_openvpn import private_write

ROOT = Path('/opt/courier-analytics/private')
QUERY_KEYS = set('Version From Name Entity Type Schema Select Column Measure Expression SourceRef Source Property Aggregation Function CountRows Arithmetic Left Right OrderBy Direction Where Condition Filter And Or Not In Expressions Values Comparison ComparisonKind Contains StartsWith EndsWith IsBlank DateSpan TimeUnit DateAdd DateDiff DatePart Hierarchy HierarchyLevel HierarchySource Level Variation VariationSource NativeReferenceName Literal Value Commands commands SemanticQueryDataShapeCommand Query Binding ExecutionMetricsKind DataReduction DataVolume Primary Groupings Projections Subtotal Secondary Top Count Window Limit Sample QueryId MaxRowCount SuppressedJoinPredicates IncludeEmptyGroups ShowAll Percentile K Kind'.split())
NAME_KEYS = {'Name', 'Entity', 'Type', 'Schema', 'Source', 'Property', 'NativeReferenceName'}


def parsed(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, RecursionError):
            return None
    return value


def query_structure(value, key=None, depth=0):
    if depth > 40:
        raise ValueError('Query nesting exceeds export limit')
    if key in ('Literal', 'Value'):
        return {'redacted': True}
    if isinstance(value, dict):
        return {k: query_structure(v, k, depth + 1) for k, v in value.items() if k in QUERY_KEYS}
    if isinstance(value, list):
        if len(value) > 10000:
            raise ValueError('Query array exceeds export limit')
        return [query_structure(v, key, depth + 1) for v in value]
    if isinstance(value, str):
        return value if key in NAME_KEYS and len(value) <= 512 else '<redacted>'
    return value if value is None or isinstance(value, (bool, int, float)) else None


def model_identifier(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return value
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def blueprint(payload):
    identity = str(UUID(payload.get('report_id')))
    definition = payload.get('definition')
    if not isinstance(definition, dict):
        raise ValueError('No saved report definition')
    exploration = parsed(definition.get('exploration'))
    sections = exploration.get('sections') if isinstance(exploration, dict) else None
    if not isinstance(sections, list):
        raise ValueError('Report sections not recognized')
    models = parsed(definition.get('models', []))
    if isinstance(models, dict):
        models = [models]
    descriptors = []
    for model in models if isinstance(models, list) else []:
        if isinstance(model, dict):
            descriptor = {'keys': sorted(model.keys())}
            for key in ('id', 'modelId', 'dataModelId'):
                identifier = model_identifier(model.get(key))
                if identifier is not None:
                    descriptor[key] = identifier
            descriptors.append(descriptor)
    visuals = []
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        for visual in section.get('visualContainers', []):
            if not isinstance(visual, dict):
                continue
            config = parsed(visual.get('config'))
            single = config.get('singleVisual') if isinstance(config, dict) else None
            if not isinstance(single, dict):
                continue
            projections = single.get('projections', {})
            refs = sorted({p['queryRef'] for values in projections.values() if isinstance(values, list)
                           for p in values if isinstance(p, dict) and isinstance(p.get('queryRef'), str)})
            if not any('name_TT' in ref or 'ЛМК' in ref or ref.endswith('.Всего курьеров') for ref in refs):
                continue
            visuals.append({'section_index': section_index, 'visual_type': single.get('visualType'),
                            'query_refs': refs,
                            'prototype_query': query_structure(parsed(single.get('prototypeQuery'))),
                            'query': query_structure(parsed(visual.get('query')))})
    if not visuals:
        raise ValueError('No medical percentage or shop-name visual found')
    base_path = payload.get('base_path')
    if base_path not in ('/powerbi', '/reports/powerbi'):
        base_path = None
    return {'schema_version': 1, 'report_id': identity, 'base_path': base_path, 'models': descriptors,
            'definition_keys': sorted(definition.keys()), 'visuals': visuals,
            'literal_values_redacted': True,
            'notice': 'Structure only; do not execute redacted queries. Use the private original on the VPS.'}


def main():
    source, output = ROOT / 'powerbi-report-definition.json', ROOT / 'powerbi-query-blueprint.json'
    if os.geteuid() != 0:
        raise ValueError('Run on the VPS as root')
    if source.stat().st_mode & 0o077 or source.stat().st_size > 9437184:
        raise ValueError('Unexpected private report definition permissions or size')
    result = blueprint(json.loads(source.read_text()))
    private_write(output, json.dumps(result, ensure_ascii=False, indent=2))
    print('Sanitized query blueprint saved: ' + str(output))
    print('Selected visual definitions: ' + str(len(result['visuals'])))
    print('No credential values, filter literals or courier rows exported.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, TypeError, AttributeError, OSError, RecursionError):
        raise SystemExit('Cannot export the saved report structure; private details hidden.')
