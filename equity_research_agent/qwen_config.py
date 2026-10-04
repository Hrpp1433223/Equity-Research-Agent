"""Optional second provider config. No live Qwen authorization is implied."""
import os,re
from dataclasses import dataclass,field
from pathlib import Path
from .llm_config import read_env


@dataclass(frozen=True)
class QwenSettings:
    model:str
    base_url:str
    region:str
    thinking:str
    reasoning_effort:str='high'
    timeout_seconds:int=90
    provider:str='qwen'
    api_key:str=field(default='',repr=False)


def valid_endpoint(endpoint,region):
    old={'beijing':'https://dashscope.aliyuncs.com/compatible-mode/v1','singapore':'https://dashscope-intl.aliyuncs.com/compatible-mode/v1','virginia':'https://dashscope-us.aliyuncs.com/compatible-mode/v1'}
    if endpoint.rstrip('/')==old.get(region):return True
    match=re.fullmatch(r'https://[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1|cn-hongkong|ap-northeast-1)\.maas\.aliyuncs\.com/compatible-mode/v1/?',endpoint)
    return bool(match and match[1]=={'beijing':'cn-beijing','singapore':'ap-southeast-1','hongkong':'cn-hongkong','tokyo':'ap-northeast-1'}.get(region))


def load_qwen_settings(env_file=None,*,environ=None,require_api_key=True):
    values=read_env(Path(env_file or Path(__file__).resolve().parents[1]/'.env'))
    values.update(os.environ if environ is None else environ)
    required=['QWEN_MODEL','QWEN_BASE_URL','QWEN_REGION','QWEN_THINKING']
    if any(not values.get(k,'').strip() for k in required):raise ValueError('QWEN_CONFIGURATION_REQUIRED')
    if not valid_endpoint(values['QWEN_BASE_URL'],values['QWEN_REGION']):raise ValueError('QWEN_ENDPOINT_REGION_MISMATCH')
    if values['QWEN_THINKING'] not in ('enabled','disabled'):raise ValueError('QWEN_THINKING_INVALID')
    key=values.get('QWEN_API_KEY','').strip()
    if require_api_key and not key:raise ValueError('QWEN_API_KEY_REQUIRED')
    return QwenSettings(model=values['QWEN_MODEL'],base_url=values['QWEN_BASE_URL'],region=values['QWEN_REGION'],thinking=values['QWEN_THINKING'],api_key=key)
