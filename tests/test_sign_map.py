"""Offline coordinate/picker tests. No real geolocation or attendance requests."""
import hashlib
import json
import shutil
import subprocess

import pytest

from server.config import ROOT
from server.chaoxing import ChaoxingClient
from tests.test_platform import response


def javascript(program):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for JavaScript regression tests')
    result = subprocess.run([node, '-e', "const assert=require('node:assert/strict'); const helper=require('./web/sign-map.js');\n" + program],
                            cwd=ROOT, text=True, capture_output=True, check=True, timeout=15)
    return json.loads(result.stdout or 'null')


def test_coordinate_reference_vectors_and_six_decimals():
    result = javascript("process.stdout.write(JSON.stringify(['wgs84','gcj02','bd09'].map(s=>helper.formatted({lng:116.404,lat:39.915},s))))")
    assert result[0] == {'longitude': '116.404000', 'latitude': '39.915000'}
    assert result[1] == {'longitude': '116.410244', 'latitude': '39.916404'}
    assert result[2] == {'longitude': '116.416627', 'latitude': '39.922700'}


@pytest.mark.parametrize('system', ['wgs84', 'gcj02', 'bd09'])
def test_coordinates_round_trip_without_map_offset(system):
    result = javascript(f"const p={{lng:121.4737,lat:31.2304}}; process.stdout.write(JSON.stringify(helper.toWGS84(helper.fromWGS84(p,'{system}'),'{system}')))")
    assert result['lng'] == pytest.approx(121.4737, abs=1e-9, rel=0)
    assert result['lat'] == pytest.approx(31.2304, abs=1e-9, rel=0)


@pytest.mark.parametrize('values', [[None, 1], ['', ''], [' ', 1], ['NaN', 2], [181, 1], [1, -91], ['Infinity', 1]])
def test_invalid_coordinates_are_not_silently_coerced(values):
    javascript(f"assert.throws(()=>helper.point(...{json.dumps(values)}));")


def test_coordinate_order_and_outside_mainland_wgs84():
    javascript("assert.deepEqual(helper.point('121.4','31.2'),{lng:121.4,lat:31.2}); assert.deepEqual(helper.fromWGS84({lng:-73.9,lat:40.7},'gcj02'),{lng:-73.9,lat:40.7}); assert.throws(()=>helper.toWGS84({lng:1,lat:1},'unknown'));")


def test_picker_click_drag_disposal_and_late_geolocation():
    javascript(r'''
let options, tileOptions, lastMarker, lastCircle, removed=0, chosen=[], messages=[];
global.requestAnimationFrame=()=>1; global.cancelAnimationFrame=()=>{};
class Layer {
  constructor(value){this.value=value;this.events={};}
  addTo(){return this;} on(name,fn){this.events[name]=fn;return this;}
  setLatLng(value){this.value=value;return this;}
  getLatLng(){return {lat:this.value[0],lng:this.value[1]};}
  remove(){}
}
const center={lat:39.915,lng:116.404,wrap(){return this;}};
const map={events:{},setView(){return this;},on(name,fn){this.events[name]=fn;},getCenter:()=>center,
  getZoom:()=>17, invalidateSize(){}, remove(){removed++;}};
const L={map:(el,opts)=>{options=opts;return map;},tileLayer:(url,opts)=>{tileOptions=opts;return new Layer();},
  control:{scale:()=>new Layer(),zoom:()=>new Layer()},marker:(p)=>lastMarker=new Layer(p),divIcon:x=>x,
  circle:(p)=>lastCircle=new Layer(p)};
const picker=helper.mount({}, {L,onSelect:(p,accuracy)=>chosen.push({p,accuracy}),onStatus:(...m)=>messages.push(m)});
assert.equal(chosen.length,0); assert.equal(options.maxZoom,19); assert.equal(tileOptions.noWrap,true);
map.events.click({latlng:center}); assert.deepEqual(chosen[0].p,{lat:39.915,lng:116.404});
lastMarker.value=[31.2,121.4]; lastMarker.events.dragend(); assert.equal(chosen[1].p.lng,121.4);
map.events.dragstart(); map.events.moveend(); assert.equal(chosen[2].p.lng,116.404);
let success;
const pending=picker.locate({getCurrentPosition(resolve,reject,opts){success=resolve;assert.equal(opts.enableHighAccuracy,true);assert.equal(opts.maximumAge,0);}});
picker.useCenter();
success({coords:{longitude:120,latitude:30,accuracy:20}});
pending.then(async()=>{
  assert.equal(chosen.length,4); assert.equal(chosen.at(-1).p.lng,116.404);
  await picker.locate({getCurrentPosition(resolve){resolve({coords:{longitude:120,latitude:30,accuracy:20}});}});
  assert.equal(chosen.at(-1).accuracy,20); assert.ok(lastCircle);
  const count=chosen.length;
  const late=picker.locate({getCurrentPosition(resolve){success=resolve;}});
  picker.destroy(); picker.destroy(); success({coords:{longitude:121,latitude:31,accuracy:10}});
  await late; assert.equal(chosen.length,count); assert.equal(removed,1);
}).catch(e=>{console.error(e);process.exitCode=1;});
''')


def test_map_assets_headers_and_licenses(browser):
    page = browser.client.get('/')
    assert 'https://tile.openstreetmap.org' in page.headers['Content-Security-Policy']
    assert "script-src 'self'" in page.headers['Content-Security-Policy']
    assert "connect-src 'self'" in page.headers['Content-Security-Policy']
    assert page.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    for path in ['sign-map.js', 'sign-map.css', 'vendor/leaflet-1.9.4/leaflet.js', 'vendor/leaflet-1.9.4/leaflet.css', 'vendor/coordtransform-2.1.2.js']:
        assert browser.client.get('/static/' + path).status_code == 200
    for name in ['leaflet', 'coordtransform']:
        assert browser.client.get('/legal/' + name).status_code == 200
    assets = {
        'leaflet-1.9.4/leaflet.js': 'db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a',
        'leaflet-1.9.4/leaflet.css': 'a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6',
        'coordtransform-2.1.2.js': '6037d92d149615c8557985ec5d025052dafda804cee8464b1e5ad7bf1915c89d',
    }
    for name, digest in assets.items():
        assert hashlib.sha256((ROOT / 'web' / 'vendor' / name).read_bytes()).hexdigest() == digest


def test_selected_coordinates_reach_platform_unchanged(monkeypatch):
    calls = []
    client = ChaoxingClient()
    def request(*args, **kwargs):
        calls.append(kwargs['params'])
        return response('success')
    monkeypatch.setattr(client, 'request', request)
    client.sign({'id':'1','kind':'location','course':{'courseId':'2','clazzId':'3'}},
                {'longitude':'116.416627','latitude':'39.922700','address':'测试地点'}, '测试')
    assert calls[-1]['longitude'] == '116.416627'
    assert float(calls[-1]['latitude']) == 39.922700
    assert calls[-1]['address'] == '测试地点'
