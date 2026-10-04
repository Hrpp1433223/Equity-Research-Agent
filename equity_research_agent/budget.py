"""Persistent conservative CNY reservations; failed requests retain their reserve."""
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


class Budget:
    def __init__(self, config=None, *, root=ROOT):
        self.config = config or json.loads((root / 'configs/execution.json').read_text(encoding='utf-8'))
        self.path = root / self.config['ledger']
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prices = self.config['pricing']
        if prices.get('currency') != 'CNY' or min(prices['input_per_million'], prices['output_per_million']) <= 0:
            raise ValueError('UNKNOWN_PRICING: cannot assume zero cost')

    @contextmanager
    def locked(self):
        lock = self.path.with_suffix('.lock')
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError('BUDGET_LEDGER_BUSY: inspect active process before recovery') from None
        try:
            os.close(descriptor)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def read(self):
        if self.path.exists():
            return json.loads(self.path.read_text(encoding='utf-8'))
        # Two previously authorized preflight requests consumed 847 tokens in total.
        # All tokens charged at peak output rate is a conservative opening allowance.
        return {'currency': 'CNY', 'opening_allowance_cny': 0, 'opening_reason': 'New local installation with no prior API usage', 'requests': []}

    def save(self, ledger):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(ledger, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    @staticmethod
    def committed(ledger):
        return ledger['opening_allowance_cny'] + sum(x['committed_cny'] for x in ledger['requests'])

    def reserve(self, payload):
        # Token count cannot exceed serialized UTF-8 bytes for the supported tokenizer;
        # use an additional 4K allowance for provider framing and tool delimiters.
        size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        if size > self.config['max_input_bytes']:
            raise ValueError('INPUT_BUDGET_EXCEEDED')
        output = payload.get('max_tokens')
        if not isinstance(output, int) or not 0 < output <= self.config['max_output_tokens']:
            raise ValueError('OUTPUT_CAP_REQUIRED')
        prices = self.config['pricing']
        estimate = ((size + 4096) * prices['input_per_million'] + output * prices['output_per_million']) / 1e6
        with self.locked():
            ledger = self.read()
            if self.committed(ledger) + estimate > self.config['cumulative_budget_cny']:
                raise ValueError('CUMULATIVE_API_BUDGET_EXCEEDED')
            request_id = uuid.uuid4().hex
            ledger['requests'].append({'id': request_id, 'at_utc': datetime.now(timezone.utc).isoformat(),
                'status': 'reserved', 'reserved_cny': estimate, 'committed_cny': estimate})
            self.save(ledger)
        return request_id

    def settle(self, request_id, usage):
        with self.locked():
            ledger = self.read()
            entry = next(x for x in ledger['requests'] if x['id'] == request_id)
            prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
            if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (prompt, completion)):
                entry['status'] = 'usage_unknown_reservation_retained'
            else:
                prices = self.config['pricing']
                cost = (prompt * prices['input_per_million'] + completion * prices['output_per_million']) / 1e6
                entry.update(status='settled_upper_bound', committed_cny=cost, usage={'prompt_tokens': prompt, 'completion_tokens': completion})
            self.save(ledger)
            return self.committed(ledger)
