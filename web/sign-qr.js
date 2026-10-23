/* Local-only QR image decoding. jsQR 1.4.0 (Apache-2.0) runs in a worker.
 * Decoded parameters are not checked against the selected activity or expiry.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SignQR = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function parameters(text) {
    const raw = String(text || '').trim();
    let enc = '', activityId = '';
    try {
      const url = new URL(raw);
      enc = url.searchParams.get('enc') || '';
      activityId = url.searchParams.get('id') || url.searchParams.get('activeId') || url.searchParams.get('activePrimaryId') || '';
    } catch { /* Plain enc or an unrecognised payload is still passed through. */ }
    return {raw, enc, activityId, value: enc || raw};
  }

  function abortError() { return new DOMException('识别已取消', 'AbortError'); }
  function checkAbort(signal) { if (signal?.aborted) throw abortError(); }

  function readPreview(file, signal) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      const abort = () => { clean(); reader.abort(); reject(abortError()); };
      signal?.addEventListener('abort', abort, {once:true});
      const clean = () => signal?.removeEventListener('abort', abort);
      reader.onload = () => { clean(); resolve(reader.result); };
      reader.onerror = () => { clean(); reject(new Error('无法读取图片，请重新选择')); };
      reader.onabort = () => { clean(); reject(abortError()); };
      if(signal?.aborted) { abort(); return; }
      reader.readAsDataURL(file);
    });
  }

  function decodePixels(pixels, width, height, signal) {
    return new Promise((resolve, reject) => {
      const worker = new Worker('/static/sign-qr-worker.js?v=0.2.1');
      let timer;
      const clean = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); worker.terminate(); };
      const abort = () => { clean(); reject(abortError()); };
      signal?.addEventListener('abort', abort, {once:true});
      worker.onmessage = event => {
        clean();
        if(event.data?.text) resolve(event.data.text);
        else reject(new Error('未识别到二维码，请选择更清晰的图片，或裁剪后重试'));
      };
      worker.onerror = () => { clean(); reject(new Error('二维码识别失败，可重新选择图片或手动粘贴内容')); };
      timer = setTimeout(() => { clean(); reject(new Error('二维码识别超时，请裁剪图片后重试')); }, 8000);
      if(signal?.aborted) { abort(); return; }
      worker.postMessage({pixels:pixels.buffer, width, height}, [pixels.buffer]);
    });
  }

  async function decodeImage(file, {signal}={}) {
    checkAbort(signal);
    if(!file || !['image/png','image/jpeg','image/webp'].includes(file.type)) throw new Error('请选择 PNG、JPEG 或 WebP 图片');
    if(!file.size || file.size > 8*1024*1024) throw new Error('图片大小需在 8 MB 以内');
    let image;
    try { image = await createImageBitmap(file); }
    catch { checkAbort(signal); throw new Error('图片无法打开，请选择有效的图片文件'); }
    try {
      checkAbort(signal);
      if(!image.width || !image.height || image.width*image.height > 24000000) throw new Error('图片尺寸过大，请裁剪到二维码区域后重试');
      const scale = Math.min(1,2048/Math.max(image.width,image.height));
      const width = Math.max(1,Math.round(image.width*scale)), height = Math.max(1,Math.round(image.height*scale));
      const canvas = document.createElement('canvas'); canvas.width=width; canvas.height=height;
      const context = canvas.getContext('2d',{willReadFrequently:true});
      if(!context) throw new Error('当前浏览器无法读取图片，请手动粘贴二维码内容');
      context.fillStyle='#fff'; context.fillRect(0,0,width,height); context.drawImage(image,0,0,width,height);
      const data=context.getImageData(0,0,width,height).data;
      const text=await decodePixels(data,width,height,signal);
      checkAbort(signal);
      const preview=await readPreview(file,signal);
      checkAbort(signal);
      return {...parameters(text), preview};
    } finally { image.close(); }
  }

  return {parameters,decodeImage};
});
