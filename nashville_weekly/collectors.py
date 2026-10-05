"""Adapters return source facts, leaving all filtering to normalize.py."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin, urlsplit
from bs4 import BeautifulSoup
from .network import CollectionError

def plain(value):
    return re.sub(r'\s+', ' ', BeautifulSoup(str(value or ''), 'html.parser').get_text(' ', strip=True)).strip()

def tribe(source, client, start, end):
    out, warnings = [], []
    endpoint = source['endpoint']
    for page in range(1, source.get('max_pages', 40) + 1):
        query = urlencode({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'per_page': 50, 'page': page})
        data = json.loads(client.get(endpoint + '?' + query))
        if not isinstance(data.get('events'), list): raise CollectionError('Event API schema changed')
        for e in data['events']:
            v = e.get('venue') or {}
            if isinstance(v, list): v = v[0] if v else {}
            out.append(dict(title=plain(e.get('title')), start=e.get('start_date'), end=e.get('end_date'),
                timezone=e.get('timezone') or 'America/Chicago', all_day=e.get('all_day', False),
                description=plain(e.get('description')), excerpt=plain(e.get('excerpt')),
                url=e.get('url'), source_event_id=str(e.get('id')), venue=plain(v.get('venue')),
                address=plain(v.get('address')), city=plain(v.get('city')), state=plain(v.get('state') or v.get('province')),
                lat=v.get('geo_lat'), lon=v.get('geo_lng'), cost_text=plain(e.get('cost')),
                source_tags=[plain(x.get('name')) for x in e.get('categories', [])],
                status=e.get('event_status', 'scheduled'), raw=e))
        if page >= int(data.get('total_pages', 1)): break
    else: warnings.append('Page limit reached; collection is incomplete')
    return out, warnings

def walk_events(obj):
    if isinstance(obj, list):
        for v in obj: yield from walk_events(v)
    elif isinstance(obj, dict):
        types = obj.get('@type', [])
        if isinstance(types, str): types = [types]
        if any(t == 'Event' or t.endswith('Event') for t in types): yield obj
        for key, value in obj.items():
            if key not in ('subEvent', 'superEvent'): yield from walk_events(value)

def schema_event(e, url):
    loc = e.get('location') or {}
    if isinstance(loc, list): loc = loc[0] if loc else {}
    if isinstance(loc, str): loc = {'name': loc}
    address = loc.get('address') or {}
    if isinstance(address, str): address = {'streetAddress': address}
    offers = e.get('offers') or []
    if isinstance(offers, dict): offers = [offers]
    prices = [str(o.get('price', o.get('lowPrice', ''))) for o in offers if isinstance(o, dict)]
    cost = ', '.join(p for p in prices if p)
    if cost: cost += ' ' + next((o.get('priceCurrency', '') for o in offers if isinstance(o, dict)), '')
    geo = loc.get('geo') or {}
    return dict(title=plain(e.get('name')), start=e.get('startDate'), end=e.get('endDate'),
        description=plain(e.get('description')), url=e.get('url') or url, venue=plain(loc.get('name')),
        address=plain(address.get('streetAddress')), city=plain(address.get('addressLocality')),
        state=plain(address.get('addressRegion')), lat=geo.get('latitude'), lon=geo.get('longitude'),
        cost_text=cost, age_text=e.get('typicalAgeRange', ''), status=e.get('eventStatus', ''),
        attendance=e.get('eventAttendanceMode', ''), raw=e)

def jsonld(source, client, start, end):
    """Read only configured listings/detail links, never crawl an entire website."""
    listing = client.get(source['url'])
    soup = BeautifulSoup(listing, 'html.parser')
    pages = [(source['url'], listing)]
    pattern = source.get('detail_pattern')
    warnings = []
    if pattern:
        links = list(dict.fromkeys(urljoin(source['url'], a['href']) for a in soup.select('a[href]')
            if re.search(pattern, a['href']) and urlsplit(urljoin(source['url'], a['href'])).netloc == urlsplit(source['url']).netloc))
        limit = source.get('max_details', 30)
        if len(links) > limit: warnings.append('Detail-page limit reached')
        for link in links[:limit]:
            try: pages.append((link, client.get(link)))
            except Exception as e: warnings.append(f'Detail failed: {link}: {e}')
        warnings.append('Listing-page coverage only; load-more results may not be included')
    events = []
    for url, body in pages:
        for script in BeautifulSoup(body, 'html.parser').select('script[type="application/ld+json"]'):
            try:
                for event in walk_events(json.loads(script.get_text())):
                    if event.get('startDate'): events.append(schema_event(event, url))
            except (ValueError, TypeError) as e: warnings.append('Invalid structured data: ' + str(e))
    if not events: warnings.append('No dated Event objects found; source needs review')
    return events, warnings

def ics(source, client, start, end):
    from icalendar import Calendar
    import recurring_ical_events
    from zoneinfo import ZoneInfo
    body = client.get(source.get('endpoint', source['url']))
    calendar = Calendar.from_ical(body)
    events = recurring_ical_events.of(calendar).between(start, end + timedelta(days=1))
    out = []
    for e in events:
        first = e.decoded('DTSTART')
        last = e.decoded('DTEND', first)
        all_day = not isinstance(first, datetime)
        # RFC5545 date-only DTEND is exclusive.
        if all_day and last > first: last -= timedelta(days=1)
        out.append(dict(title=str(e.get('SUMMARY', '')), start=first.isoformat(), end=last.isoformat(),
            all_day=all_day, description=str(e.get('DESCRIPTION', '')), venue=str(e.get('LOCATION', '')),
            url=str(e.get('URL', source['url'])), source_event_id=str(e.get('UID', '')),
            status=str(e.get('STATUS', '')), raw=e.to_ical().decode('utf-8', 'replace')))
    return out, []

def nhl(source, client, start, end):
    events, seen = [], set()
    for offset in range(0, (end-start).days+1, 7):
        url = source['endpoint'].format(date=(start+timedelta(days=offset)).isoformat())
        data = json.loads(client.get(url))
        if 'games' not in data: raise CollectionError('NHL schedule schema changed')
        for e in data['games']:
            if e['id'] in seen or e.get('homeTeam', {}).get('abbrev') != 'NSH': continue
            seen.add(e['id'])
            away = e['awayTeam']
            name = away.get('placeName', {}).get('default', away.get('abbrev', 'Visitors'))
            events.append(dict(title=f'Nashville Predators vs. {name}', start=e.get('startTimeUTC'),
                venue=e.get('venue', {}).get('default', 'Bridgestone Arena'), city='Nashville', state='TN',
                url=source['url'], description='Home hockey game. Check the official schedule for tickets and updates.',
                source_event_id=str(e['id']), age_text='All ages', registration='Tickets required',
                status='cancelled' if e.get('gameScheduleState') in ('CNCL', 'PPD') else 'scheduled', raw=e))
    return events, []

def mlb(source, client, start, end):
    data = json.loads(client.get(source['endpoint'] + '&' + urlencode({'startDate': start.isoformat(), 'endDate': end.isoformat(), 'hydrate': 'venue'})))
    if 'dates' not in data: raise CollectionError('Baseball schedule schema changed')
    out = []
    for day in data['dates']:
        for e in day.get('games', []):
            if e['teams']['home']['team']['id'] != source['team_id']: continue
            away = e['teams']['away']['team']['name']
            out.append(dict(title=f'Nashville Sounds vs. {away}', start=e.get('gameDate'),
                venue=e.get('venue', {}).get('name', 'First Horizon Park'), city='Nashville', state='TN',
                url=source['url'], description='Home baseball game. Check the official schedule for tickets and updates.',
                source_event_id=str(e['gamePk']), age_text='All ages', registration='Tickets required',
                status=e.get('status', {}).get('detailedState', ''), raw=e))
    return out, []

ADAPTERS = {'tribe': tribe, 'jsonld': jsonld, 'ics': ics, 'nhl': nhl, 'mlb': mlb}

def bedework(source, client, start, end):
    out, warnings = [], []
    def window(a,b):
        query=urlencode({'f':'y','sort':'dtstart.utc:asc','skinName':'list-json','count':200,
                         'start':a.strftime('%Y%m%d'),'end':b.strftime('%Y%m%d')})
        data=json.loads(client.get(source['endpoint']+'?'+query))['bwEventList']
        events=data.get('events',[])
        if int(data.get('resultSize',len(events)))>=200 or len(events)>=200:
            if (b-a).days>1:
                mid=a+timedelta(days=max(1,(b-a).days//2))
                window(a,mid); window(mid,b); return
            warnings.append('Library export cap reached for '+a.isoformat())
        for e in events:
            loc=e.get('location',{})
            tags=e.get('categories',[])
            if loc.get('address','').lower()=='online' or 'location/Online' in tags: continue
            out.append(dict(title=e.get('summary'),start=e.get('start',{}).get('utcdate'),
                end=e.get('end',{}).get('utcdate'),all_day=e.get('start',{}).get('allday')=='true',
                description=plain(e.get('description')),venue=loc.get('address',''),city='Nashville',state='TN',
                source_tags=tags,cost_text=plain(e.get('cost')),url=e.get('eventlink') or e.get('link'),
                status=e.get('status'),source_event_id=e.get('guid'),raw=e))
    for offset in range(0,(end-start).days+1,7):
        a=start+timedelta(days=offset); window(a,min(a+timedelta(days=7),end+timedelta(days=1)))
    return out,warnings

def squarespace(source, client, start, end):
    data=json.loads(client.get(source['endpoint']))
    if not any(k in data for k in ('items','upcoming','past')): raise CollectionError('Squarespace schema changed')
    out=[]
    for e in data.get('items',data.get('upcoming',[])+data.get('past',[])):
        if not e.get('startDate'): continue
        location=e.get('location') or {}
        out.append(dict(title=e.get('title'),start=datetime.fromtimestamp(e['startDate']/1000,timezone.utc).isoformat(),
            end=datetime.fromtimestamp(e.get('endDate',e['startDate'])/1000,timezone.utc).isoformat(),
            description=plain(e.get('body')),url=urljoin(source['url'],e.get('fullUrl','')),
            venue=location.get('addressTitle',''),address=location.get('addressLine1',''),
            city=location.get('addressLine2','').split(',')[0],raw=e))
    return out,['Squarespace first-page coverage; check source for additional events']

ADAPTERS.update(bedework=bedework,squarespace=squarespace)

def cheekwood(source, client, start, end):
    from dateutil.parser import parse
    soup=BeautifulSoup(client.get(source['url']),'html.parser')
    out=[]
    for card in soup.select('article.event-feed__item'):
        title=card.select_one('.event-feed__title')
        dates=card.select('.event-feed__dates span')
        link=card.select_one('a[href*="/calendar-events/"]')
        if not title or not dates or not link: continue
        first=parse(dates[0].get_text()).date().isoformat()
        last=parse(dates[-1].get_text()).date().isoformat()
        content=card.select_one('.event-feed__content > div')
        out.append(dict(title=title.get_text(' ',strip=True),start=first,end=last,all_day=True,
            description=content.get_text(' ',strip=True) if content else '',url=link['href'],raw=str(card)))
    return out,['First listing page only; load-more events and exact session times require checking the source']

ADAPTERS['cheekwood']=cheekwood

def collect(source, client, start, end):
    events, warnings = ADAPTERS[source['adapter']](source, client, start, end)
    for event in events:
        event['source_id'] = source['id']
        event['source_name'] = source['name']
        event['official'] = source.get('official', True)
    return events, warnings
