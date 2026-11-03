"""Versioned aliases share the UI handlers; discoverable, scoped plugin contracts."""
import copy
import re

from flask import g, jsonify

from .config import API_DEFAULTS, STUDY_DEFAULTS, VERSION
from .api_access import SCOPES


def obj(properties=None, required=(), extra=False):
    return {'type':'object','properties':properties or {},'required':list(required),'additionalProperties':extra}


TEXT={'type':'string'}
BOOL={'type':'boolean'}
SOURCE={'type':'string','enum':['course'],'default':'course'}
LOCATION=obj({'school':TEXT,'name':TEXT},['school','name'])
API=obj({k:{'type':'string'} for k in API_DEFAULTS})
STUDY=obj({k:{'type':'boolean' if type(v) is bool else 'integer' if type(v) is int else 'number' if type(v) is float else 'string'} for k,v in STUDY_DEFAULTS.items()})
CONFIG=obj({'course_keys':{'type':'array','items':TEXT},'inherit_api':BOOL,'api':API,'study':STUDY})
POINT=obj({'name':TEXT,'longitude':{'type':'number'},'latitude':{'type':'number'},'coordinate_system':{'enum':['wgs84','gcj02','bd09']}},['name','longitude','latitude','coordinate_system'])
IMPORTED_POINT=obj({**POINT['properties'],'address':{'type':'string','deprecated':True,'description':'兼容旧 JSON；点位说明不保存，上报使用学校位置'}},['name','longitude','latitude'])
SCHOOL=obj({'version':{'const':1},'school':TEXT,'address':TEXT,'coordinate_system':{'enum':['wgs84','gcj02','bd09']},'points':{'type':'array','items':IMPORTED_POINT}},['school','coordinate_system','points'])
PRESET_IMPORT={'oneOf':[SCHOOL,obj({'version':{'const':1},'schools':{'type':'array','items':SCHOOL}},['schools'])]}
NAPCAT=obj({'enabled':BOOL,'ws_url':TEXT,'token':TEXT,'allowed_qqs':{'type':'array','items':TEXT},'scan_base_url':TEXT,
            'intent_enabled':BOOL,'intent_api_url':TEXT,'intent_api_key':TEXT,'intent_model':TEXT})
MAP=obj({'provider':{'enum':['osm','amap']},'key':TEXT,'security_code':TEXT,'free_reverse_enabled':BOOL})

# All writes are explicitly classified. Registering a new UI write without a
# reviewed API contract fails at startup instead of silently granting it.
WRITES={
 'admin_credentials':('admin:write','修改管理员凭据并撤销全部登录及 API 密钥',obj({'username':TEXT,'current_password':TEXT,'new_password':TEXT},['current_password'])),
 'login_password':('accounts:write','通过手机号和密码添加或重新登录超星账户',obj({'phone':TEXT,'password':TEXT,'account_id':TEXT},['phone','password'])),
 'qr_create':('accounts:write','生成超星登录二维码，返回图像与轮询 ID',obj()),
 'qr_poll':('accounts:write','轮询本 API 密钥创建的登录二维码',obj({'account_id':TEXT})),
 'qr_cancel':('accounts:write','取消本 API 密钥的登录二维码',obj()),
 'camera_stream_start':('sign:write','开始指定用户的连续扫码队列',obj({'account_ids':{'type':'array','items':TEXT,'minItems':1,'maxItems':200},'input':{'enum':['jpeg','native'],'default':'jpeg'},'location':LOCATION},['account_ids'])),
 'camera_stream_frame':('sign:write','上传 JPEG，服务器识别并执行扫码队列',None),
 'camera_stream_native':('sign:write','向 native 扫码队列提交设备已识别的二维码',obj({'qr':TEXT},['qr'])),
 'camera_stream_stop':('sign:write','停止本 API 密钥创建的扫码队列',obj()),
 'device_global':('settings:write','设置统一设备码，可选择应用到已有账户',obj({'code':TEXT,'apply_existing':BOOL},['code','apply_existing'])),
 'device_account':('settings:write','绑定指定账户设备码或生成固定随机码',obj({'action':{'enum':['random','bind']},'code':TEXT,'source':{'enum':['manual','browser','imported']}},['action'])),
 'preferences_save':('settings:write','修改用户称呼及扫码并发、识别间隔',obj({'account_label':{'enum':['phone_tail','surname_mask','full_name','masked_surname','surname_tail']},'camera_concurrency':{'type':'integer','minimum':1,'maximum':5},'camera_scan_interval':{'type':'number','minimum':.05,'maximum':10}})),
 'napcat_save':('settings:write','保存 NapCat 连接与模型配置并应用',NAPCAT),
 'napcat_test':('settings:write','测试 NapCat 登录信息连接，不发 QQ 消息',NAPCAT),
 'napcat_intent_test':('settings:write','测试意图模型连接，可能产生 API 费用',NAPCAT),
 'map_settings_save':('settings:write','保存地图服务设置',MAP),
 'search_map':('read','搜索地图位置',obj({'query':TEXT},['query'])),
 'reverse_map':('read','查询选点地址，需管理员已开启免费地址查询',obj({'longitude':{'type':'number'},'latitude':{'type':'number'}},['longitude','latitude'])),
 'location_presets_import':('settings:write','导入学校和预设点位 JSON，可合并或替换',obj({'config':PRESET_IMPORT,'replace':BOOL},['config'])),
 'location_school_save':('settings:write','新建或编辑学校及统一上报位置',obj({'name':TEXT,'original':TEXT,'address':TEXT},['name'])),
 'location_school_delete':('settings:write','删除学校及其全部点位',obj({'name':TEXT},['name'])),
 'location_point_save':('settings:write','新增或编辑学校下的点位',obj({'school':TEXT,'point':POINT,'original':LOCATION},['school','point'])),
 'location_point_delete':('settings:write','删除学校下的点位',LOCATION),
 'settings_save':('settings:write','保存全局刷课题库 API 配置',obj({'api':API},['api'])),
 'account_config':('study:write','保存用户目标课程、学习参数和独立题库 API',CONFIG),
 'account_remove':('accounts:write','删除超星账户（须先停止其刷课任务）',obj()),
 'sign':('sign:write','提交已刷新的签到或签退活动；选用 location_preset 时服务器读取并转换点位坐标和学校位置',obj({'activity_id':TEXT,'source':SOURCE,'qr':TEXT,'kind':{'enum':['normal','photo','qr','gesture','location','code']},'object_id':TEXT,'code':TEXT,'longitude':{'type':['number','string']},'latitude':{'type':['number','string']},'address':TEXT,'location_preset':LOCATION,'verification_id':TEXT,'face_id':TEXT},['activity_id'])),
 'camera_submit':('sign:write','为指定用户提交已解码的签到二维码',obj({'qr':TEXT,'verification_id':TEXT,'face_id':TEXT,'location':LOCATION},['qr'])),
 'verification_check':('sign:write','检查、刷新或取消平台滑块验证；check 时 x 为拼图横坐标',obj({'action':{'enum':['check','refresh','cancel']},'x':{'type':'number'}},['action'])),
 'activity_related':('sign:write','选择签到活动关联的签到(in)或签退(out)阶段',obj({'source':SOURCE,'relation':{'enum':['in','out']}},['relation'])),
 'activity_confirm':('sign:write','核对平台已完成状态',obj({'source':SOURCE})),
 'face_upload':('sign:write','提交用户明确同意的本人照片，不代替官方活体校验',obj({'activity_id':TEXT,'source':SOURCE,'image':TEXT,'consent':{'const':True}},['activity_id','image','consent'])),
 'face_cancel':('sign:write','取消临时本人照片',obj()),
 'study':('study:write','按该账户已保存目标启动刷课后台任务',obj()),
 'stop':('study:write','停止指定刷课任务',obj()),
 'answer':('study:write','向等待输入的刷课任务提交内容',obj({'answer':TEXT},['answer'])),
 'scan_entry':('sign:write','为已授权 QQ 创建固定扫码地址与8位数字验证码（不发送消息）',obj({'qq':TEXT},['qq'])),
}

READS={
 'health':'检查服务版本和健康状态','bootstrap':'读取控制台初始化数据（凭据脱敏）',
 'accounts_list':'列出全部托管账户和全局显示昵称','account_detail':'读取指定账户及配置（凭据脱敏）',
 'preferences_read':'读取全局显示及扫码参数','settings_read':'读取脱敏的全局题库 API 配置',
 'napcat_settings':'读取脱敏 NapCat 配置和连接状态','devices':'读取设备码绑定列表与统一设备码',
 'camera_stream_status':'读取本 API 密钥创建的扫码队列和结果','map_settings':'读取脱敏地图设置',
 'map_runtime':'读取当前地图 JS 运行参数','location_presets':'读取学校位置和全部点位',
 'location_presets_export':'导出学校及点位 JSON','courses':'实时读取用户课程列表',
 'activities':'刷新用户课程签到活动，群聊来源不支持','activity_requirements':'查询活动要求和签到/签退阶段',
 'jobs':'读取任务、动态及账户状态','logs':'分页读取指定任务日志',
}


def install_external_api(app, access):
    for rule in list(app.url_map.iter_rules()):
        if not rule.rule.startswith('/api/') or rule.rule.startswith('/api/access') or rule.endpoint in {'current_session','admin_login','logout'}:
            continue
        for method in sorted(rule.methods-{'HEAD','OPTIONS'}):
            name=rule.endpoint
            if method=='GET':
                if name not in READS:raise RuntimeError('Missing API read contract: '+name)
                scope='settings:write' if name=='map_runtime' else 'sign:write' if name=='camera_stream_status' else 'read'
                summary,schema=READS[name],None
            else:
                if name not in WRITES:raise RuntimeError('Missing API write contract: '+name)
                scope,summary,schema=WRITES[name]
            access.operations[(name,method)]={'operationId':name,'path':re.sub(r'<(?:[^:>]+:)?([^>]+)>',r'{\1}',rule.rule[4:]),
                'method':method,'scope':scope,'summary':summary,'body':schema}
            app.add_url_rule('/api/v1'+rule.rule[4:],endpoint='external.'+name,view_func=app.view_functions[name],methods=[method])

    def me():
        key=g.api_key
        return jsonify(admin={'username':g.admin['username']},key={k:key[k] for k in ('id','name','scopes','expires_at','rate_limit')})

    def spec():return jsonify(openapi_document(access,g.api_key['scopes']))
    def tools():return jsonify(tools=model_tools(access,g.api_key['scopes']))
    for name,path,handler,summary in [('api_me','/me',me,'检查 API 密钥权限及有效期'),
            ('api_openapi','/openapi.json',spec,'读取当前密钥可用的 OpenAPI 文档'),
            ('api_tools','/tools',tools,'读取当前密钥可用的模型工具定义')]:
        access.operations[(name,'GET')]={'operationId':name,'path':path,'method':'GET','scope':None,'summary':summary,'body':None}
        app.add_url_rule('/api/v1'+path,endpoint='external.'+name,view_func=handler,methods=['GET'])


def query_schema(name):
    if name in {'activities','activity_requirements'}:return obj({'source':SOURCE})
    if name=='logs':return obj({'after':{'type':'integer','minimum':0,'default':0}})
    return obj()


def openapi_document(access, scopes=None):
    paths={}
    for operation in access.operations.values():
        if scopes is not None and operation['scope'] and operation['scope'] not in scopes:continue
        name,path,method=operation['operationId'],operation['path'],operation['method']
        parameters=[{'name':p,'in':'path','required':True,'schema':TEXT} for p in re.findall(r'{([^}]+)}',path)]
        parameters += [{'name':k,'in':'query','required':False,'schema':v} for k,v in query_schema(name)['properties'].items()]
        if method!='GET' and name!='camera_stream_frame':
            parameters.append({'name':'Idempotency-Key','in':'header','required':False,'schema':{'type':'string','maxLength':128},'description':'同一写操作重试沿用此 ID，24 小时去重；409 时先查询状态。'})
        item={'operationId':name,'summary':operation['summary'],'tags':[operation['scope'] or 'API'],
              'x-required-scope':operation['scope'],'parameters':parameters,
              'responses':{'200':{'description':'操作结果，沿用网页接口的 JSON 返回结构'},'202':{'description':'任务或画面已接收'},
                           '400':{'description':'参数错误'},'401':{'description':'密钥无效或API关闭'},'403':{'description':'权限不足'},
                           '404':{'description':'记录不存在或不属于当前管理范围'},'409':{'description':'需要平台验证或请求重复/执行中'},
                           '422':{'description':'平台要求额外处理'},'429':{'description':'请求限流'},'502':{'description':'平台请求未确认'}}}
        if method!='GET':
            content=({'image/jpeg':{'schema':{'type':'string','format':'binary'}}} if name=='camera_stream_frame'
                     else {'application/json':{'schema':operation['body']}})
            item['requestBody']={'required':True,'content':content}
        for status,response in item['responses'].items():
            response['content']={'application/json':{'schema':{'type':'object','additionalProperties':True}}}
            if int(status)>=400:
                response['content']['application/json']['schema']=obj({'error':TEXT,'code':TEXT,'verification':{'type':'object','additionalProperties':True}},['error'],extra=True)
        paths.setdefault(path,{})[method.lower()]=item
    return {'openapi':'3.1.0','info':{'title':'Auto Chaoxing Plugin API','version':VERSION,
        'description':'独立 Bearer 密钥。权限、用户归属、平台验证与网页相同；密钥不能交给模型。密钥管理与管理员网页登录只在控制台进行。'},
        'servers':[{'url':'/api/v1'}],'security':[{'bearerAuth':[]}],
        'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer','bearerFormat':'API Key','description':'设置 → 开放 API 中创建的 act_ 开头密钥'}}},
        'x-scopes':SCOPES,'paths':paths}


def model_tools(access, scopes=None):
    result=[]
    for operation in access.operations.values():
        if scopes is not None and operation['scope'] and operation['scope'] not in scopes:continue
        name=operation['operationId']
        if name in {'camera_stream_frame','api_tools','api_openapi'}:continue
        path_vars=re.findall(r'{([^}]+)}',operation['path'])
        properties={};required=[]
        if path_vars:
            properties['path']=obj({v:TEXT for v in path_vars},path_vars);required.append('path')
        query=query_schema(name)
        if query['properties']:properties['query']=query
        if operation['body'] is not None:
            properties['body']=copy.deepcopy(operation['body']);required.append('body')
        result.append({'type':'function','function':{'name':name,'description':operation['summary'],
                                                    'parameters':obj(properties,required)}})
    return result
