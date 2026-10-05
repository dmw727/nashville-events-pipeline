import argparse
import csv
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from .collectors import collect
from .network import Client
from .normalize import CATEGORIES, TZ, normalize, deduplicate

ROOT=Path(__file__).resolve().parent.parent

def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)

def csv_write(path,events):
    fields=['id','title','start','end','all_day','venue','address','city','cost','free','age_status','age_text','categories','description','registration','setting','straight_miles','road_miles_estimate','drive_minutes_estimate','distance_basis','source_url','source_name','official','flags','sources']
    temp=path.with_suffix('.tmp')
    with temp.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fields,extrasaction='ignore');writer.writeheader()
        for e in events:
            row=dict(e)
            for k,v in row.items():
                if isinstance(v,(list,dict)): row[k]=json.dumps(v,ensure_ascii=False)
                # Prevent spreadsheet formula interpretation of untrusted event text.
                if isinstance(row[k],str) and row[k].lstrip().startswith(('=','+','-','@')): row[k]="'"+row[k]
            writer.writerow(row)
    temp.replace(path)

def main(argv=None):
    p=argparse.ArgumentParser(description='Collect Nashville-area public activities and build a local report.')
    p.add_argument('--as-of',type=date.fromisoformat,default=datetime.now(TZ).date())
    p.add_argument('--days',type=int)
    p.add_argument('--offline',action='store_true',help='Replay cache; explicitly labeled as not freshly verified')
    p.add_argument('--sources',help='Comma-separated source IDs; default all enabled sources')
    p.add_argument('--output',type=Path,default=ROOT,help='Output and cache directory')
    args=p.parse_args(argv)
    config=json.loads((ROOT/'config/settings.json').read_text(encoding='utf-8'))
    sources=json.loads((ROOT/'config/sources.json').read_text(encoding='utf-8'))
    days=args.days if args.days is not None else config['lookahead_days']
    if not 1<=days<=180: p.error('--days must be between 1 and 180')
    selected=set(args.sources.split(',')) if args.sources else None
    if selected and selected-{s['id'] for s in sources if s['enabled']}: p.error('Unknown or manual-only source ID')
    enabled=[s for s in sources if s['enabled'] and (selected is None or s['id'] in selected)]
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    lock=output/'.run.lock'
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        print('Another run is active, or a previous run left .run.lock. See README.',file=sys.stderr);return 3
    os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        start=args.as_of;end=start+timedelta(days=days-1)
        now=datetime.now(timezone.utc).isoformat()
        run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run=output/'data/runs'/run_id;run.mkdir(parents=True)
        client=Client(output/'data/cache',offline=args.offline)
        health=[];raw=[];accepted=[];rejected=[]
        def one(source):
            try:
                events,warnings=collect(source,client,start,end)
                return source,events,warnings,None
            except Exception as e: return source,[],[],f'{type(e).__name__}: {e}'
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(one,s) for s in enabled]
            for future in as_completed(futures):
                source,events,warnings,error=future.result()
                before=len(accepted)
                for e in events:
                    raw.append(e)
                    try: event,reason=normalize(e,source,config,start,end)
                    except Exception as ex: event,reason=None,'normalization error: '+str(ex)
                    if event: accepted.append(event)
                    else: rejected.append({'source_id':source['id'],'title':e.get('title'),'url':e.get('url'),'reason':reason})
                if not events and not error: warnings.append('No events returned; inspect source before assuming calendar is empty')
                status='error' if error else 'partial' if warnings else 'ok'
                health.append({'source_id':source['id'],'name':source['name'],'status':status,'fetched':len(events),'included':len(accepted)-before,'warnings':([error] if error else warnings)})
                print(f"{source['id']}: {status}; {len(events)} fetched; {len(accepted)-before} retained",flush=True)
        manual=json.loads((ROOT/'config/manual_events.json').read_text(encoding='utf-8'))
        for e in manual:
            source={'id':'manual','name':e.get('source_name','Manual source check'),'url':e.get('url',''),'official':e.get('official',False)}
            event,reason=normalize(e,source,config,start,end)
            raw.append({**e,'source_id':'manual'})
            if event: event['flags'].append('Manually entered; verify current source');accepted.append(event)
            else: rejected.append({'source_id':'manual','title':e.get('title'),'reason':reason})
        events=deduplicate(accepted)
        health.sort(key=lambda h:h['source_id'])
        summary={'generated_at':now,'as_of':start.isoformat(),'through':end.isoformat(),'offline':args.offline,
          'run_id':run_id,'counts':{'raw':len(raw),'included_before_dedup':len(accepted),'deduplicated':len(events),'rejected':len(rejected)},
          'rejection_reasons':dict(Counter(r['reason'] for r in rejected)),'health':health}
        for name,obj in [('raw.json',raw),('events.json',events),('rejected.json',rejected),('health.json',health),('manifest.json',summary),('requests.json',client.audit)]: write_json(run/name,obj)
        csv_write(run/'events.csv',events)
        if health and all(h['status']=='error' for h in health):
            write_json(output/'data/last_failure.json',summary)
            print('All sources failed. Existing report preserved; see data/last_failure.json.',file=sys.stderr);return 1
        for name,obj in [('raw.json',raw),('events.json',events),('rejected.json',rejected),('health.json',health),('manifest.json',summary)]: write_json(output/'data'/name,obj)
        csv_write(output/'data/events.csv',events)
        payload={**summary,'events':events,'sources':sources,'categories':list(CATEGORIES)}
        embedded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
        html=(ROOT/'nashville_weekly/report.html').read_text(encoding='utf-8').replace('__PAYLOAD__',embedded)
        tmp=output/'report.tmp';tmp.write_text(html,encoding='utf-8');tmp.replace(output/'report.html')
        print(f"Report: {output/'report.html'} ({len(events)} listings)",flush=True)
        return 2 if any(h['status']!='ok' for h in health) else 0
    finally: lock.unlink(missing_ok=True)

if __name__=='__main__': raise SystemExit(main())
