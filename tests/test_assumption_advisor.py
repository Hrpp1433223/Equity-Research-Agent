import copy,json
from pathlib import Path
import pytest
from equity_research_agent.assumption_advisor import validate_response,DEFAULT_SHIFTS,public_url,current_parameters,discuss,extract
from equity_research_agent.company_reports import analyze
ROOT=Path(__file__).resolve().parents[1]
def snapshot():return json.loads((ROOT/'tests/fixtures/multi_market/US_NVDA.json').read_text(encoding='utf-8'))
def proposal(parameter='wacc',value=.11):return {'reply':'Test a higher discount rate without targeting the market price.','suggestions':[{'parameter':parameter,'value':value,'low':value-.005,'high':value+.005,'rationale':'Explicit risk hypothesis.','counterargument':'A lower equity risk premium would reduce it.','source_ids':[],'basis':'user_judgment'}]}
def test_proposal_uses_engine_without_mutation():
    s=snapshot();original=copy.deepcopy(s);overrides={};p,r=validate_response(proposal(),[],s,overrides,'non_financial')
    assert overrides=={} and s==original and p['wacc']==.11
    assert r['model']['base']['quote_value_per_share']<analyze(s)['model']['base']['quote_value_per_share']
@pytest.mark.parametrize('change',[{'parameter':'cash'},{'source_ids':['R999']},{'value':float('nan')},{'basis':'verified_fact'},{'low':.20},{'rationale':'中文'}])
def test_invalid_advice_rejected(change):
    a=proposal();a['suggestions'][0].update(change)
    with pytest.raises(ValueError):validate_response(a,[],snapshot(),{},'non_financial')
def test_scenario_shifts_recalculate_and_defaults_preserved():
    s=snapshot();a=analyze(s);b=analyze(s,DEFAULT_SHIFTS);assert a['model']==b['model']
    changed=analyze(s,{'bull_growth_shift':.10,'bear_margin_shift':-.06})
    assert changed['model']['base']==a['model']['base']
    assert changed['model']['bull']['equity']>a['model']['bull']['equity']
    assert changed['model']['bear']['equity']<a['model']['bear']['equity']
def test_private_research_urls_rejected():
    for u in ['http://example.com','https://127.0.0.1','https://[::1]/','https://user:pass@example.com','https://example.com:8766']:
        with pytest.raises(ValueError):public_url(u)
def test_publication_date_not_search_crawl_date():
    text,date=extract(b"<script>ga_four_event('PublishDate','View','August 26, 2026');</script><article>Quarterly results</article>",'text/html')
    assert date=='2026-08-26' and 'Quarterly results' in text
    assert extract(b'<p>Undated content</p>','text/html')[1] is None
def test_multi_turn_keeps_applied_and_no_fake_research(monkeypatch,tmp_path):
    def research(s,d,links):d.mkdir();return {'sources':[],'warnings':['Search unavailable'],'queries':[]}
    monkeypatch.setattr('equity_research_agent.assumption_advisor.research',research)
    class Provider:
        def request(self,messages,tools):return {'content':json.dumps(proposal())},{'finish_reason':'stop','model':'test'}
    one,out=discuss(snapshot(),{},'non_financial','Discuss risk',[],tmp_path,provider=Provider())
    assert out['sources']==[] and out['research_warnings'] and not one['applied']
    one['applied']=one['turns'][0]['response']['suggestions']
    two,out=discuss(snapshot(),{'wacc':.11},'non_financial','What would invalidate this?',[],tmp_path,one,provider=Provider())
    assert len(two['turns'])==2 and two['applied']==one['applied']
