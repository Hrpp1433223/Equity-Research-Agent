"""Actual local HTTP routes with deterministic research/model substitutes."""
import json,re,threading,socket,time,urllib.request,urllib.error
from pathlib import Path
import pytest
from equity_research_agent.company_reports import read,write,analyze
from equity_research_agent.assumption_advisor import DEFAULT_SHIFTS

def test_explicit_application_and_binding(monkeypatch,tmp_path):
    from equity_research_agent import app,markets,assumption_advisor
    root=Path(__file__).resolve().parents[1];snapshot=read(root/'tests/fixtures/multi_market/US_NVDA.json')
    monkeypatch.setattr(app,'ROOT',tmp_path)
    def collect(market,symbol,directory):directory.mkdir(parents=True);write(directory/'company_snapshot.json',snapshot);return snapshot
    monkeypatch.setattr(markets,'collect',collect)
    suggestion={'parameter':'revenue_growth','value':.35,'low':.25,'high':.45,'rationale':'Inference for test','counterargument':'Growth could slow','source_ids':[],'basis':'inference'}
    def discuss(snapshot,overrides,sector,message,links,directory,previous,refresh):
        directory.mkdir(parents=True);session={'turns':[{'response':{'suggestions':[suggestion]}}]};write(directory/'discussion.json',session)
        return session,{'reply':'Test only','suggestions':[suggestion]}
    monkeypatch.setattr(assumption_advisor,'discuss',discuss)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    # Capture the server so it is closed deterministically.
    original=app.ThreadingHTTPServer;servers=[]
    def server(*args,**kwargs):s=original(*args,**kwargs);servers.append(s);return s
    monkeypatch.setattr(app,'ThreadingHTTPServer',server)
    thread=threading.Thread(target=app.serve,args=(port,),daemon=True);thread.start()
    for _ in range(100):
        if servers:break
        time.sleep(.01)
    base=f'http://127.0.0.1:{port}'
    try:
        page=urllib.request.urlopen(base).read().decode();token=re.search("const token='([^']+)'",page).group(1)
        def post(path,data):
            req=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Local-Token':token})
            return json.load(urllib.request.urlopen(req))
        first=post('/api/company-preview',{'market':'US','symbol':'NVDA'})['id']
        job=post('/api/assumption-discuss',{'snapshot_id':first,'discussion_id':None,'overrides':{},'sector':'non_financial','message':'Test','links':[],'refresh':False})['id']
        for _ in range(100):
            state=json.load(urllib.request.urlopen(base+'/api/job/'+job))
            if state['status']!='running':break
            time.sleep(.01)
        assert state['status']=='complete';d=state['discussion_id'];session=read(tmp_path/'outputs/assumption_discussions'/d/'discussion.json');assert not session.get('applied')
        applied=post('/api/assumption-apply',{'discussion_id':d,'snapshot_id':first,'selected':[0],'overrides':{'wacc':.11},'sector':'non_financial'})
        expected=analyze(snapshot,{'wacc':.11,'revenue_growth':.35})
        assert applied['after']['base']==pytest.approx(expected['model']['base']['quote_value_per_share'])
        assert set(applied['overrides'])=={'revenue_growth'}
        with pytest.raises(urllib.error.HTTPError) as e:post('/api/assumption-apply',{'discussion_id':d,'snapshot_id':'wrong','selected':[0],'overrides':{},'sector':'non_financial'})
        assert e.value.code==400
    finally:
        servers[0].shutdown();servers[0].server_close();thread.join(timeout=3)
