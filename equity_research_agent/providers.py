"""Raw HTTP provider adapters; thought fields stay in request memory only."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class ProviderError(Exception):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def payload(settings, messages, tools, max_tokens):
    result = {'model':settings.model,'messages':messages,'tools':tools,'max_tokens':max_tokens,'stream':False}
    if settings.provider == 'deepseek':
        result['thinking'] = {'type':settings.thinking}
        if settings.thinking == 'enabled': result['reasoning_effort'] = settings.reasoning_effort
    elif settings.provider == 'qwen':
        result['enable_thinking'] = settings.thinking == 'enabled'
        # Alibaba API controls thinking by a token budget, not DeepSeek's effort enum.
        if settings.thinking == 'enabled': result['thinking_budget'] = 4096
    else: raise ProviderError('UNSUPPORTED_PROVIDER')
    return result


class HTTPProvider:
    def __init__(self, settings, budget):
        self.settings, self.budget = settings, budget
        allowed = {'deepseek':{'https://api.deepseek.com','https://api.deepseek.com/v1'},
            'qwen':{'https://dashscope.aliyuncs.com/compatible-mode/v1','https://dashscope-intl.aliyuncs.com/compatible-mode/v1','https://dashscope-us.aliyuncs.com/compatible-mode/v1'}}
        from .qwen_config import valid_endpoint
        approved = valid_endpoint(settings.base_url,getattr(settings,'region',None)) if settings.provider=='qwen' else settings.base_url.rstrip('/') in allowed.get(settings.provider,set())
        if not approved: raise ProviderError('UNAPPROVED_PROVIDER_ENDPOINT')
        if budget.config['provider'] != settings.provider or budget.config['model'] != settings.model:
            raise ProviderError('BUDGET_PROVIDER_MODEL_MISMATCH')

    def request(self, messages, tools):
        body = payload(self.settings,messages,tools,self.budget.config['max_output_tokens'])
        reservation = self.budget.reserve(body)
        request = Request(self.settings.base_url.rstrip('/')+'/chat/completions',data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+self.settings.api_key,'Content-Type':'application/json'},method='POST')
        try:
            with urlopen(request,timeout=min(self.settings.timeout_seconds,self.budget.config['request_timeout_seconds'],getattr(self,'remaining_timeout_seconds',90))) as response:
                data = json.load(response)
        except HTTPError as error:
            raise ProviderError('HTTP_'+str(error.code),error.code in (429,500,502,503,504)) from None
        except (URLError, TimeoutError): raise ProviderError('NETWORK_OR_TIMEOUT',True) from None
        except (ValueError, KeyError): raise ProviderError('INVALID_PROVIDER_RESPONSE') from None
        self.budget.settle(reservation,data.get('usage',{}))
        try:
            choice=data['choices'][0]
            return choice['message'],{'model':data.get('model'),'request_id':data.get('id'),'finish_reason':choice.get('finish_reason'),'usage':data.get('usage',{})}
        except (KeyError, IndexError, TypeError): raise ProviderError('INVALID_PROVIDER_RESPONSE') from None
