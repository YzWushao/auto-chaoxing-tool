"""Tikuhai consumer exact search. Contract: https://search.tikuhai.com/docs."""
import json
import re
import threading
import time

import requests

from api.logger import logger


class TikuHaiAdapter:
    preserve_question_text = True
    skip_answer_validation = True
    ENDPOINT = 'https://search.tikuhai.com/api/open/v1/search/exact'
    TYPES = {'single':'single_choice', 'multiple':'multiple_choice',
             'judgement':'true_false', 'completion':'fill_blank'}
    KINDS = {'single':'single', 'multiple':'multi', 'judgement':'boolean', 'completion':'fill'}

    def __init__(self, config_path=None):
        super().__init__(config_path)
        self.name = '题库海'
        self.lock = threading.Lock()
        self.last_request = 0
        self.cache = {}

    def _init_tiku(self):
        mode = self._conf.get('tikuhai_auth_mode', 'card')
        if mode not in {'card','api'}:
            raise ValueError('题库海认证模式无效')
        credential = 'tikuhai_card' if mode=='card' else 'tikuhai_api_key'
        self.consumer_token = self._conf.get(credential, '').strip()
        self.channel_key = self._conf.get('tikuhai_channel_key', '').strip()
        self.interval = float(self._conf.get('tikuhai_min_interval', '1'))
        if not self.consumer_token:
            self.DISABLE = True
            logger.warning('题库海未配置卡密或个人 API Key，已停用此提供方')

    @staticmethod
    def options(question):
        raw = question.get('options', '')
        values = raw.splitlines() if isinstance(raw, str) else raw if isinstance(raw, list) else []
        return [re.sub(r'^\s*[A-Z][.、:：)）]\s*', '', value) for value in values if isinstance(value,str) and value.strip()]

    def _query(self, question):
        if self.DISABLE:
            return None
        kind = question.get('type')
        if kind not in self.TYPES or not isinstance(question.get('title'),str) or not question['title'].strip():
            return None
        payload = {'stem':question['title'], 'options':self.options(question), 'type':self.TYPES[kind]}
        cache_key = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.lock:
            if cache_key in self.cache:
                return self.cache[cache_key]
            time.sleep(max(0, self.interval-(time.monotonic()-self.last_request)))
            self.last_request = time.monotonic()
            headers = {'X-Consumer-Token':self.consumer_token, 'Accept':'application/json'}
            if self.channel_key:
                headers['X-Channel-Key'] = self.channel_key
            try:
                with requests.Session() as http:
                    http.trust_env = False
                    with http.post(self.ENDPOINT, json=payload, headers=headers, timeout=(5,20),
                                   allow_redirects=False, stream=True) as response:
                        if response.status_code != 200:
                            logger.warning(f'题库海请求失败，HTTP {response.status_code}')
                            return None
                        content = bytearray()
                        for chunk in response.iter_content(65536):
                            content.extend(chunk)
                            if len(content)>1024*1024:
                                logger.warning('题库海响应过大，已停止解析')
                                return None
                        result = json.loads(content)
                answer = self.parse_result(result, kind)
            except (requests.RequestException, ValueError, TypeError, KeyError):
                logger.warning('题库海连接或响应异常，请检查配置和服务状态')
                return None
            if answer is not None:
                if len(self.cache)>=1024:
                    self.cache.clear()
                self.cache[cache_key] = answer
            return answer

    def parse_result(self, result, kind):
        if not isinstance(result,dict) or result.get('success') is not True:
            logger.warning('题库海未确认请求成功，请检查凭证和服务状态')
            return None
        meta, data = result.get('meta') or {}, result.get('data')
        if not isinstance(meta,dict) or meta.get('billing_result')=='exhausted':
            logger.warning('题库海积分不足或扣费未完成，请在题库海核对余额')
            return None
        if data is None:
            logger.info('题库海未命中')
            return None
        if not isinstance(data,dict) or data.get('answer_status')!='complete':
            logger.info('题库海已收录此题，答案尚未补全')
            return None
        items = data.get('items')
        if data.get('asset_type')=='composite' or not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],dict):
            logger.warning('题库海返回题组或不支持的题项结构，已跳过')
            return None
        answer = items[0].get('answer')
        if not isinstance(answer,dict) or answer.get('kind')!=self.KINDS[kind]:
            return None
        values = answer.get('values')
        if not isinstance(values,list) or not values:
            return None
        if kind=='judgement':
            return ('正确' if values[0] else '错误') if len(values)==1 and type(values[0]) is bool else None
        if kind=='single' and len(values)!=1:
            return None
        if any(not isinstance(value,str) or not value.strip() for value in values):
            return None
        return '\n'.join(values)
