/* Only the Android app's origin-scoped WebMessageListener exposes this object. */
'use strict';
window.AndroidScanner=(()=>{
  const bridge=window.AutoChaoxingNative;
  if(!bridge||typeof bridge.postMessage!=='function')return null;
  document.documentElement.classList.add('android-native');
  let current=null,lastLayout='',generation=0;
  const post=data=>bridge.postMessage(JSON.stringify(data));
  bridge.onmessage=event=>{
    let data;try{data=JSON.parse(event.data);}catch{return;}
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
  return {start,stop,configureInterval};
})();
