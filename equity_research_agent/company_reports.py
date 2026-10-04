"""Company-independent financial analysis, explicit assumptions and English reports."""
import calendar,copy,hashlib,json,re,zipfile,math
from datetime import date
from pathlib import Path
from .finance import scenarios,sensitivity
from .markets import collect

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def fmt(x,d=1):return 'Not available' if x is None else f'{x:,.{d}f}'
def pct(x):return 'Not available' if x is None else f'{x:.1%}'
def div(a,b):return a/b if a is not None and b is not None and b!=0 else None
def fiscal_end(end,offset):
    y=int(end[:4])+offset;m=int(end[5:7]);day=min(int(end[8:]),calendar.monthrange(y,m)[1]);return date(y,m,day).isoformat()

def analyze(snapshot,overrides=None,sector='non_financial'):
    changes=overrides or {}
    allowed={'revenue_growth','ebit_margin','tax_rate','da_ratio','capex_ratio','nwc_ratio','reserve','nci','investments','wacc','g','terminal_roic','other_claims','non_operating_assets','cash','debt','shares'}
    from .assumption_advisor import DEFAULT_SHIFTS
    allowed |= set(DEFAULT_SHIFTS)
    if set(changes)-allowed or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in changes.values()):raise ValueError('INVALID_COMPANY_OVERRIDES')
    if any(changes.get(k,0)<0 for k in ['cash','debt','shares','other_claims','non_operating_assets']):raise ValueError('INVALID_COMPANY_OVERRIDES')
    history=[];periods=snapshot['periods'];warnings=list(snapshot['warnings']);last=periods[-1];m=copy.deepcopy(last['metrics']);currency=snapshot['security']['reporting_currency'];fx=snapshot['fx']['quote_units_per_reporting_unit'];quote=snapshot['quote']
    for k in ['cash','debt','shares']:
        if k in changes:m[k]=changes[k]*1e6
    if m.get('ebit') is None and m.get('revenue') is not None and 'ebit_margin' in changes:m['ebit']=m['revenue']*changes['ebit_margin']
    for i,p in enumerate(periods):
        v=p['metrics'];old=periods[i-1]['metrics'] if i else {};assets=(v.get('assets',0)+old.get('assets',0))/2 if v.get('assets') is not None and old.get('assets') is not None else None;equity=(v.get('equity',0)+old.get('equity',0))/2 if v.get('equity') is not None and old.get('equity') is not None else None
        margin=div(v.get('parent_income'),v.get('revenue'));turn=div(v.get('revenue'),assets);lever=div(assets,equity);roe=div(v.get('parent_income'),equity)
        product=margin*turn*lever if all(x is not None for x in [margin,turn,lever]) else None
        history.append({'end':p['end'],'growth':div(v.get('revenue'),old.get('revenue'))-1 if old.get('revenue',0)>0 else None,'ebit_margin':div(v.get('ebit'),v.get('revenue')),'parent_net_margin':margin,'cfo_to_parent_income':div(v.get('cfo'),v.get('parent_income')),'parent_roe':roe,'asset_turnover':turn,'assets_to_parent_equity':lever,'dupont_product':product,'dupont_error':abs(roe-product) if product is not None else None})
    detected=bool(re.search(r'bank|insurance|reit|securities|financial services|银行|保险|证券',snapshot['security']['name']+' '+snapshot['security'].get('original_source_name',''),re.I)) or (snapshot['security']['market']=='US' and snapshot['security']['symbol'] in {'JPM','BAC','WFC','C','GS','MS','SCHW','BRK.B','BRK.A'})
    result={'history':history,'warnings':warnings,'sector':sector,'valuation_status':'not_available','model':{},'inputs':None,'assumptions':None,'sensitivity':None}
    if sector!='non_financial' or detected:
        warnings.append('Corporate FCFF is disabled for financial-sector companies. Use a separately validated equity/residual-income or property valuation method.');return result
    missing=[k for k in ['revenue','ebit','cash','debt','shares'] if m.get(k) is None]
    for k in list(missing):
        if changes.get(k) is not None:m=copy.deepcopy(m);m[k]=changes[k]*(1e6 if k!='shares' else 1e6);missing.remove(k)
    if missing:
        warnings.append('DCF withheld: essential inputs missing: '+', '.join(missing)+'. Supply explicit reviewed overrides.');return result
    rev=m['revenue']/1e6;observed_growth=history[-1]['growth'] or 0;growth=changes.get('revenue_growth',max(-.10,min(.25,observed_growth)));margin=changes.get('ebit_margin',m['ebit']/m['revenue'])
    observed_tax=div(m.get('tax'),m.get('pretax'));tax=changes.get('tax_rate',max(0,min(.35,observed_tax if observed_tax is not None else {'USD':.21,'CNY':.25,'HKD':.165}[currency])))
    da_ratio=changes.get('da_ratio',(m.get('da') if m.get('da') is not None else rev*1e6*.02)/m['revenue']);capex_ratio=changes.get('capex_ratio',(m.get('capex') if m.get('capex') is not None else rev*1e6*.03)/m['revenue'])
    trade=sum(m.get(k,0) or 0 for k in ['receivables','inventory'])-sum(m.get(k,0) or 0 for k in ['payables','deferred_revenue']);nwc_ratio=changes.get('nwc_ratio',trade/m['revenue']);reserve=changes.get('reserve',rev*.10);nci=changes.get('nci',(m.get('nci') or 0)/1e6);investments=changes.get('investments',(m.get('investments') or 0)/1e6)
    if m.get('nci') is None:warnings.append('NCI deduction is an explicit zero-recognition assumption because the feed omitted this field; this is not proof that no minority claims exist.')
    if m.get('investments') is None:warnings.append('Separate investment recognition defaults to zero as an explicit valuation policy, not a factual zero balance.')
    if m.get('da') is None:warnings.append('D&A ratio defaults to an explicit 2% assumption because no matched observation was available.')
    if m.get('capex') is None:warnings.append('Capex ratio defaults to an explicit 3% assumption because no matched observation was available.')
    if not all(-.5<=v<=1 for v in [growth,margin]) or not 0<=tax<=.5 or min(da_ratio,capex_ratio,reserve,nci,investments)<0:raise ValueError('INVALID_COMPANY_ASSUMPTIONS')
    wacc=changes.get('wacc',.10);g=changes.get('g',.02);roic=changes.get('terminal_roic',.12)
    shifts={k:changes.get(k,v) for k,v in DEFAULT_SHIFTS.items()}
    if any(abs(v)>.30 for v in shifts.values()):raise ValueError('INVALID_SCENARIO_SHIFT')
    for s in ['bull','bear']:
        if not -.5<=margin+shifts[s+'_margin_shift']<=1 or capex_ratio+shifts[s+'_capex_shift']<0:raise ValueError('INVALID_SCENARIO_ASSUMPTIONS')
    cfg={'as_of':snapshot['as_of'],'wacc':wacc,'g':g,'terminal_roic':roic,'terminal_margin':margin,'terminal_tax_rate':tax,'scenarios':{s:{'revenue_growth_shift':0,'ebit_margin_shift':0,'capex_ratio_shift':0} for s in ['bull','base','bear']},'terminal_margin_by_scenario':{'base':margin,'bull':margin+shifts['bull_margin_shift'],'bear':margin+shifts['bear_margin_shift']}}
    forecasts={}
    for s,gs,ms in [('base',0,0),('bull',shifts['bull_growth_shift'],shifts['bull_margin_shift']),('bear',shifts['bear_growth_shift'],shifts['bear_margin_shift'])]:
        revenue=rev;rows=[]
        for i in range(1,6):
            end=fiscal_end(last['end'],i);start=fiscal_end(last['end'],i-1);annual_growth=growth*(6-i)/5+g*(i-1)/5+gs;revenue*=1+annual_growth
            if annual_growth<=-1:raise ValueError('INVALID_SCENARIO_GROWTH')
            rows.append({'year':end[:4]+'E','start':start,'end':end,'revenue':revenue,'ebit':revenue*(margin+ms),'tax_rate':tax,'da':revenue*da_ratio,'capex':revenue*(capex_ratio+(shifts[s+'_capex_shift'] if s!='base' else 0)),'nwc':revenue*(nwc_ratio+(shifts[s+'_nwc_shift'] if s!='base' else 0)),'revenue_growth':annual_growth})
        forecasts[s]=rows
    if forecasts['base'][0]['end']<=snapshot['as_of']:raise ValueError('STALE_ANNUAL_ANCHOR: refresh data; no skipped forecast years permitted')
    inputs={'currency':currency,'unit':currency+' million','share_unit':'million shares','reference_price':quote['close']/fx,'opening_nwc':trade/1e6,'forecasts':forecasts['base'],'scenario_forecasts':forecasts,'bridge':{'cash':m['cash']/1e6,'investments':investments,'operating_cash_reserve':reserve,'debt':m['debt']/1e6,'other_senior_claims':changes.get('other_claims',0),'nci':nci,'non_operating_assets':changes.get('non_operating_assets',0),'shares':m['shares']/1e6}}
    model=scenarios(inputs,cfg);sens=sensitivity(inputs,cfg)
    for v in model.values():v['currency']=currency;v['quote_value_per_share']=v['value_per_share']*fx
    warnings+=['Defaults are transparent scenario seeds, not analyst-validated fair-value assumptions: latest margin, capped recent growth fading to perpetual growth, historical D&A/capex ratios, 10% revenue operating reserve, 10% WACC and 12% terminal ROIC unless overridden.','Latest annual cash/debt/share balances are frozen unless explicitly overridden; subsequent dividends, buybacks, financing, dilution and interim results are not automatically bridged.','NCI is deducted at book value; unrecognized non-operating stakes, assets and senior claims may materially change value.','First future fiscal cash flow is prorated by days remaining; same-calendar-date fiscal forecasts approximate 52/53-week calendars. Stock-based compensation is not deducted separately and future dilution is not forecast.','Trade NWC uses receivables + inventory - payables - deferred revenue. Missing components are omitted; this proxy excludes other operating current balances. Vendor operating-profit definitions may include investment or finance items and require filing reconciliation before use as core EBIT.']
    result.update(valuation_status='explicit_assumption_dcf',model=model,inputs=inputs,assumptions=cfg,sensitivity=sens,driver_parameters={'revenue_growth':growth,'ebit_margin':margin,'tax_rate':tax,'da_ratio':da_ratio,'capex_ratio':capex_ratio,'nwc_ratio':nwc_ratio,'reserve':reserve,'provenance':'explicit user overrides or disclosed generic defaults','user_overrides':changes})
    result['driver_parameters']['scenario_shifts']=shifts
    return result

def narrative(snapshot,result,run,live):
    history=result['history'];last=snapshot['periods'][-1];currency=snapshot['security']['reporting_currency'];quote_currency=snapshot['quote']['currency'];pack=[]
    for i,(p,h) in enumerate(zip(snapshot['periods'],history),1):
        pack.append({'id':f'F{i:02}','fiscal_end':p['end'],'display':{'revenue':currency+' '+fmt(p['metrics'].get('revenue',0)/1e6)+' million','EBIT_margin':pct(h['ebit_margin']),'parent_net_margin':pct(h['parent_net_margin']),'CFO_parent_profit':fmt(h['cfo_to_parent_income'],2)+'x','parent_ROE':pct(h['parent_roe'])},'status':'See field-level source references; unverified secondary data remains unverified.'})
    calc={'id':'C01','valuation_status':result['valuation_status'],'values':{s:quote_currency+' '+fmt(v['quote_value_per_share'],2)+'/share' for s,v in result['model'].items()},'close':quote_currency+' '+fmt(snapshot['quote']['close'],2)+'/share','quote_date':snapshot['quote']['date']}
    if result['model']:calc.update(base_upside=pct(result['model']['base']['upside']),terminal_EV=pct(result['model']['base']['terminal_share']),net_bridge=quote_currency+' '+fmt((result['model']['base']['equity']-result['model']['base']['ev'])/result['inputs']['bridge']['shares']*snapshot['fx']['quote_units_per_reporting_unit'],2)+'/share')
    drivers=result.get('driver_parameters',{})
    assumptions={'id':'A01','drivers':{k:(currency+' '+fmt(v)+' million' if k=='reserve' else pct(v)) for k,v in drivers.items() if k not in {'provenance','user_overrides','scenario_shifts'}},'scenario_policy':drivers.get('scenario_shifts',{}),'discussion':result.get('adopted_assumptions',[])}
    if result['assumptions']:assumptions.update(wacc=pct(result['assumptions']['wacc']),perpetual_growth=pct(result['assumptions']['g']),stable_roic=pct(result['assumptions']['terminal_roic']),annual_bridge={k:fmt(v,3)+' million shares' if k=='shares' else currency+' '+fmt(v)+' million' for k,v in result['inputs']['bridge'].items()})
    evidence={'issuer':snapshot['security'],'as_of':snapshot['as_of'],'facts':pack,'calculated_results':[calc],'assumptions':assumptions,'currency_conversion':{'id':'X01','reporting_currency':currency,'quote_currency':quote_currency,'rate':fmt(snapshot['fx']['quote_units_per_reporting_unit'],6),'date':snapshot['fx']['date']},'limitations':{'id':'L01','items':result['warnings']},'operating_evidence':[]};write(run/'narrative_evidence.json',evidence)
    if live:
        from .llm_config import load_llm_settings
        from .providers import HTTPProvider
        from .budget import Budget
        config=read(ROOT/'configs/execution.json');config['max_output_tokens']=24000;provider=HTTPProvider(load_llm_settings(),Budget(config))
        msg,meta=provider.request([{'role':'system','content':(ROOT/'prompts/multi_market_analysis_en.txt').read_text(encoding='utf-8')},{'role':'user','content':json.dumps(evidence,ensure_ascii=False)}],[]);write(run/'provider_metadata.json',meta)
        if meta.get('finish_reason')!='stop':raise ValueError('INCOMPLETE_NARRATIVE_OUTPUT')
        text=msg.get('content','').strip();(run/'model_response.txt').write_text(text,encoding='utf-8');out=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text))
        if len(out['sections'])!=2 or re.search('[\u3400-\u9fff]',json.dumps(out,ensure_ascii=False)):raise ValueError('INVALID_ENGLISH_NARRATIVE')
        valid={p['id'] for p in pack}|{'C01','A01','L01','X01'}
        for s in out['sections']:
            if not s['paragraphs'] or set(re.findall(r'\[([^\[\]]+)\]',' '.join(s['paragraphs']))) - valid:raise ValueError('INVALID_NARRATIVE_REFERENCES')
        write(run/'narrative.json',out);return out
    h=history[-1];prev=history[-2];ref=f'[F{len(pack):02}]';prior=f'[F{len(pack)-1:02}]'
    paragraphs=[f"At the latest fiscal end {last['end']}, EBIT margin was {pct(h['ebit_margin'])}, compared with {pct(prev['ebit_margin'])} in the preceding annual period {ref}{prior}. Parent net margin was {pct(h['parent_net_margin'])}. A change in operating margin indicates a change in the revenue-cost relationship, but does not identify the contributions of selling prices, product mix, utilization or expenses.",f"Operating cash flow relative to parent profit was {fmt(h['cfo_to_parent_income'],2)}x {ref}. This ratio compares consolidated operating cash flow with parent-attributable profit and is a cash-conversion diagnostic, not a scope-matched accounting identity. Receivable collection, inventory movements and customer advances can change cash conversion independently of profit; segment results and working-capital notes are needed to distinguish these mechanisms."]
    second=[f"The annual balance and share anchor is {last['end']}, whereas the dated stock close is {snapshot['quote']['date']}. Subsequent distributions, financing and dilution require a separate bridge. Reported cash cannot automatically be treated as distributable: liquidity needs, restrictions and funding commitments must be examined.","The three operating scenarios use explicit growth, margin, reinvestment and trade-working-capital assumptions. These are scenario seeds, not proof of fair value. Missing business evidence limits causal claims; bank, insurer and REIT valuation requires a different method."]
    if result['model']:second.append(f"Base DCF is {calc['values']['base']} versus {calc['close']}, a {calc['base_upside']} difference [C01]. Terminal value represents {calc['terminal_EV']} of operating EV. Discount-rate, terminal-profitability and cash-reserve uncertainty must therefore be considered before drawing an investment conclusion.")
    out={'sections':[{'title':'Profitability and cash conversion','paragraphs':paragraphs},{'title':'Capital allocation and valuation implications','paragraphs':second}],'missing_evidence':['Segment and pricing/cost evidence','Quarterly collections and remaining funding requirements','Post-balance dividends, buybacks and financing']};write(run/'narrative.json',out);return out

def build(snapshot,result,text,run):
    from .company_layout import build_reference_report
    return build_reference_report(snapshot,result,text,run)

def validate(run):
    import pdfplumber
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    run=Path(run);manifest=read(run/'run_manifest.json');result=read(run/'analysis_results.json');checks={}
    with ZipFile(run/'report.docx') as z:
        root=ET.fromstring(z.read('word/document.xml'));text=' '.join(n.text or '' for n in root.iter() if n.tag.endswith('}t'))
        checks['english_only_docx']=not re.search('[\u3400-\u9fff]',text);checks['editable_text']=len(text)>3000;checks['no_placeholders']=not any(s in text for s in ['{{','TODO','TBD','NaN','Infinity']);checks['docx_hash']=hashlib.sha256((run/'report.docx').read_bytes()).hexdigest()==manifest['docx_sha256']
        if manifest.get('template_version')=='reference_layout_v2':
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            cover=root.find('w:body/w:tbl',ns);grid=cover.find('w:tblGrid',ns) if cover is not None else []
            checks['reference_cover_frame']=len(grid)==2 and [int(c.get('{'+ns['w']+'}w')) for c in grid]==[6660,3980]
            if result['model']:
                import posixpath
                chart=manifest['chart'];blips=root.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip');rels=ET.fromstring(z.read('word/_rels/document.xml.rels'));targets={r.get('Id'):r.get('Target') for r in rels};embeds=[]
                for b in blips:
                    target=targets.get(b.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed'))
                    if target:embeds.append(hashlib.sha256(z.read(posixpath.normpath('word/'+target))).hexdigest())
                checks['dcf_chart_embedded']=chart['sha256'] in embeds
                checks['chart_currency_values']=chart['currency']==read(run/'company_snapshot.json')['quote']['currency'] and all(abs(chart['values'][s]-v['quote_value_per_share'])<1e-8 for s,v in result['model'].items())
    if result['model']:
        recalculated=scenarios(result['inputs'],result['assumptions']);checks['financial_recalculation']=all(abs(recalculated[s]['value_per_share']-result['model'][s]['value_per_share'])<1e-8 for s in recalculated)
        checks['scenario_values_in_word']=all(fmt(v['quote_value_per_share'],2) in text for v in result['model'].values())
        fx=read(run/'company_snapshot.json')['fx']['quote_units_per_reporting_unit'];checks['fx_consistent']=all(abs(v['quote_value_per_share']-v['value_per_share']*fx)<1e-8 for v in result['model'].values())
        checks['sensitivity_center']=abs(result['sensitivity']['values'][2][2]-result['model']['base']['value_per_share'])<1e-8
    checks['dupont_identity']=all(h['dupont_error'] is None or h['dupont_error']<1e-8 for h in result['history'])
    snapshot=read(run/'company_snapshot.json')
    checks['source_cache_hashes']=all(re.fullmatch(r'[a-f0-9]{64}\.json',s['local_file']) and (run/'data'/s['local_file']).exists() and hashlib.sha256((run/'data'/s['local_file']).read_bytes()).hexdigest()==s['sha256'] for s in snapshot['sources'])
    if manifest.get('evidence_hashes'):checks['frozen_evidence_hashes']=all((run/p).is_file() and hashlib.sha256((run/p).read_bytes()).hexdigest()==sha for p,sha in manifest['evidence_hashes'].items())
    if (run/'report.pdf').exists():
        checks['pdf_export_hash']=hashlib.sha256((run/'report.pdf').read_bytes()).hexdigest()==manifest.get('pdf_sha256')
        with pdfplumber.open(run/'report.pdf') as d:
            pdftext='\n'.join(p.extract_text() or '' for p in d.pages);checks['page_count']=len(d.pages)==manifest['expected_pages'];checks['english_only_pdf']=not re.search('[\u3400-\u9fff]',pdftext);checks['scenario_values_in_pdf']=all(fmt(v['quote_value_per_share'],2) in pdftext for v in result['model'].values());outliers=[]
            for n,p in enumerate(d.pages,1):
                for c in p.chars:
                    if c.get('text','').strip() and (c['x0']<35 or c['x1']>p.width-35 or c['top']<20 or c['bottom']>p.height-9):outliers.append({'page':n,'text':c['text']})
            checks['page_bounds']=not outliers
    qa=run/'qa';qa.mkdir(exist_ok=True);out={'passed':all(checks.values()),'checks':checks,'visual_review':'required for new content','outliers':locals().get('outliers',[])};write(qa/'validation.json',out);return out

def seal_and_package(run):
    run=Path(run);manifest=read(run/'run_manifest.json')
    paths=list(run.glob('*.json'))+list((run/'data').glob('*.json'))+[run/'analysis_prompt.txt']+list((run/'discussion_research').glob('*'))
    manifest['evidence_hashes']={p.relative_to(run).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.name!='run_manifest.json'}
    write(run/'run_manifest.json',manifest)
    qa=validate(run)
    if not qa['passed']:raise ValueError('MULTI_MARKET_REPORT_VALIDATION_FAILED: '+str(run))
    with zipfile.ZipFile(run/'evidence.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in list(run.glob('*.json'))+list(run.glob('*.txt')):z.write(p,p.name)
        for p in (run/'data').glob('*.json'):z.write(p,'data/'+p.name)
        for p in (run/'qa').glob('*.json'):z.write(p,'qa/'+p.name)
        for p in (run/'charts').glob('*.png'):z.write(p,'charts/'+p.name)
        for p in (run/'discussion_research').glob('*'):
            if p.is_file():z.write(p,'discussion_research/'+p.name)
    return qa

def generate_company(market,symbol,output,*,snapshot_file=None,overrides=None,sector='non_financial',live=False,skip_pdf=False,discussion_dir=None):
    from .markets import security
    from datetime import datetime
    sec=security(market,symbol);run=Path(output).resolve()/(sec['market']+'_'+sec['symbol']+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));run.mkdir(parents=True,exist_ok=False)
    snapshot=read(snapshot_file) if snapshot_file else collect(market,symbol,run/'data')
    if snapshot['security']['market']!=sec['market'] or snapshot['security']['symbol']!=sec['symbol']:raise ValueError('SNAPSHOT_ENTITY_MISMATCH')
    if snapshot_file:
        data=run/'data';data.mkdir()
        for p in Path(snapshot_file).parent.glob('*.json'):
            if p.is_file() and p.stat().st_size<16000000:(data/p.name).write_bytes(p.read_bytes())
        for source in snapshot['sources']:
            name=source['local_file']
            if not re.fullmatch(r'[a-f0-9]{64}\.json',name):raise ValueError('INVALID_SOURCE_CACHE_NAME')
            original=Path(snapshot_file).parent/'data'/name
            if original.is_file():(data/name).write_bytes(original.read_bytes())
        for source in snapshot['sources']:
            name=source['local_file']
            if not re.fullmatch(r'[a-f0-9]{64}\.json',name):raise ValueError('INVALID_SOURCE_CACHE_NAME')
            original=Path(snapshot_file).parent/'data'/name
            if original.is_file():(data/name).write_bytes(original.read_bytes())
    write(run/'company_snapshot.json',snapshot);result=analyze(snapshot,overrides,sector);write(run/'analysis_results.json',result)
    if discussion_dir:
        import shutil
        session=read(Path(discussion_dir)/'discussion.json')
        if session['snapshot_sha256']!=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest():raise ValueError('DISCUSSION_SNAPSHOT_MISMATCH')
        adopted=[]
        for x in session.get('applied',[]):
            if x['parameter'] in (overrides or {}) and abs(overrides[x['parameter']]-x['value'])<1e-10:adopted.append(x)
        write(run/'assumption_discussion.json',{**session,'adopted':adopted,'final_overrides':overrides,'adoption_rule':'Only explicitly applied suggestion values equal to the final override are identified as adopted.'})
        shutil.copytree(Path(discussion_dir)/'research',run/'discussion_research')
        result['adopted_assumptions']=adopted;write(run/'analysis_results.json',result)
    (run/'analysis_prompt.txt').write_bytes((ROOT/'prompts/multi_market_analysis_en.txt').read_bytes())
    text=narrative(snapshot,result,run,live);build(snapshot,result,text,run)
    if not skip_pdf:
        from .cli import render
        render(run)
    seal_and_package(run)
    return run,result
