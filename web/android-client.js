/* Only the Android app's origin-scoped WebMessageListener exposes this object. */
'use strict';
window.AndroidScanner=(()=>{
  const bridge=window.AutoChaoxingNative;
  if(!bridge||typeof bridge.postMessage!=='function')return null;
  document.documentElement.classList.add('android-native');
  let current=null,lastLayout='',generation=0,locationTask=null,locationGeneration=0,deviceLocationAvailable=false;
  const capabilityWaiters=new Set();
  const post=data=>bridge.postMessage(JSON.stringify(data));
  bridge.onmessage=event=>{
    let data;try{data=JSON.parse(event.data);}catch{return;}
    if(data.type==='capabilities'){
      deviceLocationAvailable=data.device_location===true;
      for(const finish of capabilityWaiters)finish(deviceLocationAvailable);capabilityWaiters.clear();
      window.onAndroidCapabilities?.();return;
    }
    if(data.type==='device_location'){
      const task=locationTask;if(!task||task.id!==data.id)return;
      locationTask=null;clearTimeout(task.timeout);
      if(data.error)task.reject(new Error(data.error));else task.resolve(data.location);
      return;
    }
    const task=current;
    if(!task||data.id!==task.id)return;
    if(data.type==='started'){clearTimeout(task.timeout);task.resolve();}
    if(data.type==='qr'&&typeof data.qr==='string')task.onScan(data.qr);
    if(data.type==='closed'){
      current=null;clearTimeout(task.timeout);
      task.reject(new Error(data.message||'原生扫描已关闭'));
      task.onClosed(data.message||'原生扫描已停止');
    }
  };
  function stop(){
    const task=current;current=null;if(!task)return;
    clearTimeout(task.timeout);task.reject(new Error('原生扫描已取消'));
    post({type:'stop',id:task.id});
  }
  function start({interval,onScan,onClosed}){
    stop();
    return new Promise((resolve,reject)=>{
      const id=String(++generation);
      current={id,resolve,reject,onScan,onClosed,timeout:setTimeout(()=>{
        stop();onClosed('摄像头启动超时，请重新开始');
      },60000)};
      post({type:'start',id,interval:Math.max(100,interval)});
    });
  }
  const layout=()=>{
    const loading=document.getElementById('loading');
    if(loading&&!loading.classList.contains('hidden'))return;
    const authenticated=!!document.getElementById('app-screen')&&!document.getElementById('app-screen').classList.contains('hidden');
    const data=JSON.stringify({type:'layout',authenticated,route:location.hash.slice(1).split('?')[0]||'overview'});
    if(data!==lastLayout){lastLayout=data;bridge.postMessage(data);}
  };
  window.addEventListener('hashchange',layout);
  document.addEventListener('DOMContentLoaded',layout);
  setInterval(layout,750);
  function configureInterval(interval){if(current)post({type:'interval',id:current.id,interval:Math.max(100,interval)});}
  function cancelLocation(){
    locationGeneration++;
    if(!locationTask)return;const task=locationTask;locationTask=null;
    clearTimeout(task.timeout);task.reject(new Error('定位已取消'));post({type:'cancel_location',id:task.id});
  }
  function waitForDeviceLocation(){
    if(deviceLocationAvailable)return Promise.resolve(true);
    return new Promise(resolve=>{
      const finish=value=>{clearTimeout(timeout);capabilityWaiters.delete(finish);resolve(value);};
      const timeout=setTimeout(()=>finish(false),2000);capabilityWaiters.add(finish);
      post({type:'capabilities'});
    });
  }
  async function getDeviceLocation(){
    cancelLocation();const requested=locationGeneration;
    if(!await waitForDeviceLocation())throw new Error('当前 APK 未支持定位授权，请升级新版 APK，或在系统浏览器打开');
    if(requested!==locationGeneration)throw new Error('定位已取消');
    return new Promise((resolve,reject)=>{
      const id='location-'+String(++generation);
      locationTask={id,resolve,reject,timeout:setTimeout(()=>cancelLocation(),60000)};
      post({type:'device_location',id});
    });
  }
  setTimeout(()=>post({type:'capabilities'}),0);
  return {start,stop,configureInterval,getDeviceLocation,cancelLocation,waitForDeviceLocation,get deviceLocationAvailable(){return deviceLocationAvailable;}};
})();
