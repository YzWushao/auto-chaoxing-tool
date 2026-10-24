'use strict';
// Official AMap JS API. Its security code is injected only by our server proxy.
(async()=>{
  const send=data=>parent.postMessage({channel:'auto-chaoxing-amap',...data},location.origin);
  const loading=document.querySelector('#map-loading');
  let map,marker,circle,search,disposed=false;
  const coordinates=p=>({lng:Number(p.getLng()),lat:Number(p.getLat())});
  function select(p,accuracy) {
    if(disposed) return;
    if(circle) {circle.setMap(null);circle=null;}
    if(!marker) {
      marker=new AMap.Marker({map,position:p,draggable:true,anchor:'bottom-center',content:'<div class="amap-point-pin"></div>',title:'已选位置，可拖动微调'});
      marker.on('dragend',()=>select(marker.getPosition()));
    } else marker.setPosition(p);
    if(Number.isFinite(accuracy) && accuracy>0) circle=new AMap.Circle({map,center:p,radius:accuracy,strokeColor:'#7354d8',strokeWeight:1,fillOpacity:0.08});
    send({type:'selected',point:coordinates(p),accuracy});
  }
  try {
    const response=await fetch('/api/map/runtime',{credentials:'same-origin'}), config=await response.json();
    if(!response.ok) throw new Error(config.error||'高德配置无法读取');
    window._AMapSecurityConfig={serviceHost:config.service_host};
    await new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      const timer=setTimeout(()=>{script.remove();delete window.__autoChaoxingAMapReady;reject(new Error('高德 SDK 加载超时，请检查网络；可切回免费地图'));},18000);
      window.__autoChaoxingAMapReady=()=>{clearTimeout(timer);delete window.__autoChaoxingAMapReady;resolve();};
      script.onerror=()=>{clearTimeout(timer);delete window.__autoChaoxingAMapReady;reject(new Error('高德 SDK 加载失败，请检查网络和 Key'));};
      script.src='https://webapi.amap.com/maps?v=2.0&key='+encodeURIComponent(config.key)+'&callback=__autoChaoxingAMapReady&plugin=AMap.Scale,AMap.ToolBar,AMap.PlaceSearch';
      document.head.append(script);
    });
    if(disposed) return;
    map=new AMap.Map('amap',{viewMode:'2D',center:[105,35],zoom:4,zooms:[2,20],resizeEnable:true,jogEnable:false,animateEnable:false,rotateEnable:false});
    map.addControl(new AMap.Scale()); map.addControl(new AMap.ToolBar());
    search=new AMap.PlaceSearch({pageSize:5,pageIndex:1,extensions:'base'});
    map.on('click',event=>select(event.lnglat));
    map.on('dragend',()=>select(map.getCenter()));
    map.on('complete',()=>{loading.hidden=true;});
    map.on('error',()=>send({type:'status',error:true,message:'高德地图加载异常，请检查 Key、域名白名单、配额和网络'}));
    window.addEventListener('message',event=>{
      if(event.source!==parent || event.origin!==location.origin || event.data?.channel!=='auto-chaoxing-amap') return;
      const data=event.data;
      try {
        if(data.type==='center') {
          const p=new AMap.LngLat(data.point.lng,data.point.lat);
          map.setZoomAndCenter(Math.min(20,Math.max(2,data.zoom||17)),p); select(p,data.accuracy);
        }
        if(data.type==='useCenter') select(map.getCenter());
        if(data.type==='search') {
          if(typeof data.query!=='string' || data.query.trim().length<2 || data.query.length>120) throw new Error('请输入 2～120 个字符的公开学校或地点名称');
          search.search(data.query,(status,result)=>{
            if(disposed) return;
            const error=status==='error'?'高德搜索失败，请检查 Key、白名单或配额':null;
            const results=status==='complete'?(result.poiList?.pois||[]).filter(p=>p.location).map(p=>({name:[p.name,p.pname,p.cityname,p.adname,p.address].filter(s=>typeof s==='string'&&s).join(' · '),point:coordinates(p.location)})):[];
            send({type:'results',id:data.id,results,error});
          });
        }
      } catch(error) {send({type:data.type==='search'?'results':'status',id:data.id,error:error.message||'高德地图操作失败'});}
    });
    send({type:'ready'});
  } catch(error) {loading.textContent=error.message;send({type:'failed',message:error.message});}
  window.addEventListener('pagehide',()=>{disposed=true;map?.destroy();});
})();
