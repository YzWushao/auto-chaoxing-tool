/* Unmodified decoder: jsQR 1.4.0, Apache-2.0. See licenses/jsqr-Apache-2.0.txt. */
'use strict';
importScripts('/static/vendor/jsqr-1.4.0.js');
self.onmessage = event => {
  try {
    const {pixels,width,height}=event.data;
    const result=jsQR(new Uint8ClampedArray(pixels),width,height,{inversionAttempts:'attemptBoth'});
    self.postMessage({text:result?.data || ''});
  } catch { self.postMessage({text:''}); }
};
