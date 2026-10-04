"""Local V2 settings loader; imports never read credentials or call an API."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def read_env(path):
    """Literal KEY=value subset: no shell execution or variable interpolation."""
    values = {}
    if not path.is_file():
        return values
    for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Invalid .env assignment at line {line_number}')
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key.isidentifier():
            raise ValueError(f'Invalid .env variable name at line {line_number}')
        if value.startswith(('"', "'")):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ValueError(f'Unclosed .env quote at line {line_number}')
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    thinking: str
    reasoning_effort: str
    timeout_seconds: int
    api_key: str = field(repr=False)

    def request_options(self):
        options = {'model': self.model, 'extra_body': {'thinking': {'type': self.thinking}}}
        if self.thinking == 'enabled':
            options['reasoning_effort'] = self.reasoning_effort
        return options


def load_llm_settings(config_path=None, *, require_api_key=True, environ=None):
    """Explicit process overrides take precedence; all defaults live in .env."""
    config_path = Path(config_path or Path(__file__).resolve().parents[1] / 'configs/llm.yaml')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    values = read_env((config_path.parent / config['env_file']).resolve())
    values.update(os.environ if environ is None else environ)
    settings = {name: values.get(variable, '').strip() for name, variable in config['variables'].items()}
    for name in ['model', 'base_url', 'thinking', 'reasoning_effort', 'timeout_seconds']:
        if not settings[name]:
            raise ValueError('Missing LLM setting: ' + config['variables'][name])
    if settings['thinking'] not in ('enabled', 'disabled'):
        raise ValueError('DEEPSEEK_THINKING must be enabled or disabled')
    if settings['reasoning_effort'] not in ('low', 'high', 'max'):
        raise ValueError('DEEPSEEK_REASONING_EFFORT must be low, high or max')
    try:
        timeout = int(settings['timeout_seconds'])
    except ValueError:
        raise ValueError('DEEPSEEK_TIMEOUT_SECONDS must be a positive integer') from None
    if timeout <= 0:
        raise ValueError('DEEPSEEK_TIMEOUT_SECONDS must be a positive integer')
    if require_api_key and not settings['api_key']:
        raise ValueError('DEEPSEEK_API_KEY is not configured; enter it locally in .env')
    return LLMSettings(provider=config['provider'], **{**settings, 'timeout_seconds': timeout})
