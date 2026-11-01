/* Local identifiers only; no hardware fingerprinting or requests. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;else root.DeviceCodes=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  function validate(value){
    if(typeof value!=='string'||!/^[A-Za-z0-9+/_=\-]{16,512}$/.test(value.trim()))throw new Error('设备码格式无效，请填写设备码本身。');
    return value.trim();
  }
  function fromShare(raw){
    try{
      if(typeof raw!=='string'||raw.length>16384)throw new Error();
      const url=new URL(raw),values=url.searchParams.getAll('dc');
      if(!['https:','http:'].includes(url.protocol)||values.length!==1)throw new Error();
      return validate(values[0]);
    }catch{throw new Error('二维码中没有有效设备码 dc，请用随地大小签重新生成包含设备码的账号分享二维码。');}
  }
  function localCode(storage,random,encode){
    const key='auto-chaoxing-browser-device-v1',saved=storage.getItem(key);
    if(saved){try{return validate(saved);}catch{throw new Error('本浏览器已保存的标识损坏，请先使用手动码或手机二维码；不会静默替换。');}}
    const bytes=new Uint8Array(32);random(bytes);
    const twice=new Uint8Array(64);twice.set(bytes);twice.set(bytes,32);
    const code=encode(String.fromCharCode(...twice));validate(code);storage.setItem(key,code);
    if(storage.getItem(key)!==code)throw new Error('本浏览器无法持久保存设备码，请使用手动码或手机二维码。');
    return code;
  }
  return {validate,fromShare,localCode};
});
