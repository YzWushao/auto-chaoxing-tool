(function(root,factory){
  const api=factory(); if(typeof module==='object'&&module.exports) module.exports=api; else root.AMapPicker=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function mount(container,{onSelect,onStatus,convert}) {
    const frame=document.createElement('iframe'); frame.title='高德地图选点'; frame.className='amap-picker-frame'; frame.src='/map/amap';
    let disposed=false,ready=false,pendingCenter=null,requestId=0,locateId=0,resolveReady,rejectReady;
    const pending=new Map();
    const readiness=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;}); readiness.catch(()=>{});
    const abort=()=>new DOMException('地图已关闭','AbortError');
    const send=data=>{if(!disposed) frame.contentWindow?.postMessage({channel:'auto-chaoxing-amap',...data},location.origin);};
    const timer=setTimeout(()=>fail('高德地图加载超时，可切回免费地图重试'),22000);
    function fail(message) {clearTimeout(timer);rejectReady(new Error(message));onStatus(message,true);}
    function receive(event) {
      if(disposed || event.source!==frame.contentWindow || event.origin!==location.origin || event.data?.channel!=='auto-chaoxing-amap') return;
      const data=event.data;
      if(data.type==='ready') {clearTimeout(timer);ready=true;resolveReady();if(pendingCenter) send(pendingCenter);}
      if(data.type==='failed') fail(data.message||'高德地图未能加载');
      if(data.type==='status') onStatus(data.message||String(data.error||'地图服务异常'),Boolean(data.error));
      if(data.type==='selected') {
        try {locateId++;onSelect(convert.toWGS84(data.point,'gcj02'),data.accuracy);} catch(error) {onStatus(error.message,true);}
      }
      if(data.type==='results' && pending.has(data.id)) {
        const entry=pending.get(data.id);clearTimeout(entry.timer);pending.delete(data.id);
        if(data.error) entry.reject(new Error(data.error));
        else {try {entry.resolve(data.results.map(p=>({...convert.toWGS84(p.point,'gcj02'),name:p.name})));} catch {entry.reject(new Error('高德搜索返回无效坐标'));}}
      }
    }
    window.addEventListener('message',receive); container.replaceChildren(frame);
    function center(point,zoom=17,accuracy) {locateId++;pendingCenter={type:'center',point:convert.fromWGS84(point,'gcj02'),zoom,accuracy};if(ready) send(pendingCenter);}
    return {provider:'amap',center,
      useCenter(){locateId++;if(ready) send({type:'useCenter'});else onStatus('高德地图仍在加载，请稍后重试',true);},
      async search(query) {
        await readiness;if(disposed) throw abort();
        return new Promise((resolve,reject)=>{const id=++requestId;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('高德搜索超时，请重试'));},15000);pending.set(id,{resolve,reject,timer});send({type:'search',id,query});});
      },
      async locate(geolocation) {
        const id=++locateId;
        if(!geolocation) {onStatus('浏览器不支持定位，请搜索或拖动地图',true);return;}
        onStatus('正在请求设备高精度定位…');
        try {
          const result=await new Promise((resolve,reject)=>geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,timeout:15000,maximumAge:0}));
          if(disposed||id!==locateId) return;
          center({lng:result.coords.longitude,lat:result.coords.latitude},17,result.coords.accuracy);
        } catch {if(!disposed&&id===locateId) onStatus('设备定位未成功，请搜索或拖动地图选点',true);}
      },
      destroy(){if(disposed)return;disposed=true;clearTimeout(timer);rejectReady(abort());window.removeEventListener('message',receive);for(const p of pending.values()){clearTimeout(p.timer);p.reject(abort());}pending.clear();frame.remove();}
    };
  }
  return {mount};
});
