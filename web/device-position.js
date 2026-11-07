/* One explicitly requested foreground fix, shared by web and Android. */
'use strict';
window.DevicePosition={
  available(){return Boolean(window.AndroidScanner?.deviceLocationAvailable||(window.isSecureContext&&navigator.geolocation));},
  async get(){
    let fix;
    if(window.AndroidScanner?.deviceLocationAvailable)fix=await window.AndroidScanner.getDeviceLocation();
    else{
      if(!window.isSecureContext)throw new Error('设备定位需要 HTTPS 或本机 localhost 访问');
      if(!navigator.geolocation)throw new Error('当前设备或浏览器不支持定位，请选择预设点位');
      fix=await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(position=>resolve({
        latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy,captured_at:position.timestamp/1000,
      }),error=>reject(new Error(({1:'未允许定位权限，请在浏览器或系统设置中授权',2:'无法获取当前位置，请检查系统定位服务',3:'定位超时，请重试或选择实际所在的预设点位'})[error.code]||'设备定位失败')),
      {enableHighAccuracy:true,maximumAge:0,timeout:20000}));
    }
    if(!fix||!['latitude','longitude','accuracy','captured_at'].every(k=>typeof fix[k]==='number'&&Number.isFinite(fix[k]))
      ||Math.abs(fix.latitude)>90||Math.abs(fix.longitude)>180||fix.accuracy<=0||Date.now()/1000-fix.captured_at>60||fix.captured_at-Date.now()/1000>10)
      throw new Error('设备返回的位置无效或已过期，请重新定位');
    return fix;
  }
};
