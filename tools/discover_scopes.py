"""Mirror the site's AF/PF/LF catalogue mapping; no guesses from ID proximity."""
import re

from dashboard_shops import TARGETS


def items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get('items'), list):
        return payload['items']
    raise ValueError('Unknown catalogue format')


def first(row, *keys):
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def name_shop_numbers(name):
    # Exact AF rule in the inspected web application, including token lengths.
    output = []
    for match in re.finditer(r'[0-9]+', str(name or '').strip()):
        token = match.group()
        if len(token) > 7 or len(token) < (2 if match.start() == 0 else 4):
            continue
        value = int(token)
        if value > 0 and value not in output:
            output.append(value)
    return output


def discover(shops_payload, clusters_payload, targets=TARGETS):
    shops, clusters = items(shops_payload), items(clusters_payload)
    catalogue = {}
    for row in shops:
        identity = first(row, 'shopno', 'shop_id', 'id', 'shopno_cluster_id')
        if identity is None:
            continue
        identity = int(identity)
        if identity in catalogue and catalogue[identity] != row:
            raise ValueError('Conflicting shop catalogue entries')
        catalogue[identity] = row
    by_shop = {}
    for cluster in clusters:
        identity = int(first(cluster, 'id', 'cluster_id') or 0)
        if identity <= 0:
            continue
        for shop in name_shop_numbers(cluster.get('name')):
            by_shop.setdefault(shop, set()).add(identity)
    result = []
    for shop in targets:
        row = catalogue.get(shop)
        if row is None:
            result.append({'shop_id': shop, 'scope_verified': False,
                           'reason': 'shop_missing_from_catalogue', 'cluster_ids': []})
            continue
        cluster_ids = set(by_shop.get(shop, set()))
        parent = int(row.get('cluster_id') or 0)
        if parent > 0:
            cluster_ids.add(parent)
        result.append({'shop_id': shop, 'scope_verified': True,
                       'scope_verified_from': 'site_AF_PF_LF_catalogue_mapping',
                       'cluster_ids': sorted(cluster_ids)})
    return {'schema_version': 1, 'shops': result}
