"""Single-user loopback UI. No external assets, API key form or arbitrary file API."""
import json,secrets,uuid
import threading,html
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
from .cli import ROOT,read,write

def serve(port=8766):
    if not 1024<=port<=65535:raise ValueError('INVALID_PORT')
    token=secrets.token_urlsafe(32);artifacts={};snapshots={};discussions={};jobs={};lock=threading.Lock();pool=ThreadPoolExecutor(max_workers=1)
    company_page=(Path(__file__).with_name('company_ui.html')).read_text(encoding='utf-8')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data,content_type='application/json; charset=utf-8'):
            encoded=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8') if content_type.startswith('application/json') else data
            self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(encoded)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(encoded)
        def allowed_host(self):return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
        def do_GET(self):
            if not self.allowed_host():return self.reply(403,{'error':'LOCAL_HOST_REQUIRED'})
            path=urlparse(self.path).path
            if path=='/':return self.reply(200,company_page.replace('__TOKEN__',token).encode('utf-8'),'text/html; charset=utf-8')
            if path=='/advisor-ui.js':return self.reply(200,Path(__file__).with_name('advisor_ui.js').read_bytes(),'text/javascript; charset=utf-8')
            if path=='/guide':
                guide=ROOT/'docs/MULTI_MARKET_GUIDE_ZH.html'
                if guide.exists():return self.reply(200,guide.read_bytes(),'text/html; charset=utf-8')
                return self.reply(404,{'error':'GUIDE_NOT_FOUND'})
            if path.startswith('/api/job/'):
                identifier=path.split('/')[-1]
                with lock:state=dict(jobs.get(identifier,{}))
                return self.reply(200,state) if state else self.reply(404,{'error':'JOB_NOT_FOUND'})
            parts=path.split('/')
            if len(parts)==4 and parts[1]=='download' and parts[2] in artifacts and parts[3] in ('report.docx','report.pdf','evidence.zip'):
                file=artifacts[parts[2]]/parts[3]
                if file.is_file():return self.reply(200,file.read_bytes(),'application/pdf' if file.suffix=='.pdf' else 'application/zip' if file.suffix=='.zip' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            self.reply(404,{'error':'NOT_FOUND'})
        def do_POST(self):
            if not self.allowed_host() or self.headers.get('X-Local-Token')!=token:return self.reply(403,{'error':'LOCAL_REQUEST_TOKEN_REQUIRED'})
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):return self.reply(403,{'error':'CROSS_ORIGIN_REJECTED'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000:raise ValueError('INVALID_INPUT_SIZE')
                a=json.loads(self.rfile.read(size));path=urlparse(self.path).path
                if not isinstance(a,dict):raise ValueError('INVALID_REQUEST')
                if path=='/api/assumption-discuss':
                    if set(a)!={'snapshot_id','discussion_id','overrides','sector','message','links','refresh'} or not isinstance(a['refresh'],bool) or a['sector']!='non_financial':raise ValueError('INVALID_DISCUSSION_REQUEST')
                    snapshot_file=snapshots.get(a['snapshot_id'])
                    if snapshot_file is None:raise ValueError('LOAD_COMPANY_BEFORE_DISCUSSION')
                    prior=discussions.get(a['discussion_id']) if a['discussion_id'] else None
                    if a['discussion_id'] and (prior is None or prior['snapshot_id']!=a['snapshot_id']):raise ValueError('DISCUSSION_COMPANY_MISMATCH')
                    discussion_id=a['discussion_id'] or uuid.uuid4().hex;directory=ROOT/'outputs/assumption_discussions'/discussion_id;identifier=uuid.uuid4().hex
                    with lock:
                        if any(j['status']=='running' for j in jobs.values()):raise ValueError('GENERATION_BUSY')
                        jobs[identifier]={'status':'running','message':'Researching public sources and discussing DCF assumptions with DeepSeek…'}
                    def discuss_work():
                        try:
                            from .assumption_advisor import discuss
                            old=read(directory/'discussion.json') if prior else None
                            session,answer=discuss(read(snapshot_file),a['overrides'],a['sector'],a['message'],a['links'],directory,old,a['refresh'])
                            discussions[discussion_id]={'directory':directory,'snapshot_id':a['snapshot_id']}
                            state={'status':'complete','message':'Discussion complete. Select suggestions to apply; manual values have not changed.','discussion_id':discussion_id,'answer':answer}
                        except Exception as error:
                            state={'status':'failed','message':str(error)[:300] if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__+' during discussion; inspect local logs.'}
                        with lock:jobs[identifier]=state
                    pool.submit(discuss_work);return self.reply(202,{'id':identifier})
                if path=='/api/assumption-apply':
                    if set(a)!={'discussion_id','snapshot_id','selected','overrides','sector'} or a['sector']!='non_financial':raise ValueError('INVALID_APPLY_REQUEST')
                    discussion=discussions.get(a['discussion_id'])
                    if not discussion or discussion['snapshot_id']!=a['snapshot_id']:raise ValueError('DISCUSSION_COMPANY_MISMATCH')
                    session=read(discussion['directory']/'discussion.json');suggestions=session['turns'][-1]['response']['suggestions']
                    if not isinstance(a['selected'],list) or not a['selected'] or any(isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(suggestions) for i in a['selected']):raise ValueError('SELECT_ASSUMPTIONS_TO_APPLY')
                    from .company_reports import analyze
                    snapshot=read(snapshots[a['snapshot_id']]);before=analyze(snapshot,a['overrides'],a['sector']);chosen={suggestions[i]['parameter']:suggestions[i]['value'] for i in a['selected']};after=analyze(snapshot,{**a['overrides'],**chosen},a['sector'])
                    applied={x['parameter']:x for x in session.get('applied',[])}
                    for i in a['selected']:applied[suggestions[i]['parameter']]=suggestions[i]
                    session['applied']=list(applied.values());write(discussion['directory']/'discussion.json',session)
                    return self.reply(200,{'overrides':chosen,'before':{s:v['quote_value_per_share'] for s,v in before['model'].items()},'after':{s:v['quote_value_per_share'] for s,v in after['model'].items()},'currency':snapshot['quote']['currency']})
                if path=='/api/company-preview':
                    if set(a)!={'market','symbol'}:raise ValueError('INVALID_REQUEST')
                    from .markets import collect,security
                    sec=security(a['market'],a['symbol']);identifier=uuid.uuid4().hex;directory=ROOT/'outputs/company_previews'/identifier
                    snapshot=collect(sec['market'],sec['symbol'],directory);snapshots[identifier]=directory/'company_snapshot.json';m=snapshot['periods'][-1]['metrics']
                    return self.reply(200,{'id':identifier,'name':snapshot['security']['name'],'symbol':sec['symbol'],'quote':f"{snapshot['quote']['currency']} {snapshot['quote']['close']:.2f} on {snapshot['quote']['date']}; statements in {snapshot['security']['reporting_currency']}",'coverage':'Latest annual end: '+snapshot['periods'][-1]['end']+'\nFields: '+', '.join(sorted(m))+'\n\n'+'\n'.join(snapshot['warnings'])})
                if path=='/api/company-generate':
                    if set(a)-{'market','symbol','sector','live','overrides','snapshot_id','discussion_id'} or not {'market','symbol','sector','live','overrides','snapshot_id'}<=set(a) or not isinstance(a['live'],bool) or a['sector'] not in ('non_financial','bank','insurance','reit','other_financial'):raise ValueError('INVALID_REQUEST')
                    from .markets import security
                    sec=security(a['market'],a['symbol']);allowed={'wacc','g','revenue_growth','ebit_margin','tax_rate','terminal_roic','da_ratio','capex_ratio','nwc_ratio','reserve','cash','debt','shares','nci','investments','non_operating_assets','other_claims'}
                    from .assumption_advisor import DEFAULT_SHIFTS
                    allowed |= set(DEFAULT_SHIFTS)
                    import math
                    if not isinstance(a['overrides'],dict) or set(a['overrides'])-allowed:raise ValueError('INVALID_ASSUMPTION_FIELDS')
                    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in a['overrides'].values()):raise ValueError('INVALID_ASSUMPTION_NUMBER')
                    snapshot_file=snapshots.get(a['snapshot_id']) if a['snapshot_id'] else None
                    if a['snapshot_id'] and snapshot_file is None:raise ValueError('UNKNOWN_PREVIEW_SNAPSHOT')
                    discussion=discussions.get(a.get('discussion_id')) if a.get('discussion_id') else None
                    if a.get('discussion_id') and (discussion is None or discussion['snapshot_id']!=a['snapshot_id']):raise ValueError('DISCUSSION_COMPANY_MISMATCH')
                    identifier=uuid.uuid4().hex
                    with lock:
                        if any(j['status']=='running' for j in jobs.values()):raise ValueError('GENERATION_BUSY: wait for the current report')
                        jobs[identifier]={'status':'running','message':'Loading data, calculating scenarios and generating the English report…'}
                    def work():
                        try:
                            from .company_reports import generate_company
                            report,result=generate_company(sec['market'],sec['symbol'],ROOT/'outputs/companies',snapshot_file=snapshot_file,overrides=a['overrides'],sector=a['sector'],live=a['live'],discussion_dir=discussion['directory'] if discussion else None)
                            snapshot=read(report/'company_snapshot.json');artifact=uuid.uuid4().hex;artifacts[artifact]=report
                            state={'status':'complete','message':'Report generated. Financial and document checks passed; review the assumptions, filing evidence and page layout.','artifact_id':artifact,'values':{s:result['model'][s]['quote_value_per_share'] if s in result['model'] else None for s in ['bull','base','bear']},'currency':snapshot['quote']['currency'],'name':snapshot['security']['name'],'quote':f"Close {snapshot['quote']['currency']} {snapshot['quote']['close']:.2f} on {snapshot['quote']['date']}; annual anchor {snapshot['periods'][-1]['end']}"}
                        except Exception as error:
                            message=str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__+' during report generation; inspect local logs.'
                            state={'status':'failed','message':message[:500]}
                        with lock:jobs[identifier]=state
                    pool.submit(work);return self.reply(202,{'id':identifier})
                self.reply(404,{'error':'NOT_FOUND'})
            except (ValueError,KeyError,TypeError,RuntimeError,OSError) as error:
                code=str(error).split(':',1)[0]
                if not code.isupper() or len(code)>80:code='LOCAL_OPERATION_FAILED'
                self.reply(400,{'error':code})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Local research workspace: http://127.0.0.1:{port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();pool.shutdown(wait=False)

if __name__=='__main__':serve()
