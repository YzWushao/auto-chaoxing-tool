const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
let calls=0,options,mode='ok';
const now=Date.now(),fresh={latitude:31.2,longitude:121.4,accuracy:12,captured_at:now/1000};
const context=vm.createContext({Date,Number,Math,Boolean,Promise,Error,
  window:{isSecureContext:true},navigator:{geolocation:{getCurrentPosition(resolve,reject,settings){calls++;options=settings;
    if(mode==='ok')resolve({coords:fresh,timestamp:now});else reject({code:mode});}}}});
vm.runInContext(fs.readFileSync('web/device-position.js','utf8'),context);
(async()=>{
  const device=context.window.DevicePosition;
  assert(device.available());assert.equal(calls,0,'Capability detection never requests a position');
  assert.equal((await device.get()).accuracy,12);
  assert.equal(options.enableHighAccuracy,true);assert.equal(options.maximumAge,0);assert.equal(options.timeout,20000);
  for(const code of [1,2,3]){mode=code;await assert.rejects(device.get(),/权限|定位|位置/);}
  const before=calls;context.window.AndroidScanner={deviceLocationAvailable:true,getDeviceLocation:async()=>fresh};
  assert.equal((await device.get()).latitude,31.2);assert.equal(calls,before,'Android uses its native position provider');
  context.window.AndroidScanner.getDeviceLocation=async()=>({...fresh,captured_at:now/1000-120});await assert.rejects(device.get(),/过期/);
  context.window.AndroidScanner={deviceLocationAvailable:false,waitForDeviceLocation:async()=>false};
  await assert.rejects(device.get(),/APK/);assert.equal(calls,before,'Unsupported APK must not silently fall back to an unhandled WebView permission');
  delete context.window.AndroidScanner;context.window.isSecureContext=false;
  assert.equal(device.available(),false);await assert.rejects(device.get(),/HTTPS/);
  console.log('Explicit web/native position, permission errors, freshness, HTTPS and accuracy contract passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
