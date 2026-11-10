"""Explicitly opted-in static named details for DS7745, without source archives."""
import json
from datetime import date
from pathlib import Path
FIELDS=set('kind schema_version date shop_id generated_at metrics aggregate groups reconciled note title count couriers name courier_id slots slot_id slot_type scope planned_start planned_end actual_start actual_end late_seconds status removed_at removed_by worked_through shift_start_source_date shift_end_source_date fact_source_slot_id capacity occupied free numerator denominator value reason basis training_date match_status'.split())
METRICS={'shift_marked','slot_fill','planned_attendance','planned_late','unplanned_work','planned_completion','training'}
def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k in FIELDS}
    if isinstance(value,list):return [clean(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)):return value
    raise ValueError('Invalid detail value')
def export(directory):
    records={}
    for path in sorted(Path(directory).glob('*-7745.json')):
        data=json.loads(path.read_text());day=data['date']
        if date.fromisoformat(day).isoformat()!=day or path.name!=day+'-7745.json':raise ValueError('Invalid detail date')
        if data.get('kind')!='courier_metric_details' or data.get('shop_id')!=7745:raise ValueError('Invalid detail identity')
        metrics={k:clean(v) for k,v in data['metrics'].items() if k in METRICS}
        records[day]={'generated_at':data['generated_at'],'metrics':metrics}
    if not records:raise ValueError('No DS7745 details to publish')
    return {'schema_version':1,'shop_id':7745,'records':records}
