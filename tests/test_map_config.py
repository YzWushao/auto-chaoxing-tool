import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from server.config import ROOT, MASK
from server.map_config import validate_map_settings
from tests.test_location_presets import SCHOOL


KEY='a'*32
CODE='b'*32


def configure(browser,provider='osm'):
    browser.admin_login()
    response=browser.send('/map/settings',{'provider':provider,'key':KEY,'security_code':CODE},'PUT')
    assert response.status_code == 200,response.json
    return response


def test_free_default_works_without_credentials(browser):
    browser.admin_login()
    value=browser.get('/bootstrap').json['map_settings']
    assert value == {'provider':'osm','key':'','security_code':'','configured':False}
    assert browser.get('/map/runtime').status_code == 400
    assert browser.send('/map/settings',{'provider':'amap'},'PUT').status_code == 400
    assert browser.send('/map/settings',{'provider':'osm'},'PUT').status_code == 200


def test_keys_encrypted_masked_and_not_exported(browser,app):
    result=configure(browser).json['map_settings']
    assert result['key'] == MASK and result['security_code'] == MASK
    browser.send('/location-presets',{'config':SCHOOL})
    original=browser.get('/bootstrap').json['location_presets']
    switched=browser.send('/map/settings',{'provider':'amap','key':MASK,'security_code':MASK},'PUT')
    assert switched.status_code == 200
    assert browser.get('/bootstrap').json['location_presets'] == original
    runtime=browser.get('/map/runtime').json
    assert runtime['key'] == KEY
    assert 'security_code' not in runtime and 'jscode' not in json.dumps(runtime)
    assert runtime['service_host'] == 'http://localhost/_AMapService'
    assert CODE not in json.dumps(browser.get('/bootstrap').json)
    assert CODE not in json.dumps(browser.get('/location-presets/export').json)
    assert KEY.encode() not in app.extensions['store'].path.read_bytes()
    assert CODE.encode() not in app.extensions['store'].path.read_bytes()
    assert browser.send('/map/settings',{'provider':'osm','key':'','security_code':''},'PUT').json['map_settings']['configured'] is False


@pytest.mark.parametrize('data',[{'provider':'baidu'}, {'key':'bad'}, {'key':KEY}, {'security_code':CODE}, {'provider':None}, {'url':'https://example.invalid'}])
def test_bad_map_configuration_rejected(data):
    with pytest.raises(ValueError):
        validate_map_settings(data,{'provider':'osm','key':'','security_code':''})


def test_amap_routes_require_admin_and_csrf(browser):
    for path in ['/map/amap','/_AMapService/v3/place/text']:
        assert browser.client.get(path).status_code == 401
    assert browser.get('/map/settings').status_code == 401
    browser.admin_login()
    assert browser.client.put('/api/map/settings',json={'provider':'osm'}).status_code == 403


def test_proxy_allowlist_credentials_and_origin(browser,monkeypatch):
    configure(browser)
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(status_code=200,content=b'callback({"status":"1","pois":[]})')
    monkeypatch.setattr('server.map_config.requests.get',get)
    response=browser.client.get('/_AMapService/v3/place/text?key=attacker-key&jscode=attacker-code&keywords=school&callback=callback')
    assert response.status_code == 200
    url,kwargs=calls[0]
    assert url == 'https://restapi.amap.com/v3/place/text'
    assert kwargs['params']['key'] == KEY and kwargs['params']['jscode'] == CODE
    assert kwargs['headers']['Referer'] == 'http://localhost/'
    assert 'cookies' not in kwargs and 'auth' not in kwargs and kwargs['allow_redirects'] is False
    assert response.mimetype == 'application/javascript'
    assert browser.client.get('/_AMapService/v3/place/text',headers={'Origin':'https://other.invalid'}).status_code == 403
    assert browser.client.get('/_AMapService/arbitrary/url').status_code == 404
    assert browser.client.get('/_AMapService/v3/place/text?callback=alert(1)').status_code == 400
    assert len(calls) == 1


def test_parent_csp_unchanged_and_sdk_permissions_scoped_to_frame(browser):
    browser.admin_login()
    parent=browser.client.get('/').headers['Content-Security-Policy']
    assert "script-src 'self';" in parent and "style-src 'self';" in parent
    assert 'unsafe-inline' not in parent and 'webapi.amap.com' not in parent
    assert "frame-src 'self'" in parent
    child=browser.client.get('/map/amap')
    assert child.status_code == 200 and child.headers['X-Frame-Options']=='SAMEORIGIN'
    assert 'https://webapi.amap.com' in child.headers['Content-Security-Policy']
    assert "frame-ancestors 'self'" in child.headers['Content-Security-Policy']
    assert child.headers['Cache-Control']=='no-store'


def test_amap_bridge_preserves_coordinates_origin_and_disposal():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for bridge tests')
    program=r'''
const assert=require('node:assert/strict'),helper=require('./web/sign-map.js');
let receive,removed=0,frame,selected=[],posted=[];
global.location={origin:'http://localhost'};
global.window={addEventListener:(name,fn)=>receive=fn,removeEventListener:()=>removed++};
global.document={createElement:()=>frame={contentWindow:{postMessage:data=>posted.push(data)},remove(){}}};
const driver=require('./web/amap-picker.js');
const picker=driver.mount({replaceChildren(){}},{convert:helper,onSelect:p=>selected.push(p),onStatus(){}});
const event=data=>({origin:location.origin,source:frame.contentWindow,data:{channel:'auto-chaoxing-amap',...data}});
picker.center({lng:116.404,lat:39.915});
assert.equal(posted.length,0); receive(event({type:'ready'}));
assert.equal(posted[0].type,'center'); assert.ok(Math.abs(posted[0].point.lng-116.410244499)<1e-8);
receive({...event({type:'selected',point:{lng:116.41024449916938,lat:39.91640428150164}}),origin:'https://evil.invalid'});
assert.equal(selected.length,0);
receive(event({type:'selected',point:{lng:116.41024449916938,lat:39.91640428150164}}));
assert.ok(Math.abs(selected[0].lng-116.404)<1e-9);
(async()=>{
 const promise=picker.search('school'); await new Promise(r=>setImmediate(r));
 const request=posted.at(-1); assert.equal(request.type,'search');
 receive(event({type:'results',id:request.id,results:[{name:'test',point:{lng:116.41024449916938,lat:39.91640428150164}}]}));
 const result=await promise; assert.ok(Math.abs(result[0].lng-116.404)<1e-9);
 const late=picker.search('late');await new Promise(r=>setImmediate(r));picker.destroy();picker.destroy();
 await assert.rejects(late,{name:'AbortError'});assert.equal(removed,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    subprocess.run([node,'-e',program],cwd=ROOT,text=True,capture_output=True,check=True,timeout=15)


def test_official_sdk_adapter_with_offline_fake_sdk():
    node=shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for SDK adapter tests')
    program=r'''
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
let map,marker,events={},messages=[],scriptURL='';
const parent={postMessage:data=>messages.push(data)}, loading={textContent:'loading',hidden:false};
class LngLat {constructor(lng,lat){this.lng=lng;this.lat=lat;}getLng(){return this.lng;}getLat(){return this.lat;}}
class Map {constructor(id,opts){this.opts=opts;this.events={};this.center=new LngLat(...opts.center);map=this;}addControl(){}on(n,fn){this.events[n]=fn;}getCenter(){return this.center;}setZoomAndCenter(z,p){this.center=p;}destroy(){this.destroyed=true;}}
class Marker {constructor(opts){this.p=opts.position;this.events={};marker=this;}on(n,fn){this.events[n]=fn;}setPosition(p){this.p=p;}getPosition(){return this.p;}}
const context={console,Promise,setTimeout,clearTimeout,parent,location:{origin:'http://localhost'},
  fetch:async()=>({ok:true,json:async()=>({key:'fake-key',service_host:'http://localhost/_AMapService'})}),
  AMap:{Map,Marker,LngLat,Scale:class{},ToolBar:class{},Circle:class{setMap(){}},PlaceSearch:class{search(q,fn){fn('complete',{poiList:{pois:[{name:'School',location:new LngLat(116.4,39.9)}]}});}}},
  document:{querySelector:()=>loading,createElement:()=>({remove(){}}),head:{append(script){scriptURL=script.src;context.__autoChaoxingAMapReady();}}},
  addEventListener:(n,fn)=>events[n]=fn};
context.window=context;
vm.createContext(context);vm.runInContext(fs.readFileSync('web/amap-frame.js','utf8'),context);
(async()=>{
 await new Promise(r=>setImmediate(r));
 assert.ok(scriptURL.startsWith('https://webapi.amap.com/maps?v=2.0&key='));assert.ok(!scriptURL.includes('securityJsCode'));
 assert.equal(context._AMapSecurityConfig.serviceHost,'http://localhost/_AMapService');assert.equal(map.opts.jogEnable,false);
 assert.equal(messages.at(-1).type,'ready'); map.events.complete(); assert.equal(loading.hidden,true);
 const send=data=>events.message({origin:'http://localhost',source:parent,data:{channel:'auto-chaoxing-amap',...data}});
 send({type:'center',point:{lng:116.4,lat:39.9},zoom:17});assert.equal(messages.at(-1).point.lng,116.4);
 map.center=new LngLat(120,30);map.events.dragend();assert.equal(messages.at(-1).point.lng,120);
 marker.p=new LngLat(121,31);marker.events.dragend();assert.equal(messages.at(-1).point.lng,121);
 send({type:'search',query:'school',id:9});assert.equal(messages.at(-1).id,9);assert.equal(messages.at(-1).results[0].point.lat,39.9);
 events.pagehide();assert.equal(map.destroyed,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    subprocess.run([node,'-e',program],cwd=ROOT,text=True,capture_output=True,check=True,timeout=15)
