/* Map coordinates are WGS84. Conversion is local; no account data is sent to OSM.
 * Leaflet 1.9.4: BSD-2-Clause; coordtransform 2.1.2: MIT (see licenses/).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./vendor/coordtransform-2.1.2.js'));
  else root.SignMap = factory(root.coordtransform);
})(typeof globalThis !== 'undefined' ? globalThis : this, function (convert) {
  'use strict';
  const systems = new Set(['bd09', 'gcj02', 'wgs84']);

  function point(longitude, latitude) {
    if (longitude === null || latitude === null || String(longitude).trim() === '' || String(latitude).trim() === '') throw new Error('请先填写经度和纬度');
    const lng = Number(longitude), lat = Number(latitude);
    if (!Number.isFinite(lng) || !Number.isFinite(lat) || Math.abs(lng) > 180 || Math.abs(lat) > 90) throw new Error('经度应在 -180～180，纬度应在 -90～90 之间');
    return {lng, lat};
  }
  function system(value) { if (!systems.has(value)) throw new Error('不支持的坐标系'); return value; }
  function inverse(target, initial, project) {
    let p=initial;
    for(let i=0;i<12;i++) {
      const projected=project(p);
      const dx=projected.lng-target.lng, dy=projected.lat-target.lat;
      p=point(p.lng-dx,p.lat-dy);
      if(Math.max(Math.abs(dx),Math.abs(dy))<1e-9) break;
    }
    return p;
  }
  function fromWGS84(value, target) {
    const p = point(value.lng, value.lat); system(target);
    if (target === 'wgs84') return p;
    let pair = convert.wgs84togcj02(p.lng, p.lat);
    if (target === 'bd09') pair = convert.gcj02tobd09(...pair);
    return point(...pair);
  }
  function toWGS84(value, source) {
    let p = point(value.lng, value.lat); system(source);
    if (source === 'wgs84') return p;
    // Invert both projections iteratively, avoiding the extra round-trip error
    // of their single-subtraction approximations. Not a surveying guarantee.
    if (source === 'bd09') p=inverse(p,point(...convert.bd09togcj02(p.lng,p.lat)),p=>point(...convert.gcj02tobd09(p.lng,p.lat)));
    return inverse(p,p,p=>fromWGS84(p,'gcj02'));
  }
  function formatted(value, target) {
    const p = fromWGS84(value, target);
    return {longitude:p.lng.toFixed(6), latitude:p.lat.toFixed(6)};
  }

  function mount(container, {L, onSelect, onStatus}) {
    if (!L) throw new Error('地图组件未能加载，请刷新页面或手动填写坐标');
    let disposed = false, marker = null, accuracyCircle = null, locateId = 0, pickAfterMove = false;
    const map = L.map(container, {minZoom:2, maxZoom:19, worldCopyJump:true, zoomControl:false, inertia:false}).setView([35,105], 4);
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom:19, maxNativeZoom:19, noWrap:true, crossOrigin:true,
      attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
    }).addTo(map);
    let tileFailed = false;
    tiles.on('tileerror', () => {
      if (!disposed && !tileFailed) { tileFailed = true; onStatus('部分底图加载失败，请检查网络；仍可手动填写坐标，勿在空白底图上盲目选点。', true); }
    });
    L.control.scale({imperial:false}).addTo(map);
    L.control.zoom({zoomInTitle:'放大',zoomOutTitle:'缩小'}).addTo(map);
    const clearAccuracy = () => { if (accuracyCircle) { accuracyCircle.remove(); accuracyCircle = null; } };
    function select(value, accuracy) {
      if (disposed) return;
      const p = point(value.lng, value.lat);
      if (Math.abs(p.lat) > 85.05112878) throw new Error('此位置超出在线底图的纬度范围，请手动填写');
      clearAccuracy();
      if (!marker) {
        marker = L.marker([p.lat,p.lng], {draggable:true, title:'已选位置，可拖动微调', alt:'已选位置，可拖动微调',
          icon:L.divIcon({className:'sign-map-pin', html:'<span></span>', iconSize:[26,34], iconAnchor:[13,34]})}).addTo(map);
        marker.on('dragend', () => { locateId++; select(marker.getLatLng()); });
      } else marker.setLatLng([p.lat,p.lng]);
      if (Number.isFinite(accuracy) && accuracy > 0) accuracyCircle = L.circle([p.lat,p.lng], {radius:accuracy, color:'#6d52d7', weight:1, fillOpacity:0.08}).addTo(map);
      onSelect(p, accuracy);
    }
    map.on('click', event => { locateId++; select(event.latlng.wrap()); });
    map.on('dragstart', () => { locateId++; pickAfterMove=true; });
    map.on('moveend', () => { if(pickAfterMove) {pickAfterMove=false;select(map.getCenter().wrap());} });
    const frame = requestAnimationFrame(() => { if (!disposed) map.invalidateSize(); });
    return {
      center(value, zoom=17) {
        const p = point(value.lng, value.lat); locateId++; pickAfterMove=false; select(p);
        map.setView([p.lat,p.lng], zoom);
      },
      useCenter() { locateId++; select(map.getCenter().wrap()); },
      async locate(geolocation) {
        const id = ++locateId;
        if (!geolocation) { onStatus('当前浏览器不支持定位，请在地图选点或手动填写。',true); return; }
        onStatus('正在请求设备定位，请在浏览器提示中允许；不会自动提交签到。');
        try {
          const result = await new Promise((resolve,reject) => geolocation.getCurrentPosition(resolve,reject,{enableHighAccuracy:true,timeout:15000,maximumAge:0}));
          if (disposed || id !== locateId) return;
          const p = point(result.coords.longitude,result.coords.latitude);
          select(p,result.coords.accuracy);
          map.setView([p.lat,p.lng],17);
        } catch (error) {
          if (!disposed && id === locateId) onStatus((({1:'定位权限被拒绝',2:'无法获取设备位置',3:'设备定位超时'})[error.code] || '设备定位失败') + '，请在地图选点或手动填写。',true);
        }
      },
      destroy() { if (disposed) return; disposed = true; locateId++; cancelAnimationFrame(frame); map.remove(); }
    };
  }
  return {point, fromWGS84, toWGS84, formatted, mount};
});
