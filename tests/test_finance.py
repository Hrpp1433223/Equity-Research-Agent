import unittest
from copy import deepcopy
from datetime import date
from equity_research_agent.finance import value,scenarios,sensitivity

def fixture():
    inp={'currency':'USD','unit':'USD million','share_unit':'million shares','reference_price':100,'opening_nwc':20,'forecasts':[{'year':'2026E','start':'2025-09-30','end':'2026-09-30','revenue':500,'ebit':100,'tax_rate':.2,'da':10,'capex':20,'nwc':25}],'bridge':{'cash':10,'investments':0,'operating_cash_reserve':0,'debt':30,'other_senior_claims':0,'nci':0,'non_operating_assets':0,'shares':10}}
    a={'as_of':'2025-09-30','wacc':.08,'g':.03,'terminal_roic':.3,'terminal_margin':.2,'terminal_tax_rate':.2,'scenarios':{k:{'revenue_growth_shift':r,'ebit_margin_shift':m,'capex_ratio_shift':0} for k,r,m in [('base',0,0),('bull',.02,.02),('bear',-.03,-.03)]}}
    return inp,a

class FinanceTests(unittest.TestCase):
    def test_hand_fixture(self):
        i,a=fixture();v=value(i,a);p=v['periods'][0]
        self.assertEqual(p['nopat'],80);self.assertEqual(p['annual_fcff'],65);self.assertEqual(p['portion'],1)
        self.assertAlmostEqual(v['terminal_fcff'],74.16);self.assertAlmostEqual(v['terminal_value'],1483.2)
        self.assertAlmostEqual(v['ev'],1433.5185185185185);self.assertAlmostEqual(v['equity'],1413.5185185185185)
        self.assertAlmostEqual(v['value_per_share'],141.35185185185185)
    def test_stub_and_year_end(self):
        i,a=fixture();a['as_of']='2026-03-31';v=value(i,a);p=v['periods'][0]
        self.assertAlmostEqual(p['portion'],183/365);self.assertAlmostEqual(p['fcff'],65*183/365);self.assertAlmostEqual(p['tau'],183/365)
        a['as_of']='2026-09-30';v=value(i,a);self.assertEqual(v['periods'][0]['fcff'],0);self.assertEqual(v['periods'][0]['discount_factor'],1)
    def test_loss_has_no_tax_credit(self):
        i,a=fixture();i['forecasts'][0]['ebit']=-100;self.assertEqual(value(i,a)['periods'][0]['nopat'],-100)
    def test_negative_nwc_and_bridge(self):
        i,a=fixture();i['opening_nwc']=-20;i['forecasts'][0]['nwc']=-25;v=value(i,a);self.assertEqual(v['periods'][0]['delta_nwc'],-5);self.assertEqual(v['periods'][0]['annual_fcff'],75)
        i2=deepcopy(i);i2['bridge']['debt']+=10;self.assertAlmostEqual(v['equity']-value(i2,a)['equity'],10)
        i2=deepcopy(i);i2['bridge']['nci']=10;self.assertAlmostEqual(v['equity']-value(i2,a)['equity'],10)
        i2=deepcopy(i);i2['bridge']['shares']=20;self.assertAlmostEqual(value(i2,a)['value_per_share'],v['value_per_share']/2)
    def test_missing_and_invalid(self):
        i,a=fixture()
        for k in ['cash','debt','nci','shares']:
            bad=deepcopy(i);bad['bridge'][k]=None
            with self.assertRaises(ValueError):value(bad,a)
        a['g']=a['wacc']
        with self.assertRaises(ValueError):value(i,a)
        i,a=fixture();i['bridge']['shares']=0
        with self.assertRaises(ValueError):value(i,a)
    def test_currency_units(self):
        i,a=fixture();v=value(i,a);j=deepcopy(i);j['unit']='USD billion';j['share_unit']='thousand shares'
        for p in j['forecasts']:
            for k in ['revenue','ebit','da','capex','nwc']:p[k]/=1000
        j['opening_nwc']/=1000
        for k in j['bridge']:j['bridge'][k]=j['bridge'][k]*1000 if k=='shares' else j['bridge'][k]/1000
        self.assertAlmostEqual(value(j,a)['value_per_share'],v['value_per_share'])
        j['currency']='CNY'
        with self.assertRaises(ValueError):value(j,a)
    def test_scenario_and_sensitivity(self):
        i,a=fixture();s=scenarios(i,a);self.assertGreater(s['bull']['value_per_share'],s['base']['value_per_share']);self.assertLess(s['bear']['value_per_share'],s['base']['value_per_share'])
        grid=sensitivity(i,a);self.assertAlmostEqual(grid['values'][2][2],s['base']['value_per_share'])
        self.assertTrue(all(grid['values'][j][2]>grid['values'][j+1][2] for j in range(4)))
    def test_five_year_and_skipped_period_nwc(self):
        i,a=fixture();p=i['forecasts'][0]
        for year in range(2027,2031):
            q=deepcopy(p);q.update(year=f'{year}E',start=f'{year-1}-09-30',end=f'{year}-09-30',nwc=25+5*(year-2026));i['forecasts'].append(q)
        self.assertEqual(len(value(i,a)['periods']),5)
        a['as_of']='2027-01-01';v=value(i,a);self.assertEqual(v['periods'][0]['delta_nwc'],5)
    def test_repeatable(self):
        i,a=fixture();self.assertEqual(value(i,a),value(i,a));self.assertEqual(i,fixture()[0])
    def test_invalid_operating_inputs_fail_explainably(self):
        for k,bad in [('revenue',0),('revenue',None),('da',None),('tax_rate',float('nan'))]:
            i,a=fixture();i['forecasts'][0][k]=bad
            with self.assertRaisesRegex(ValueError,'FACT|DCF_INPUT'):value(i,a)
        i,a=fixture();i['reference_price']=0
        with self.assertRaisesRegex(ValueError,'reference price'):value(i,a)
    def test_invalid_calendar_and_terminal_tax(self):
        i,a=fixture();i['forecasts'][0]['start']=i['forecasts'][0]['end']
        with self.assertRaisesRegex(ValueError,'end must follow start'):value(i,a)
        i,a=fixture();a['terminal_tax_rate']=None
        with self.assertRaisesRegex(ValueError,'terminal_tax_rate'):value(i,a)
    def test_invalid_sensitivity_cells(self):
        i,a=fixture();a['g']=.079;grid=sensitivity(i,a);self.assertIsNone(grid['values'][0][2]);self.assertIsNone(grid['values'][2][4]);self.assertIsNotNone(grid['values'][2][2])

if __name__=='__main__':unittest.main()
