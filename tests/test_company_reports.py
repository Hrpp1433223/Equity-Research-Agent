import copy,json,math
from pathlib import Path
import pytest
from equity_research_agent.markets import security
from equity_research_agent.company_reports import analyze

ROOT=Path(__file__).resolve().parents[1]
def snapshot(market='US',symbol='NVDA'):
    return json.loads((ROOT/f'tests/fixtures/multi_market/{market}_{symbol}.json').read_text(encoding='utf-8'))

def test_symbols():
    assert security('HK','00700')['feed_symbol']=='0700.HK'
    assert security('SH','600519')['feed_symbol']=='600519.SS'
    for market,symbol in [('US','../env'),('SH','000001'),('HK','0')]:
        with pytest.raises(ValueError):security(market,symbol)

def test_fx_and_dupont():
    data=snapshot('HK','00700');result=analyze(data)
    for v in result['model'].values():assert v['quote_value_per_share']==pytest.approx(v['value_per_share']*data['fx']['quote_units_per_reporting_unit'])
    assert all(h['dupont_error'] is None or h['dupont_error']<1e-10 for h in result['history'])

def test_missing_essential_not_zero_and_financial_guard():
    data=snapshot();data['periods'][-1]['metrics'].pop('debt')
    assert analyze(data)['model']=={}
    assert analyze(data,{'debt':5000})['model']
    assert analyze(snapshot(),sector='bank')['model']=={}
    data=snapshot();data['periods'][-1]['metrics'].pop('ebit')
    assert analyze(data)['model']=={}
    assert analyze(data,{'ebit_margin':.4})['model']
    data=snapshot();data['periods'][-1]['metrics'].pop('ebit')
    assert analyze(data)['model']=={}
    assert analyze(data,{'ebit_margin':.4})['model']

def test_override_existing_debt_changes_value():
    data=snapshot();base=analyze(data);changed=analyze(data,{'debt':data['periods'][-1]['metrics']['debt']/1e6+1000})
    assert changed['model']['base']['equity']==pytest.approx(base['model']['base']['equity']-1000)
    changed=analyze(data,{'cash':data['periods'][-1]['metrics']['cash']/1e6+1000})
    assert changed['model']['base']['equity']==pytest.approx(base['model']['base']['equity']+1000)
    changed=analyze(data,{'cash':data['periods'][-1]['metrics']['cash']/1e6+1000})
    assert changed['model']['base']['equity']==pytest.approx(base['model']['base']['equity']+1000)

def test_zero_tax_and_invalid_numbers():
    data=snapshot();data['periods'][-1]['metrics']['tax']=0
    assert analyze(data)['driver_parameters']['tax_rate']==0
    for overrides in [{'wacc':math.nan},{'wacc':True},{'unknown':1},{'debt':-1}]:
        with pytest.raises(ValueError):analyze(data,overrides)

def test_actual_sec_fiscal_end():
    data=snapshot();assert data['periods'][-1]['end']=='2026-01-25'
    assert data['periods'][-1]['vendor_period_end']=='2026-01-31'
