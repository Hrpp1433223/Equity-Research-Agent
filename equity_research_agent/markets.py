"""Public multi-market snapshots. Secondary facts never become 'verified' by default."""
import hashlib,json,re,time
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from concurrent.futures import ThreadPoolExecutor

FIELDS={'revenue':['TotalRevenue'],'ebit':['OperatingIncome'],'parent_income':['NetIncome'],'assets':['TotalAssets'],'equity':['StockholdersEquity'],'cash':['CashAndCashEquivalents'],'investments':['OtherShortTermInvestments'],'debt':['TotalDebt'],'shares':['OrdinarySharesNumber'],'cfo':['OperatingCashFlow'],'capex':['CapitalExpenditure'],'da':['DepreciationAndAmortization','DepreciationAmortizationDepletion'],'tax':['TaxProvision'],'pretax':['PretaxIncome'],'receivables':['AccountsReceivable','NetReceivables'],'inventory':['Inventory'],'payables':['AccountsPayable'],'deferred_revenue':['CurrentDeferredRevenue'],'nci':['MinorityInterest'],'cost':['CostOfRevenue']}
HOSTS={'query1.finance.yahoo.com','data.sec.gov','efts.sec.gov','datacenter.eastmoney.com','datacenter-web.eastmoney.com'}

def security(market,symbol):
    market=str(market).upper();symbol=str(symbol).strip().upper()
    if market=='US' and re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,10}',symbol):return {'market':'US','symbol':symbol,'feed_symbol':symbol.replace('.','-'),'expected_quote_currency':'USD'}
    if market=='SH' and re.fullmatch(r'6\d{5}(?:\.SH|\.SS)?',symbol):return {'market':'SH','symbol':symbol[:6],'feed_symbol':symbol[:6]+'.SS','expected_quote_currency':'CNY'}
    if market=='HK' and re.fullmatch(r'\d{1,5}(?:\.HK)?',symbol) and int(symbol.split('.')[0])>0:
        number=int(symbol.split('.')[0]);return {'market':'HK','symbol':str(number).zfill(5),'feed_symbol':str(number).zfill(4)+'.HK','expected_quote_currency':'HKD'}
    raise ValueError('INVALID_MARKET_SYMBOL: US ticker, Shanghai six-digit A-share code, or Hong Kong numeric code required')

class PublicData:
    def __init__(self,cache,offline=False):self.cache=Path(cache);self.cache.mkdir(parents=True,exist_ok=True);self.offline=offline;self.sources=[]
    def get(self,url):
        if urlparse(url).hostname not in HOSTS:raise ValueError('UNAPPROVED_DATA_HOST')
        key=hashlib.sha256(url.encode()).hexdigest();path=self.cache/(key+'.json');meta=self.cache/(key+'.source.json')
        if self.offline:
            if not path.exists() or not meta.exists():raise ValueError('PUBLIC_DATA_CACHE_MISS')
            provenance=json.loads(meta.read_text(encoding='utf-8'))
            if hashlib.sha256(path.read_bytes()).hexdigest()!=provenance['sha256']:raise ValueError('PUBLIC_DATA_CACHE_TAMPERED')
        else:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0 EquityResearchAgent public-data local research','Accept':'application/json'}),timeout=45) as response:
                if urlparse(response.url).hostname not in HOSTS:raise ValueError('UNAPPROVED_DATA_REDIRECT')
                raw=response.read(15_000_001)
            if len(raw)>15_000_000:raise ValueError('PUBLIC_DATA_TOO_LARGE')
            json.loads(raw);path.write_bytes(raw)
            provenance={'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'local_file':path.name,'source_kind':'official_sec' if urlparse(url).hostname in {'data.sec.gov','efts.sec.gov'} else 'secondary_public_feed'}
            meta.write_text(json.dumps(provenance,indent=2),encoding='utf-8')
        self.sources.append(provenance);return json.loads(path.read_text(encoding='utf-8')),provenance

def close_from_chart(data,as_of):
    r=data.get('chart',{}).get('result')
    if not r:raise ValueError('QUOTE_NOT_FOUND')
    r=r[0];quotes=r['indicators']['quote'][0]['close'];rows=[]
    for timestamp,close in zip(r.get('timestamp',[]),quotes):
        stamp=datetime.fromtimestamp(timestamp,timezone.utc).date().isoformat()
        if close is not None and close>0 and stamp<=as_of:rows.append((stamp,float(close)))
    if not rows:raise ValueError('NO_QUOTE_BEFORE_AS_OF')
    return max(rows),r['meta']

def sec_overlay(client,sec,periods,as_of,warnings):
    discovery,src=client.get('https://efts.sec.gov/LATEST/search-index?'+urlencode({'keysTyped':sec['symbol']}))
    matches=[h for h in discovery.get('hits',{}).get('hits',[]) if sec['symbol'] in str(h.get('_source',{}).get('tickers','')).replace(',',' ').split()]
    if len(matches)!=1:raise ValueError('SEC_ENTITY_NOT_UNIQUE')
    cik=int(matches[0]['_id']);raw,source=client.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
    sec.update(cik=cik,official_name=raw['entityName'])
    # Vendor series may round a 52/53-week fiscal end to month end.
    annual_ends=[]
    for tag in ['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet']:
        for item in raw['facts'].get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[]):
            if item.get('form') in ('10-K','10-K/A') and item.get('filed','9999')<=as_of and item.get('start'):
                if 300<=(date.fromisoformat(item['end'])-date.fromisoformat(item['start'])).days<=400:annual_ends.append(item)
    for p in periods:
        matches=[i for i in annual_ends if abs((date.fromisoformat(i['end'])-date.fromisoformat(p['end'])).days)<=10]
        if matches:
            item=max(matches,key=lambda i:i['filed']);p['vendor_period_end']=p['end'];p['end']=item['end'];p['start']=item['start'];p['published_date']=item['filed']
    tags={'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],'ebit':['OperatingIncomeLoss'],'parent_income':['NetIncomeLoss'],'assets':['Assets'],'equity':['StockholdersEquity'],'cash':['CashAndCashEquivalentsAtCarryingValue'],'investments':['ShortTermInvestments','MarketableSecuritiesCurrent'],'shares':['CommonStockSharesOutstanding'],'cfo':['NetCashProvidedByUsedInOperatingActivities'],'capex':['PaymentsToAcquirePropertyPlantAndEquipment','PaymentsToAcquireProductiveAssets'],'da':['DepreciationDepletionAndAmortization','DepreciationDepletionAndAmortizationPropertyPlantAndEquipment'],'tax':['IncomeTaxExpenseBenefit'],'pretax':['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest'],'receivables':['AccountsReceivableNetCurrent'],'inventory':['InventoryNet'],'payables':['AccountsPayableCurrent'],'nci':['MinorityInterest'],'cost':['CostOfRevenue','CostOfGoodsAndServicesSold']}
    instant={'assets','equity','cash','investments','shares','receivables','inventory','payables','nci'}
    for period in periods:
        end=period['end']
        for metric,aliases in tags.items():
            unit='shares' if metric=='shares' else 'USD';candidates=[]
            for priority,tag in enumerate(aliases):
                for item in raw['facts'].get('us-gaap',{}).get(tag,{}).get('units',{}).get(unit,[]):
                    if item.get('end')!=end or item.get('filed','9999')>as_of or item.get('form') not in ('10-K','10-K/A'):continue
                    if metric not in instant:
                        if not item.get('start'):continue
                        duration=(date.fromisoformat(item['end'])-date.fromisoformat(item['start'])).days
                        if not 300<=duration<=400:continue
                    candidates.append((item['filed'],-priority,tag,item))
            if candidates:
                _,_,tag,item=max(candidates,key=lambda z:(z[0],z[1]));val=item['val']
                period['metrics'][metric]=abs(val) if metric=='capex' else val
                period['refs'][metric]={'source_kind':'official_sec','url':source['url'],'tag':tag,'accession':item['accn'],'filed':item['filed'],'period_end':end,'form':item['form']}
                if metric=='revenue':period['start']=item['start'];period['published_date']=item['filed']
    warnings.append('SEC tags are selected by matching period and annual duration. Unmatched fields remain explicitly marked secondary; custom XBRL tags are not guessed.')

def hk_debt(client,sec,periods):
    url='https://datacenter.eastmoney.com/securities/api/data/v1/get?'+urlencode({'reportName':'RPT_HKF10_FN_BALANCE_PC','columns':'ALL','filter':f'(SECUCODE="{sec["symbol"]}.HK")(DATE_TYPE_CODE="001")','pageSize':500,'pageNumber':1,'sortColumns':'REPORT_DATE,STD_ITEM_CODE','sortTypes':'-1,1','source':'F10','client':'PC'})
    raw,src=client.get(url);data=(raw.get('result') or {}).get('data') or []
    for p in periods:
        rows={r['STD_ITEM_CODE']:r for r in data if r['REPORT_DATE'][:10]==p['end']}
        keys=['004011010','004020001','004020018','004011006','004020005']
        values=[rows[k]['AMOUNT'] for k in keys if k in rows and rows[k].get('AMOUNT') is not None]
        if values and p['metrics'].get('debt') is None:
            p['metrics']['debt']=sum(values);p['refs']['debt']={'source_kind':'secondary_public_feed','url':src['url'],'period_end':p['end'],'components':{k:rows[k]['AMOUNT'] for k in keys if k in rows and rows[k].get('AMOUNT') is not None},'definition':'Disclosed standardized borrowing/noncurrent-note/lease rows; other debt categories require filing review.'}

def collect(market,symbol,cache,as_of=None):
    as_of=as_of or date.today().isoformat();date.fromisoformat(as_of)
    if as_of!=date.today().isoformat():raise ValueError('HISTORICAL_AS_OF_REQUIRES_SNAPSHOT: fetch current data then replay its immutable snapshot')
    sec=security(market,symbol);client=PublicData(cache);warnings=[]
    quote_raw,qsrc=client.get('https://query1.finance.yahoo.com/v8/finance/chart/'+sec['feed_symbol']+'?interval=1d&range=1mo')
    (quote_date,close),meta=close_from_chart(quote_raw,as_of)
    if meta.get('instrumentType')!='EQUITY':raise ValueError('EQUITY_SECURITY_REQUIRED')
    if meta.get('currency')!=sec['expected_quote_currency']:raise ValueError('QUOTE_CURRENCY_MISMATCH')
    name=meta.get('longName') or meta.get('shortName') or sec['symbol'];sec['original_source_name']=name
    sec['name']=({'US':'US-listed issuer','SH':'Shanghai-listed issuer','HK':'Hong Kong-listed issuer'}[market]+' '+sec['symbol']) if re.search('[\u3400-\u9fff]',name) else name
    types=','.join('annual'+tag for vals in FIELDS.values() for tag in vals)
    url='https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/'+sec['feed_symbol']+'?'+urlencode({'type':types,'period1':int(datetime(date.today().year-6,1,1,tzinfo=timezone.utc).timestamp()),'period2':int(time.time())})
    raw,src=client.get(url);result=raw.get('timeseries',{}).get('result') or [];by_end={};currencies=set()
    for series in result:
        key=series['meta']['type'][0];tag=key.removeprefix('annual');metric=next((k for k,v in FIELDS.items() if tag in v),None)
        if metric is None:continue
        for item in series.get(key,[]):
            end=item['asOfDate']
            if end>as_of or item.get('reportedValue',{}).get('raw') is None:continue
            ccy=item.get('currencyCode')
            if metric!='shares' and ccy:currencies.add(ccy)
            row=by_end.setdefault(end,{'end':end,'start':str(int(end[:4])-1)+end[4:],'metrics':{},'refs':{},'reporting_currency':ccy,'published_date':None})
            if metric not in row['metrics']:
                value=item['reportedValue']['raw'];row['metrics'][metric]=abs(value) if metric=='capex' else value
                row['refs'][metric]={'source_kind':'secondary_public_feed','url':src['url'],'field':key,'period_end':end,'disclosure_date_verified':False}
    periods=sorted([p for p in by_end.values() if p['metrics'].get('revenue',0)>0],key=lambda p:p['end'])[-4:]
    if len(periods)<2:raise ValueError('INSUFFICIENT_ANNUAL_HISTORY')
    if len(currencies)!=1 or next(iter(currencies)) not in ('USD','CNY','HKD'):raise ValueError('MIXED_OR_UNSUPPORTED_REPORTING_CURRENCY')
    currency=next(iter(currencies));sec['reporting_currency']=currency
    if market=='US':
        try:sec_overlay(client,sec,periods,as_of,warnings)
        except (ValueError,OSError) as e:warnings.append('SEC overlay unavailable: '+type(e).__name__+'; all unmatched financial data remains secondary.')
    if market=='HK':
        try:
            hk_debt(client,sec,periods)
            if any('components' in p['refs'].get('debt',{}) for p in periods):warnings.append('Supplemental HK debt is a standardized borrowing/note/lease component subtotal, not a reconciled total-debt figure. Feed availability and omitted categories can change valuation; inspect the field references and reconcile issuer notes.')
        except (ValueError,OSError):warnings.append('Hong Kong supplemental debt unavailable; valuation requires an explicit debt input.')
    fx=1;fxsrc=None;fxdate=quote_date
    if currency!=meta['currency']:
        pair=currency+meta['currency']+'=X';fx_raw,fxsrc=client.get('https://query1.finance.yahoo.com/v8/finance/chart/'+pair+'?interval=1d&range=1mo')
        (fxdate,fx),_=close_from_chart(fx_raw,quote_date)
    warnings+=['Secondary financial feeds are not independently verified against issuer filings; publication cutoff and restatement scope require review.','Annual shares and bridge balances are frozen at the latest annual end, not assumed to be current. Corporate actions since that date require review.','Trade working capital proxy omits unavailable prepayments, contract assets and customer advances.','A report is a research draft with explicit assumptions, not a brokerage recommendation.']
    snapshot={'version':1,'security':sec,'as_of':as_of,'quote':{'close':close,'currency':meta['currency'],'date':quote_date,'source':qsrc},'fx':{'quote_units_per_reporting_unit':fx,'date':fxdate,'source':fxsrc},'periods':periods,'sources':client.sources,'warnings':warnings,'status':'public_data_research_draft'}
    target=Path(cache)/'company_snapshot.json';target.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8');return snapshot
