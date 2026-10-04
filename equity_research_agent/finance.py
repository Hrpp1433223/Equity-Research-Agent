"""Single-currency million / million shares FCFF model; no network or LLM."""
from datetime import date
from math import isfinite
from copy import deepcopy

REQUIRED_BRIDGE=('cash','investments','operating_cash_reserve','debt','other_senior_claims','nci','non_operating_assets','shares')

def number(value,field):
    if not isinstance(value,(int,float)) or isinstance(value,bool) or not isfinite(value):
        raise ValueError('MISSING_OR_INVALID_FACT: '+field)
    return value

def normalize(inputs):
    x=deepcopy(inputs)
    currency=x.get('currency')
    if currency not in ('USD','CNY','HKD'):raise ValueError('INVALID_CURRENCY: explicit FX normalization required')
    amount_scale={currency+' million':1,currency+' billion':1000,currency+' thousand':.001,currency:1e-6}.get(x.get('unit'))
    share_scale={'million shares':1,'thousand shares':.001,'shares':.000001}.get(x.get('share_unit'))
    if amount_scale is None or share_scale is None:raise ValueError('INVALID_UNIT')
    all_forecasts=[x['forecasts']]+list(x.get('scenario_forecasts',{}).values())
    normalized_rows=set()
    for p in [row for rows in all_forecasts for row in rows]:
        if id(p) in normalized_rows:continue
        normalized_rows.add(id(p))
        for k in ['revenue','ebit','da','capex','nwc']:p[k]=number(p.get(k),'forecast.'+k)*amount_scale
        p['tax_rate']=number(p.get('tax_rate'),'forecast.tax_rate')
        if p['revenue']<=0:raise ValueError('INVALID_DCF_INPUT: positive forecast revenue required')
    x['opening_nwc']=number(x.get('opening_nwc'),'opening_nwc')*amount_scale
    if number(x.get('reference_price'),'reference_price')<=0:raise ValueError('INVALID_DCF_INPUT: positive reference price required')
    for k in REQUIRED_BRIDGE:
        if k in x['bridge'] and x['bridge'][k] is not None:x['bridge'][k]=number(x['bridge'][k],'bridge.'+k)*(share_scale if k=='shares' else amount_scale)
    x['unit']=currency+' million';x['share_unit']='million shares';return x

def value(inputs, assumptions, scenario='base'):
    inputs=normalize(inputs);cfg=deepcopy(assumptions); wacc=number(cfg.get('wacc'),'wacc'); g=number(cfg.get('g'),'g'); bridge=inputs['bridge']
    if not (isfinite(wacc) and isfinite(g) and wacc>g and wacc>-1): raise ValueError('INVALID_DCF_INPUT: WACC must exceed g')
    for k in REQUIRED_BRIDGE:
        if k not in bridge or bridge[k] is None or not isfinite(bridge[k]): raise ValueError('MISSING_REQUIRED_FACT: '+k)
    if bridge['shares']<=0: raise ValueError('INVALID_DCF_INPUT: positive shares required')
    if number(cfg.get('terminal_roic'),'terminal_roic')<=g or cfg['terminal_roic']<=0: raise ValueError('INVALID_DCF_INPUT: terminal ROIC must exceed growth')
    if not 0<=number(cfg.get('terminal_tax_rate'),'terminal_tax_rate')<=1:raise ValueError('INVALID_DCF_INPUT: stable tax rate')
    number(cfg.get('terminal_margin'),'terminal_margin')
    asof=date.fromisoformat(cfg['as_of']); scen=cfg['scenarios'][scenario]; periods=[]; prev_nwc=inputs['opening_nwc']; growth_scale=1
    for i,ref in enumerate(inputs.get('scenario_forecasts',{}).get(scenario,inputs['forecasts'])):
        end=date.fromisoformat(ref['end']); start=date.fromisoformat(ref['start'])
        if end<=start:raise ValueError('INVALID_DCF_INPUT: forecast end must follow start')
        tau=(end-asof).days/365.0
        portion=max(0,min(1,(end-max(asof,start)).days/(end-start).days))
        growth_scale*=1+scen['revenue_growth_shift']
        rev=ref['revenue']*growth_scale
        margin=ref['ebit']/ref['revenue']+scen['ebit_margin_shift']
        ebit=rev*margin; tax=ref['tax_rate']; nopat=ebit-max(ebit,0)*tax
        da=rev*(ref['da']/ref['revenue']); capex=rev*(ref['capex']/ref['revenue']+scen['capex_ratio_shift'])
        nwc=ref['nwc']/ref['revenue']*rev; delta=nwc-prev_nwc
        fcff=nopat+da-capex-delta; cashflow=fcff*portion; df=(1+wacc)**(-tau)
        if not all(isfinite(x) for x in [rev,ebit,da,capex,nwc,tax]) or rev<=0 or da<0 or capex<0 or not 0<=tax<=1:raise ValueError('INVALID_DCF_INPUT: operating assumptions')
        prev_nwc=nwc
        if end<asof:continue
        periods.append(dict(year=ref['year'],end=ref['end'],revenue=rev,ebit=ebit,margin=margin,tax_rate=tax,nopat=nopat,da=da,capex=capex,nwc=nwc,delta_nwc=delta,annual_fcff=fcff,portion=portion,fcff=cashflow,tau=tau,discount_factor=df,pv=cashflow*df))
    if not periods: raise ValueError('INVALID_DCF_INPUT: no forecast after valuation date')
    last=periods[-1]; terminal_rev=last['revenue']*(1+g)
    terminal_margin=number(cfg.get('terminal_margin_by_scenario',{}).get(scenario,cfg['terminal_margin']),'terminal_margin_by_scenario')+scen['ebit_margin_shift']
    terminal_nopat=terminal_rev*terminal_margin*(1-cfg['terminal_tax_rate'])
    reinvest=terminal_nopat*g/cfg['terminal_roic']; terminal_fcff=terminal_nopat-reinvest
    tv=terminal_fcff/(wacc-g); tv_pv=tv*last['discount_factor']; explicit=sum(x['pv'] for x in periods); ev=explicit+tv_pv
    excess=bridge['cash']+bridge['investments']-bridge['operating_cash_reserve']
    equity=ev+excess+bridge['non_operating_assets']-bridge['debt']-bridge['other_senior_claims']-bridge['nci']
    per_share=equity/bridge['shares']; upside=per_share/inputs['reference_price']-1
    return dict(scenario=scenario,periods=periods,terminal_revenue=terminal_rev,terminal_margin=terminal_margin,terminal_nopat=terminal_nopat,terminal_reinvestment=reinvest,terminal_fcff=terminal_fcff,terminal_value=tv,terminal_pv=tv_pv,explicit_pv=explicit,ev=ev,equity=equity,excess_cash=excess,bridge=deepcopy(bridge),value_per_share=per_share,upside=upside,terminal_share=tv_pv/ev,wacc=wacc,g=g,as_of=cfg['as_of'])

def scenarios(inputs,assumptions): return {s:value(inputs,assumptions,s) for s in ('bull','base','bear')}

def sensitivity(inputs,assumptions):
    ws=[assumptions['wacc']+x for x in [-.01,-.005,0,.005,.01]]; gs=[assumptions['g']+x for x in [-.01,-.005,0,.005,.01]]
    matrix=[]
    for w in ws:
        row=[]
        for g in gs:
            c=deepcopy(assumptions); c.update(wacc=w,g=g)
            row.append(value(inputs,c)['value_per_share'] if w>g else None)
        matrix.append(row)
    return {'wacc':ws,'g':gs,'values':matrix}
