import json
import tempfile
import unittest
from pathlib import Path
from equity_research_agent.budget import Budget


class BudgetTests(unittest.TestCase):
    def config(self):
        return {'ledger':'ledger.json','pricing':{'currency':'CNY','input_per_million':2,'output_per_million':8},'max_input_bytes':1000,'max_output_tokens':100,'cumulative_budget_cny':1}

    def test_persistent_reservation_unknown_usage_and_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            config=self.config(); budget=Budget(config, root=Path(directory))
            ident=budget.reserve({'max_tokens':100,'messages':[]})
            total=budget.settle(ident,{})
            self.assertGreater(total,0)
            config['cumulative_budget_cny']=total
            with self.assertRaisesRegex(ValueError,'CUMULATIVE_API'): budget.reserve({'max_tokens':100})
            config['cumulative_budget_cny']=1
            total=budget.settle(ident,{'prompt_tokens':10,'completion_tokens':10})
            self.assertAlmostEqual(total,.0001)
            self.assertEqual(Budget(config,root=Path(directory)).committed(budget.read()),total)

    def test_no_uncapped_requests_or_unknown_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            config=self.config(); budget=Budget(config,root=Path(directory))
            with self.assertRaisesRegex(ValueError,'OUTPUT_CAP'): budget.reserve({})
            config['pricing']['output_per_million']=0
            with self.assertRaisesRegex(ValueError,'UNKNOWN_PRICING'): Budget(config,root=Path(directory))
