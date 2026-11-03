'use strict';
// Resolve only a user-selected point, never poll, track, or geocode in bulk.
const MapAddressLookup=(()=>{
  const pending=new Map();
  function cancel(context){const work=pending.get(context);if(work){clearTimeout(work.timer);work.abort.abort();pending.delete(context);}}
  function queue(context,point,force=false){
    cancel(context);
    const preset=context==='preset',field=$(preset?'#edit-point-address':'#sign-address');
    if(!field||field.readOnly)return;
    const auto=context+'MapAddress',status=preset?presetMapStatus:signMapStatus;
    const generated=/^地图选点[（(].*[）)]$/.test(field.value);
    if(!force&&field.value&&field.value!==state[auto]&&!generated)return;
    // Remove the obsolete generated address as soon as the point changes.
    field.value='';state[auto]='';
    const provider=$('#'+context+'-map-provider')?.value||state.map_settings?.provider||'osm';
    if(provider!=='amap'&&!state.map_settings?.free_reverse_enabled){
      status('已回填坐标。免费地图自动地址查询需在设置 → 地图服务开启；也可手动填写位置说明。');return;
    }
    const work={abort:new AbortController(),timer:null};pending.set(context,work);
    status('已回填坐标，正在查询此点的地图地址说明…');
    work.timer=setTimeout(async()=>{
      const map=state[context+'Map'];
      const current=()=>pending.get(context)===work&&state[context+'MapPoint']===point&&state[context+'Map']===map&&$(preset?'#edit-point-address':'#sign-address')===field;
      try{
        const data=provider==='amap'?await map.reverse(point):await api('/map/reverse','POST',{longitude:point.lng,latitude:point.lat},{signal:work.abort.signal});
        if(!current())return;
        if(typeof data.address!=='string'||!data.address.trim())throw new Error('地图未返回地址，请手动填写位置说明');
        if(!field.value){field.value=data.address.trim().slice(0,200);state[auto]=field.value;status(`地址来自${provider==='amap'?'高德地图':'OpenStreetMap'}，请核对实际地点：${field.value}`);}
        else status('地址查询已完成，保留了你刚刚手动填写的位置说明。');
      }catch(error){if(current()&&error.name!=='AbortError')status((error.message||'地址查询失败')+'；请手动填写位置说明，或点击“获取位置说明”重试。',true);}
      finally{if(pending.get(context)===work)pending.delete(context);}
    },1300);
  }
  return {queue,cancel};
})();
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-map-address]');if(!button)return;
  const context=button.dataset.mapAddress,point=state[context+'MapPoint'];
  if(point)MapAddressLookup.queue(context,point,true);
  else (context==='preset'?presetMapStatus:signMapStatus)('请先在地图上选点。',true);
});
