"""Bounded public research and auditable DCF discussion; no automatic application."""
import hashlib,ipaddress,json,re,socket,uuid,copy
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse,urlencode
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from xml.etree import ElementTree
from html import unescape
from .company_reports import ROOT,read,write,analyze

DEFAULT_SHIFTS={'bull_growth_shift':.05,'bull_margin_shift':.02,'bull_capex_shift':0.,'bull_nwc_shift':-.01,'bear_growth_shift':-.05,'bear_margin_shift':-.03,'bear_capex_shift':.005,'bear_nwc_shift':.02}
ALLOWED={'wacc','g','terminal_roic','revenue_growth','ebit_margin','tax_rate','da_ratio','capex_ratio','nwc_ratio','reserve'}|set(DEFAULT_SHIFTS)

def public_url(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('PUBLIC_HTTPS_URL_REQUIRED')
    addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('NON_PUBLIC_RESEARCH_HOST')
    return url

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch_public(url):
    public_url(url)
    with build_opener(SafeRedirect()).open(Request(url,headers={'User-Agent':'Mozilla/5.0','Accept':'text/html,application/pdf,application/rss+xml'}),timeout=12) as r:
        raw=r.read(3_000_001);kind=r.headers.get('Content-Type','');final=r.url
    if len(raw)>3_000_000:raise ValueError('RESEARCH_DOCUMENT_TOO_LARGE')
    return raw,kind,final

def extract(raw,kind):
    if 'pdf' in kind or raw.startswith(b'%PDF'):
        import io,pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as pdf:return '\n'.join(p.extract_text() or '' for p in pdf.pages[:12])[:18000],None
    html=raw.decode('utf-8',errors='replace')
    dates=re.findall(r'(?:datePublished|article:published_time|pubdate)[^>\n]{0,100}?([0-9]{4}-[0-9]{2}-[0-9]{2})',html,re.I)
    if not dates:
        dates=re.findall(r'<time\b[^>]*datetime=["\']([0-9]{4}-[0-9]{2}-[0-9]{2})',html,re.I)
    if not dates:
        written=re.search(r"ga_four_event\('PublishDate','View','([^']+)'\)",html)
        if written:
            try:dates=[datetime.strptime(written.group(1),'%B %d, %Y').date().isoformat()]
            except ValueError:pass
    html=re.sub(r'<(script|style|nav|footer)\b[^>]*>.*?</\1>',' ',html,flags=re.S|re.I)
    return re.sub(r'\s+',' ',unescape(re.sub('<[^>]+>',' ',html))).strip()[:18000],dates[0] if dates else None

def research(snapshot,directory,links=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);sec=snapshot['security'];sources=[];errors=[];candidates=[]
    # Recent quarterly observations supplement the frozen annual anchor without replacing it.
    from .markets import PublicData,security
    import time
    symbol=security(sec['market'],sec['symbol'])['feed_symbol']
    quarterly='https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/'+symbol+'?'+urlencode({'type':','.join('quarterly'+k for k in ['TotalRevenue','OperatingIncome','OperatingCashFlow','CapitalExpenditure','TaxProvision','PretaxIncome']),'period1':int(time.time())-730*86400,'period2':int(time.time())})
    try:
        raw,meta=PublicData(directory).get(quarterly);series=raw.get('timeseries',{}).get('result') or []
        compact=[]
        for row in series:
            for key,values in row.items():
                if key.startswith('quarterly') and isinstance(values,list):compact.append({'field':key,'observations':[v for v in values if v.get('asOfDate','9999')<=snapshot['as_of']][-4:]})
        if compact:sources.append({'id':'R1','title':'Recent quarterly financial observations from public secondary feed','url':quarterly,'published_at':None,'retrieved_utc':meta['retrieved_utc'],'status':'secondary_quarterly_feed_publication_unverified','text':json.dumps(compact,ensure_ascii=False),'sha256':meta['sha256'],'local_file':meta['local_file']})
    except Exception as e:errors.append('Recent quarterly feed unavailable: '+type(e).__name__)
    terms=[sec['name']+' '+sec['symbol']+' latest earnings outlook investor relations',sec['name']+' latest revenue margin guidance capital expenditure']
    for term in terms:
        url='https://www.bing.com/search?'+urlencode({'q':term,'format':'rss'})
        try:
            raw,_,_=fetch_public(url);(directory/(hashlib.sha256(raw).hexdigest()+'.rss')).write_bytes(raw)
            for item in ElementTree.fromstring(raw).findall('.//item')[:10]:
                candidates.append({'url':item.findtext('link',''),'title':item.findtext('title',''),'snippet':item.findtext('description',''),'published_at':None,'search_index_date':item.findtext('pubDate')})
        except Exception as e:errors.append('Search unavailable: '+type(e).__name__)
    official={('US','NVDA'):[('https://investor.nvidia.com/news-and-events/press-releases/default.aspx','NVIDIA official earnings releases'),('https://investor.nvidia.com/financial-info/financial-reports-and-sec-filings/default.aspx','NVIDIA official financial reports')],('HK','00700'):[('https://www.tencent.com/en-us/investors/financial-news.html','Tencent official financial news'),('https://www.tencent.com/en-us/investors/financial-reports.html','Tencent official financial reports')],('SH','600519'):[('https://www.moutaichina.com/maotaigf/xxgk/tzzgx/index.html','Kweichow Moutai official investor relations')]}
    if sec['market']=='US' and sec['symbol']=='NVDA':official[('US','NVDA')]=[('https://nvidianews.nvidia.com/news?q=earnings','NVIDIA official earnings archive')]
    seeds=[{'url':u,'title':t,'snippet':'','published_at':None,'official_index':True} for u,t in official.get((sec['market'],sec['symbol']),[])]
    candidates=[{'url':u,'title':'User supplied source','snippet':'','published_at':None,'user_supplied':True} for u in (links or [])]+seeds+[c for c in candidates if re.search(r'earnings|financial|investor|revenue|profit|margin|guidance|outlook|results|财报|业绩|利润|投资者',c['title']+' '+c['snippet'],re.I)]
    seen=set()
    for c in candidates:
        if c['url'] in seen:continue
        seen.add(c['url'])
        if len(sources)>=6:break
        try:
            raw,kind,url=fetch_public(c['url']);body,published=extract(raw,kind);sha=hashlib.sha256(raw).hexdigest();file=sha+('.pdf' if raw.startswith(b'%PDF') else '.html');(directory/file).write_bytes(raw)
            # A date is never invented from the retrieval date.
            published=None if c.get('official_index') else (published or c['published_at']);status='official_index_not_dated_filing' if c.get('official_index') else 'retrieved_public_document';text=body
            if c.get('official_index'):
                # Follow only financial announcement links on the issuer's own domain.
                from urllib.parse import urljoin
                page=raw.decode('utf-8',errors='replace');host=urlparse(url).hostname
                for href,label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',page,re.I|re.S):
                    title=re.sub('<[^>]+>',' ',unescape(label)).strip();target=urljoin(url,href)
                    if urlparse(target).hostname==host and re.search(r'results|earnings|quarter|interim|annual|业绩|季度|年度',title,re.I) and target!=url:
                        candidates.append({'url':target,'title':title[:200],'snippet':'','published_at':None})
        except Exception as e:
            errors.append('Source unavailable: '+c['url']+' ('+type(e).__name__+')')
            if not c['snippet']:continue
            url=c['url'];published=c['published_at'];status='search_snippet_only';text=c['snippet'];sha=hashlib.sha256(text.encode()).hexdigest();file=sha+'.txt';(directory/file).write_text(text,encoding='utf-8')
        if published and re.fullmatch(r'\d{4}-\d{2}-\d{2}',published) and published>snapshot['as_of']:
            errors.append('Excluded source published after valuation cutoff: '+url);continue
        sources.append({'id':'R'+str(len(sources)+1),'title':c['title'],'url':url,'published_at':published,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'status':status,'text':text[:12000],'sha256':sha,'local_file':file})
    out={'sources':sources,'warnings':errors,'queries':terms,'cutoff':snapshot['as_of'],'independently_verified':False};write(directory/'research.json',out);return out

def current_parameters(result):
    if not result['model']:raise ValueError('DCF_UNAVAILABLE_FOR_DISCUSSION')
    p={k:v for k,v in result['driver_parameters'].items() if k in ALLOWED}
    p.update({k:result['assumptions'][k] for k in ['wacc','g','terminal_roic']});p.update(result['driver_parameters'].get('scenario_shifts',DEFAULT_SHIFTS));return p

def validate_response(response,sources,snapshot,overrides,sector):
    import math
    if not isinstance(response,dict) or set(response)!={'reply','suggestions'} or not isinstance(response['reply'],str) or not 0<len(response['reply'])<=7000:raise ValueError('INVALID_ADVISOR_REPLY')
    if re.search('[\u3400-\u9fff]',json.dumps(response,ensure_ascii=False)):raise ValueError('ENGLISH_ADVISOR_RESPONSE_REQUIRED')
    items=response['suggestions'];ids={s['id'] for s in sources};seen=set()
    if not isinstance(items,list) or len(items)>12:raise ValueError('INVALID_ADVISOR_SUGGESTIONS')
    for x in items:
        if not isinstance(x,dict) or set(x)!={'parameter','value','low','high','rationale','counterargument','source_ids','basis'}:raise ValueError('INVALID_ADVISOR_SUGGESTION')
        if x['parameter'] not in ALLOWED or x['parameter'] in seen:raise ValueError('INVALID_ADVISOR_PARAMETER')
        seen.add(x['parameter'])
        if not all(isinstance(x[k],(int,float)) and not isinstance(x[k],bool) and math.isfinite(x[k]) for k in ['value','low','high']) or not x['low']<=x['value']<=x['high']:raise ValueError('INVALID_ADVISOR_RANGE')
        if any(not isinstance(x[k],str) or not 0<len(x[k])<=1000 for k in ['rationale','counterargument']) or x['basis'] not in {'historical','guidance','inference','user_judgment'}:raise ValueError('INVALID_ADVISOR_BASIS')
        if not isinstance(x['source_ids'],list) or any(not isinstance(i,str) or i not in ids for i in x['source_ids']):raise ValueError('INVALID_ADVISOR_SOURCE_REFERENCE')
    proposed={**overrides,**{x['parameter']:x['value'] for x in items}};result=analyze(snapshot,proposed,sector)
    if not result['model']:raise ValueError('DCF_UNAVAILABLE_FOR_DISCUSSION')
    return proposed,result

def discuss(snapshot,overrides,sector,message,links,directory,previous=None,refresh=False,provider=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if not isinstance(message,str) or not 1<=len(message.strip())<=6000:raise ValueError('DISCUSSION_MESSAGE_REQUIRED')
    if not isinstance(links,list) or len(links)>3 or any(not isinstance(u,str) or len(u)>2048 for u in links):raise ValueError('INVALID_RESEARCH_LINKS')
    before=analyze(snapshot,overrides,sector);params=current_parameters(before)
    previous=previous or {'turns':[]}
    if len(previous['turns'])>=8:raise ValueError('DISCUSSION_TURN_LIMIT: start a new discussion')
    evidence=research(snapshot,directory/'research',links) if refresh or not previous.get('research') or links else previous['research']
    context={'issuer':snapshot['security'],'valuation_date':snapshot['as_of'],'annual_periods':snapshot['periods'],'current_parameters':params,'allowed_parameters':sorted(ALLOWED),'user_view':message,'conversation':previous['turns'][-4:],'research':evidence}
    prompt=(ROOT/'prompts/assumption_discussion_en.txt').read_text(encoding='utf-8')
    if provider is None:
        from .llm_config import load_llm_settings
        from .providers import HTTPProvider
        from .budget import Budget
        config=read(ROOT/'configs/execution.json');config['max_output_tokens']=16000
        provider=HTTPProvider(load_llm_settings(),Budget(config))
    # Trim raw financial provenance; the original snapshot stays frozen in the session.
    context['annual_periods']=[{'end':p['end'],'metrics':p['metrics']} for p in snapshot['periods']]
    context=copy.deepcopy(context)
    for s in context['research']['sources']:s['text']=s['text'][:6000]
    msg,meta=provider.request([{'role':'system','content':prompt},{'role':'user','content':json.dumps(context,ensure_ascii=False)}],[])
    if meta.get('finish_reason')!='stop':raise ValueError('INCOMPLETE_ADVISOR_OUTPUT')
    answer=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',msg.get('content','').strip()))
    proposed,after=validate_response(answer,evidence['sources'],snapshot,overrides,sector)
    turn={'user_view':message,'current_overrides':overrides,'response':answer,'provider_metadata':meta,'at_utc':datetime.now(timezone.utc).isoformat()}
    session={'security':snapshot['security'],'snapshot_sha256':hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest(),'research':evidence,'turns':previous['turns']+[turn],'proposal':proposed,'prompt':prompt,'applied':previous.get('applied',[])}
    write(directory/'discussion.json',session)
    values=lambda r:{k:v['quote_value_per_share'] for k,v in r['model'].items()}
    return session,{'reply':answer['reply'],'suggestions':answer['suggestions'],'current_parameters':params,'before':values(before),'after':values(after),'currency':snapshot['quote']['currency'],'sources':[{k:v for k,v in s.items() if k!='text'} for s in evidence['sources']],'research_warnings':evidence['warnings'],'turn_count':len(session['turns'])}
