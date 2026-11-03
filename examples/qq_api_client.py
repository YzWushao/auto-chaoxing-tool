"""Transport adapter for a QQ plugin's authorized model tool calls.

No QQ framework, model provider, server address or credentials are bundled.
Pass tool definitions to the model; keep this client's token in the plugin.
"""
import hashlib
import re
from urllib.parse import quote, urlsplit

import requests


class PluginAPIError(Exception):
    def __init__(self, status, payload, request_id=''):
        self.status, self.payload, self.request_id = status, payload, request_id
        super().__init__(f"HTTP {status}: {payload.get('error','API 请求失败')}")


class ChaoxingAPI:
    def __init__(self, server_url, api_key):
        value=urlsplit(server_url.rstrip('/'))
        if (value.scheme not in {'http','https'} or not value.hostname or value.username or value.password
                or value.path not in ('','/') or value.query or value.fragment):
            raise ValueError('请填写项目根地址，不能带路径、账号或查询参数')
        if value.scheme!='https' and value.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('远程调用需要 HTTPS；localhost 调试可使用 HTTP')
        self.base=server_url.rstrip('/')+'/api/v1'
        self.session=requests.Session();self.session.trust_env=False
        self.session.headers.update({'Authorization':'Bearer '+api_key,'Accept':'application/json'})
        self.operations={};self.tools=[]

    def _request(self, method, path, **kwargs):
        response=self.session.request(method,self.base+path,timeout=(5,45),allow_redirects=False,**kwargs)
        try:payload=response.json()
        except ValueError:raise PluginAPIError(response.status_code,{'error':'服务器未返回 JSON'}) from None
        if not response.ok:raise PluginAPIError(response.status_code,payload,response.headers.get('X-Request-ID',''))
        return payload

    def discover(self):
        spec=self._request('GET','/openapi.json')
        self.tools=self._request('GET','/tools')['tools']
        allowed={t['function']['name'] for t in self.tools}
        self.operations={operation['operationId']:{'method':method.upper(),'path':path}
            for path,methods in spec['paths'].items() for method,operation in methods.items()
            if operation['operationId'] in allowed}
        return self.tools

    def call(self, operation, arguments, request_id=None):
        if not self.operations:self.discover()
        if operation not in self.operations:raise ValueError('当前 API 密钥未授权此工具')
        if not isinstance(arguments,dict) or set(arguments)-{'path','query','body'}:raise ValueError('工具参数格式错误')
        selected=self.operations[operation];method,path=selected['method'],selected['path']
        variables=re.findall(r'{([^}]+)}',path);values=arguments.get('path',{})
        if not isinstance(values,dict) or set(values)!=set(variables):raise ValueError('路径参数不完整')
        for name in variables:
            if not isinstance(values[name],str) or not values[name] or '/' in values[name] or '\\' in values[name] or values[name] in {'.','..'}:
                raise ValueError('路径参数无效')
            path=path.replace('{'+name+'}',quote(values[name],safe=''))
        query=arguments.get('query',{})
        if not isinstance(query,dict):raise ValueError('查询参数需要为对象')
        options={'params':query}
        if method!='GET':
            if not request_id:raise ValueError('写操作必须由插件提供稳定的 request_id，重试沿用原值')
            body=arguments.get('body',{})
            if not isinstance(body,dict):raise ValueError('请求体需要为对象')
            options.update(json=body,headers={'Idempotency-Key':hashlib.sha256(str(request_id).encode()).hexdigest()})
        return self._request(method,path,**options)

    def send_frame(self, run_id, jpeg):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32}',run_id) or not isinstance(jpeg,bytes) or len(jpeg)>768*1024:
            raise ValueError('队列 ID 或 JPEG 格式无效')
        return self._request('POST','/camera-stream/'+run_id+'/frame',data=jpeg,headers={'Content-Type':'image/jpeg'})

    def close(self):
        self.session.close()
