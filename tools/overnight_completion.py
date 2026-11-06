"""Stitch verified daily work fragments without merging independent courier shifts."""
from collections import Counter,defaultdict
from copy import deepcopy
from datetime import datetime,timedelta,time
from audit_sources import sanitize_slot
from calculate_metrics import MOSCOW,period,timestamp,cutoff_end
from enrich_slots import fetch,source_status

ARRIVED={'on_time','early','late'}
MAX_DAYS=3


def midnight(value):
    return value is not None and value.astimezone(MOSCOW).time().replace(tzinfo=None)==time.min


def conflicting_origin(people,identity,start,until,aliases=None):
    """An alternate actual start overlapping the source fragment prevents reset joins."""
    for person in people:
        if person['courier_id']!=identity or source_status(person.get('shift_status')) not in ARRIVED:continue
        other=timestamp(person.get('shift_start'))
        if other is None:continue
        starts=(aliases or {}).get((identity,other,cutoff_end(person)),{other})
        end=timestamp(person.get('shift_end')) or cutoff_end(person)
        if any(candidate!=start and (start<candidate<=until or
            (candidate<start and end is not None and end>start)) for candidate in starts):return True
    return False


def matching(original,candidates,now,allow_reset=False):
    start=timestamp(original.get('shift_start'))
    if start is None:return []
    people=[c for c in candidates if c['courier_id']==original['courier_id'] and source_status(c.get('shift_status'))!='no_show']
    exact=[c for c in people if timestamp(c.get('shift_start'))==start]
    if any((end:=timestamp(c.get('shift_end'))) is not None and end<=now and cutoff_end(c) is None for c in exact):return exact
    boundary=cutoff_end(original)
    if not allow_reset or boundary is None or midnight(start):return exact
    following=datetime.combine(boundary.astimezone(MOSCOW).date()+timedelta(days=1),time.min,tzinfo=MOSCOW)
    reset=[c for c in people if timestamp(c.get('shift_start'))==following and source_status(c.get('shift_status')) in ARRIVED]
    ends={timestamp(c.get('shift_end')) for c in reset};ends.discard(None)
    valid=[end for end in ends if following<=end<=now]
    if not valid:return exact+reset
    # A different overlapping actual start is evidence against a unique continuation.
    if any(following < other <= max(valid) for c in people
           if (other:=timestamp(c.get('shift_start'))) is not None):return exact
    return exact+reset


def match_end(original,candidates,now,allow_reset=False):
    start=timestamp(original.get('shift_start'))
    if start is None:return None,'original_shift_start_missing_or_unzoned'
    people=matching(original,candidates,now,allow_reset)
    ends={timestamp(c.get('shift_end')) for c in people};ends.discard(None)
    ends={end for end in ends if start<=end<=now}
    lower=cutoff_end(original)
    if lower is not None and any(end<lower for end in ends):return None,'conflicting_next_day_ends'
    boundaries={end for end in ends if cutoff_end({'shift_end':end.isoformat()})}
    final=ends-boundaries
    if len(final)>1 or (final and boundaries and max(boundaries)>next(iter(final))):
        return None,'conflicting_next_day_ends'
    if not final:return None,'same_shift_end_not_found_next_day'
    method=('matched_same_courier_and_actual_shift_start' if any(timestamp(c.get('shift_start'))==start and timestamp(c.get('shift_end')) in final for c in people)
            else 'matched_unique_adjacent_midnight_fragments')
    return next(iter(final)).isoformat(),method


def resolve(slots,token,proxy,now=None,source_cache=None,scopes=None):
    now=now or datetime.now(MOSCOW);today=now.astimezone(MOSCOW).date()
    resolved=deepcopy(slots);cache=source_cache if source_cache is not None else {}
    reasons=Counter();recovered=0;starts_recovered=0
    known=set(scopes or ())|{(s['scope_kind'],s['scope_id']) for s in slots}
    def candidates(day,preferred):
        people=[];complete=True
        for kind,identity in [preferred]+sorted(known-{preferred}):
            key=day,kind,identity
            if key not in cache:
                try:
                    payload=fetch((*key,'all'),token,proxy)
                    rows=payload if isinstance(payload,list) else payload.get('slots',payload.get('items'))
                    if not isinstance(rows,list):raise ValueError('Incomplete daily work source')
                    parsed=[sanitize_slot(row,*key) for row in rows]
                    cache[key]=[]
                    for s in parsed:
                        try:planned_start,planned_end=period(s)
                        except (ValueError,KeyError,TypeError,AttributeError):planned_start=planned_end=None
                        cache[key].extend(dict(p,_source_date=day,_source_slot_id=s['slot_id'],
                            _source_slot_type=s['slot_type'],_source_scope_kind=kind,_source_scope_id=identity,
                            _source_planned_start=planned_start.isoformat() if planned_start else None,
                            _source_planned_end=planned_end.isoformat() if planned_end else None) for p in s['couriers'])
                except (RuntimeError,ValueError,KeyError,TypeError,OSError):cache[key]=None
            if cache[key] is None:complete=False
            else:people.extend(cache[key])
        return people,complete
    # A source start of00:00 is often the second fragment, not a new shift.
    for slot in resolved:
        scope=slot['scope_kind'],slot['scope_id']
        for person in slot['couriers']:
            raw=timestamp(person.get('shift_start'))
            if not midnight(raw) or source_status(person.get('shift_status')) not in ARRIVED:continue
            cursor=raw;chosen=None
            for _ in range(MAX_DAYS):
                day=(cursor.astimezone(MOSCOW).date()-timedelta(days=1)).isoformat()
                people,complete=candidates(day,scope)
                if not complete:break
                previous={timestamp(p.get('shift_start')) for p in people
                    if p['courier_id']==person['courier_id'] and source_status(p.get('shift_status')) in ARRIVED
                    and (end:=cutoff_end(p)) is not None and timedelta(0)<cursor-end<=timedelta(seconds=1)
                    and (start:=timestamp(p.get('shift_start'))) is not None and start<end}
                if len(previous)!=1:break
                preceding=next(iter(previous))
                if conflicting_origin(people,person['courier_id'],preceding,cursor):break
                cursor=preceding
                if not midnight(cursor):chosen=(cursor,day);break
            if chosen:
                person['shift_start_raw']=person.get('shift_start')
                person['shift_start']=chosen[0].isoformat();person['shift_start_source_date']=chosen[1]
                person['shift_stitch_method']='matched_unique_adjacent_midnight_fragments'
                starts_recovered+=1
    original_starts=defaultdict(set)
    for slot in resolved:
        for person in slot['couriers']:
            if (boundary:=cutoff_end(person)) is not None:
                original_starts[person['courier_id'],boundary].add(timestamp(person.get('shift_start')))
    aliases=defaultdict(set)
    for slot in resolved:
        for person in slot['couriers']:
            if person.get('shift_start_raw') and (cut:=cutoff_end(person)) is not None:
                aliases[person['courier_id'],timestamp(person['shift_start_raw']),cut].add(timestamp(person.get('shift_start')))
    for slot in resolved:
        scope=slot['scope_kind'],slot['scope_id']
        try:_,planned_end=period(slot);night=planned_end.date().isoformat()!=slot['date']
        except (ValueError,KeyError,TypeError,AttributeError):night=False
        for person in slot['couriers']:
            if source_status(person.get('shift_status')) not in ARRIVED:continue
            boundary=cutoff_end(person)
            if person.get('shift_end') and boundary is None:continue
            if boundary is None and not night:continue
            if boundary is not None:
                person.setdefault('shift_end_raw',person.get('shift_end') or boundary.isoformat())
                person['shift_end_lower_bound']=boundary.isoformat();person['shift_end']=None
            cursor=boundary or datetime.combine(datetime.fromisoformat(slot['date']).date(),time.max,tzinfo=MOSCOW)
            working=dict(person);working['shift_end']=boundary.isoformat() if boundary else None
            chain=[]
            def remember(records):
                for p in records:
                    fact={'date':p['_source_date'],'slot_id':p['_source_slot_id'],'slot_type':p['_source_slot_type'],
                        'scope_kind':p['_source_scope_kind'],'scope_id':p['_source_scope_id'],
                        'shift_start':p.get('shift_start'),'shift_end':p.get('shift_end'),
                        'planned_start':p.get('_source_planned_start'),'planned_end':p.get('_source_planned_end')}
                    if fact not in chain:chain.append(fact)
                    if (cut:=cutoff_end(p)) is not None:
                        aliases[person['courier_id'],timestamp(p.get('shift_start')),cut].add(timestamp(person.get('shift_start')))
                if chain:person['shift_continuation_facts']=deepcopy(chain)
            for _ in range(MAX_DAYS):
                day=(cursor.astimezone(MOSCOW).date()+timedelta(days=1))
                if day>today:break
                people,complete=candidates(day.isoformat(),scope)
                allow_reset=False
                if (cut:=cutoff_end(working)) is not None and complete:
                    origins,origin_complete=candidates(cut.astimezone(MOSCOW).date().isoformat(),scope)
                    possible=set(original_starts.get((person['courier_id'],cut),()))
                    for p in origins:
                        if p['courier_id']==person['courier_id'] and cutoff_end(p)==cut and source_status(p.get('shift_status')) in ARRIVED:
                            raw_start=timestamp(p.get('shift_start'))
                            possible.update(aliases.get((person['courier_id'],raw_start,cut),{raw_start}))
                    possible.discard(None)
                    allow_reset=(origin_complete and len(possible)==1 and not conflicting_origin(
                        origins,person['courier_id'],next(iter(possible)),cut,aliases))
                actual_end,reason=match_end(working,people,now,allow_reset)
                reasons[reason]+=1
                if not complete:reasons['adjacent_day_source_unavailable']+=1
                if actual_end:
                    person['shift_end']=actual_end;person['shift_end_source_date']=day.isoformat()
                    person['shift_stitch_method']=reason
                    remember([p for p in matching(working,people,now,allow_reset) if timestamp(p.get('shift_end'))==timestamp(actual_end)])
                    recovered+=1;break
                if reason=='conflicting_next_day_ends':break
                matched=matching(working,people,now,allow_reset)
                bounds={cutoff_end(p) for p in matched};bounds.discard(None)
                if bounds:
                    bound=max(bounds)
                    remember([p for p in matched if cutoff_end(p)==bound])
                    working['shift_end']=bound.isoformat()
                    cursor=bound if bound>cursor else datetime.combine(day,time.max,tzinfo=MOSCOW)
                else:
                    # Exact original-start evidence may appear on a later export.
                    cursor=datetime.combine(day,time.max,tzinfo=MOSCOW)
            if boundary is not None and not person.get('shift_end'):
                reasons['calendar_boundary_end_unconfirmed']+=1
    return resolved,{'recovered_records':recovered,'recovered_start_records':starts_recovered,'reasons':dict(reasons)}
