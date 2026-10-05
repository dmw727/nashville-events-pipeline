"""Deterministic event-only rules. Uncertainty is retained, never invented away."""
import hashlib
import math
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .collectors import plain

TZ = ZoneInfo('America/Chicago')
CATEGORIES = {
 'STEM/science': r'\b(science|stem|steam|astronomy|planetarium|chemistry|physics|experiment|nightwatch|solar system)\b',
 'nature': r'\b(nature|hike|hiking|garden|birding|creek|river|wildflower|forest|tree|ecology|naturalist)\b',
 'animals': r'\b(animal|zoo|wildlife|critter|reptile|bird|raptor|owl|goat|snake|creature|insect)\w*',
 'sports': r'\b(sport|baseball|hockey|soccer|basketball|tennis|fishing|archery|skating|football)\b',
 'physical adventure': r'\b(climb|climbing|zipline|zip line|kayak|paddle|ropes|trampoline|adventure park)\w*',
 'art': r'\b(art|paint|painting|draw|drawing|pottery|ceramic|sculpture|printmaking|craft)\w*',
 'music': r'\b(music|concert|symphony|song|songwriting|instrument|orchestra|jazz|guitar|ukulele)\w*',
 'theater': r'\b(theater|theatre|puppet|musical|acting|drama|ballet|dance)\w*',
 'maker/building': r'\b(maker|build|building|lego|woodwork|tinker|sewing|robot|craft|printmaking)\w*',
 'history': r'\b(history|historic|museum|battlefield|heritage|archaeology|railway)\w*',
 'cooking': r'\b(cook|cooking|baking|culinary|chef|recipe|bread|kitchen)\w*',
 'technology': r'\b(technology|coding|code club|robot|3d print|programming|computer|electronics)\w*',
 'volunteering/community': r'\b(volunteer|cleanup|clean-up|service day|community service|food packing)\w*',
 'festivals/cultures': r'\b(festival|culture|cultural|heritage|mariachi|diwali|pow wow|international)\w*',
 'gaming': r'\b(game|gaming|chess|pokemon|pokémon|dungeons|boardgame|board game|tabletop|minecraft)\w*',
 'unusual experiences': r'\b(train ride|excursion|cave|caving|magic show|circus|aerial|immersive|stargazing)\w*',
 'seasonal events': r'\b(halloween|pumpkin|harvest|christmas|holiday|easter|fall fest|winter|summer splash)\w*',
 'general fun': r'\b(fun|movie|fair|carnival|play|picnic)\b',
}

def canonical(url):
    if not url: return ''
    u = urlsplit(url)
    if u.scheme not in ('http', 'https'): return ''
    q = [(k,v) for k,v in parse_qsl(u.query) if not k.startswith('utm_') and k not in ('fbclid','gclid')]
    return urlunsplit((u.scheme, u.netloc.lower(), u.path.rstrip('/'), urlencode(q), ''))

def key(text):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', text.lower()).encode('ascii','ignore').decode())

def parse_date(value, zone='America/Chicago', all_day=False, end=False):
    if not value: return None
    d = isoparse(str(value))
    if all_day or len(str(value)) == 10:
        d = datetime.combine(d.date(), time(23,59,59) if end else time.min)
    if d.tzinfo is None:
        offset = re.fullmatch(r'UTC([+-])(\d{1,2})(?::(\d{2}))?', zone)
        if offset:
            minutes = (int(offset[2])*60+int(offset[3] or 0))*(1 if offset[1]=='+' else -1)
            tz = timezone(timedelta(minutes=minutes))
        else: tz = ZoneInfo(zone)
        d = d.replace(tzinfo=tz)
    return d.astimezone(TZ)

def age_info(title, description, explicit, tags):
    text = ' '.join([title, description, explicit, ' '.join(tags)]).lower()
    if re.search(r'\b(?:18|21)\+(?!\d)',text):
        return 'excluded', 'Adults only / adult event', None, None
    if re.search(r'\b(adults?[- ]only|21\+|18\+|ages?\s*(?:18|21)\s*(?:and (?:up|over)|\+)|must be (?:18|21))\b', text) or re.search(r'\b(booze|beer festival|bar crawl|wine tasting)\b',title.lower()):
        return 'excluded', 'Adults only / adult event', None, None
    bounds = re.findall(r'\b(?:ages?|aged|children ages?)\s*:?\s*(\d{1,2})\s*(?:-|–|—|to|through)\s*(\d{1,2})\b', text)
    if explicit and re.fullmatch(r'\d{1,2}-\d{1,2}',str(explicit)):
        bounds.insert(0,tuple(str(explicit).split('-')))
    if bounds:
        allowed = [(int(a),int(b)) for a,b in bounds if int(a)<=10<=int(b)]
        lo,hi = allowed[0] if allowed else tuple(map(int,bounds[0]))
        return ('stated range' if allowed else 'excluded'), f'Ages {lo}–{hi}',lo,hi
    minimum = re.search(r'\bages?\s*(\d{1,2})\s*(?:\+|and (?:up|older)|or older)',text)
    if minimum:
        lo=int(minimum[1]); return ('stated range' if lo<=10 else 'excluded'), f'Ages {lo}+',lo,None
    if re.search(r'\b(toddler|preschool|baby|babies|teen[- ]only|adult workshop)\b', title.lower()):
        return 'excluded','Program aimed at a different age group',None,None
    if re.search(r'\b(all ages|family[- ]friendly|families|family program|elementary|school[- ]age|ages? 10)\b',text):
        return 'family / school age','Family / school-age wording; check restrictions',None,None
    if re.search(r'\b(adults|teens)\b', ' '.join(tags).lower()) and not re.search(r'\b(children|family|all ages)\b',' '.join(tags).lower()):
        return 'excluded','Source audience is adults or teens',None,None
    return 'check age','Age suitability not stated',None,None

def distance_info(e, source, config):
    lat,lon = e.get('lat'),e.get('lon')
    basis='source coordinates'
    try:
        lat,lon=float(lat),float(lon)
        if not (-90<=lat<=90 and -180<=lon<=180): raise ValueError()
    except (ValueError,TypeError):
        lat=lon=None
        city=(e.get('city') or '').lower().strip()
        if not city and source.get('fixed_location'):
            city=source.get('city','').lower()
        if not city:
            location=' '.join([e.get('venue',''),e.get('address','')]).lower()
            city=next((c for c in sorted(config['city_centers'],key=len,reverse=True) if re.search(r'\b'+re.escape(c)+r'\b',location)), '')
        center=config['city_centers'].get(city)
        if center: lat,lon=center; basis=f'{city.title()} city center; not venue coordinates'
    if lat is None: return None,None,None,'Location not resolved'
    olat,olon=config['origin']['lat'],config['origin']['lon']
    p1,p2=map(math.radians,[olat,lat]); dp=math.radians(lat-olat); dl=math.radians(lon-olon)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    miles=3958.8*2*math.atan2(math.sqrt(a),math.sqrt(max(0,1-a)))
    road=round(miles*config['road_factor'],1)
    minutes=round(config['local_overhead_minutes']+road/config['average_mph']*60)
    return round(miles,1),road,minutes,basis

def normalize(e, source, config, start, end):
    title=plain(e.get('title')); description=plain(e.get('description'))
    if not title: return None,'missing title'
    if re.search(r'\b(cancelled|canceled|postponed|EventCancelled|EventPostponed)\b',str(e.get('status','')),re.I): return None,'cancelled / postponed'
    if re.search(r'^(closed\b|museum closed\b|private event\b)',title,re.I): return None,'closure / private listing'
    if 'OnlineEventAttendanceMode' in str(e.get('attendance','')) or re.search(r'\b(online only|virtual only|zoom only)\b',title+' '+description,re.I): return None,'online only'
    if re.search(r'\b(school groups only|field trips only|school-only)\b',description,re.I): return None,'school groups only'
    all_day=e.get('all_day',False) or len(str(e.get('start','')))==10
    try:
        first=parse_date(e.get('start'),e.get('timezone') or 'America/Chicago',all_day)
        last=parse_date(e.get('end'),e.get('timezone') or 'America/Chicago',all_day,True) or first
    except (ValueError,TypeError,KeyError): return None,'invalid date / timezone'
    if first is None: return None,'missing date'
    if last < first: return None,'end before start'
    if last.date()<start or first.date()>end: return None,'outside report dates'
    tags=e.get('source_tags',[])
    age_status,age_text,age_min,age_max=age_info(title,description,str(e.get('age_text','')),tags)
    if age_status=='excluded': return None,'age mismatch: '+age_text
    straight,road,minutes,basis=distance_info(e,source,config)
    if minutes is not None and minutes>config['max_drive_minutes']: return None,'outside approximate drive limit'
    state=e.get('state','').lower()
    if state and state not in ('tn','tennessee') and minutes is None: return None,'outside Tennessee with unknown distance'
    combined=' '.join([title,description,' '.join(tags)]).lower()
    cats=[c for c,p in CATEGORIES.items() if re.search(p,combined)]
    for c in source.get('default_categories',[]):
        if c not in cats: cats.append(c)
    if not cats: cats=['general fun']
    if len(cats)>1 and 'general fun' in cats: cats.remove('general fun')
    cost=plain(e.get('cost_text'))
    free=bool(re.fullmatch(r'(?:free(?: admission)?|\$?0(?:\.00)?(?:\s*USD)?)',cost,re.I))
    if not cost: cost='Not stated — check source'
    setting=e.get('setting') or 'unknown'
    indoor=bool(re.search(r'\b(indoors?|inside the|auditorium|planetarium)\b',combined))
    outdoor=bool(re.search(r'\b(outdoors?|hike|hiking|trail|creek|river exploration)\b',combined))
    if indoor and outdoor: setting='mixed'
    elif indoor: setting='indoor'
    elif outdoor: setting='outdoor'
    elif source.get('setting'): setting=source['setting']
    reg=e.get('registration') or 'Not stated — check source'
    if re.search(r'\b(no registration|registration not required|drop[- ]in)\b',combined): reg='No advance registration stated'
    elif re.search(r'\b(registration required|register by|register online|registration opens|reserve tickets|buy tickets)\b',combined): reg='Registration / tickets required'
    url=canonical(e.get('url')) or canonical(source['url'])
    flags=[]
    if age_status=='check age': flags.append('Confirm age suitability')
    if minutes is None: flags.append('Confirm distance')
    else: flags.append('Drive estimate is heuristic; check a map')
    if e.get('timezone') not in (None,'','America/Chicago','US/Central'): flags.append('Source timezone differs from Nashville; verify time')
    if last.date()>first.date(): flags.append('Date range; check individual opening days and sessions')
    if re.search(r'\b(sold out|waitlist)\b',combined): flags.append('May be sold out / waitlisted')
    if 'volunteering/community' in cats: flags.append('Check minimum volunteer age and adult accompaniment')
    identity='|'.join([key(title),first.isoformat(),key(e.get('venue') or source.get('venue',''))])
    return dict(id=hashlib.sha256(identity.encode()).hexdigest()[:16],title=title,start=first.isoformat(),end=last.isoformat(),
        all_day=all_day,venue=e.get('venue') or source.get('venue',''),address=e.get('address') or source.get('address',''),
        city=e.get('city') or (source.get('city','') if source.get('fixed_location') else ''),
        cost=cost,free=free,age_status=age_status,age_text=age_text,age_min=age_min,age_max=age_max,
        categories=cats,description=(plain(e.get('excerpt')) or description)[:320],
        registration=reg,setting=setting,setting_basis='source text / configured venue inference',
        straight_miles=straight,road_miles_estimate=road,drive_minutes_estimate=minutes,distance_basis=basis,
        source_url=url,source_id=source['id'],source_name=source['name'],official=source.get('official',True),
        sources=[{'name':source['name'],'url':url,'official':source.get('official',True)}],flags=flags),None

def deduplicate(events):
    """Conservative identity: same URL+start or title+start+known venue.

    Different showtimes and locations survive. Official facts win; all provenance survives.
    """
    results=[]
    by_url,by_identity={},{}
    for e in sorted(events,key=lambda x:(not x['official'],x['start'],x['source_id'])):
        u=(e['source_url'],e['start'])
        venue=key(e['venue'] or e['address'])
        identity=(key(e['title']),e['start'],venue)
        previous=by_url.get(u) or (by_identity.get(identity) if venue else None)
        if previous is not None:
            for src in e['sources']:
                if src not in previous['sources']: previous['sources'].append(src)
            continue
        results.append(e); by_url[u]=e
        if venue: by_identity[identity]=e
    return sorted(results,key=lambda e:(e['start'],e['title']))
