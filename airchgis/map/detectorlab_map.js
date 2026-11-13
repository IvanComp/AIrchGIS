/* Map interface adapted from DetectorLab (https://github.com/IvanComp/DetectorLab), Apache License 2.0.
   Kept: satellite base, 3D terrain, place names, measure, UTM coordinates, Google Earth link, layer panel.
   Removed: historical maps, Roman roads, prediction-model layer. Added: AIrchGIS raster layers and elevation readout. */
(function(){
const CFG=window.AIRCHGIS_MAP||{layers:[]};
const toast=document.querySelector('.toast');
let map,terrainEnabled=CFG.terrain!==false,measurementActive=false,coordinateActive=false;
let measurementPoints=[],measurementMarkers=[],coordinateMarker=null,selectedEarthPoint=null;
const measureButton=document.querySelector('[data-map-action="measure"]');
const coordinateButton=document.querySelector('[data-map-action="coordinates"]');
const earthButton=document.querySelector('[data-map-action="earth"]');
const terrainButton=document.querySelector('.terrain-toggle');
const labelIds=['locality-cities','locality-towns','locality-villages'];

function showToast(message){toast.textContent=message;toast.classList.add('show');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>toast.classList.remove('show'),2600);}
function emptyFC(){return{type:'FeatureCollection',features:[]};}

function layerBounds(){
  let w=180,s=90,e=-180,n=-90;
  CFG.layers.forEach(l=>{w=Math.min(w,l.bounds[0]);s=Math.min(s,l.bounds[1]);e=Math.max(e,l.bounds[2]);n=Math.max(n,l.bounds[3]);});
  if(CFG.elevation){const b=CFG.elevation.bounds;w=Math.min(w,b[0]);s=Math.min(s,b[1]);e=Math.max(e,b[2]);n=Math.max(n,b[3]);}
  return w<e?[[w,s],[e,n]]:null;
}

function initMap(){
  const bounds=layerBounds();
  map=new maplibregl.Map({
    container:'detectorMap',
    center:bounds?[(bounds[0][0]+bounds[1][0])/2,(bounds[0][1]+bounds[1][1])/2]:[12.5,42.5],zoom:bounds?14:5,
    pitch:terrainEnabled?45:0,bearing:terrainEnabled?-10:0,maxPitch:80,maxZoom:19,antialias:true,attributionControl:false,
    style:{version:8,glyphs:'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
      sources:{
        satellite:{type:'raster',tiles:[CFG.basemap],tileSize:256,attribution:'© Esri, Maxar, Earthstar Geographics'},
        terrain:{type:'raster-dem',tiles:['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],tileSize:256,maxzoom:15,encoding:'terrarium',attribution:'Terrain © AWS Terrain Tiles'}
      },
      layers:[{id:'satellite',type:'raster',source:'satellite'}],
      terrain:terrainEnabled?{source:'terrain',exaggeration:1.35}:undefined,
      sky:{'sky-color':'#ead7b5','horizon-color':'#7a5a37','fog-color':'#2c1b11','sky-horizon-blend':.18,'horizon-fog-blend':.12,'fog-ground-blend':.55}
    }
  });
  map.on('error',e=>console.warn('map:',e&&e.error&&e.error.message));
  map.addControl(new maplibregl.AttributionControl({compact:true}),'bottom-right');
  map.addControl(new maplibregl.ScaleControl({maxWidth:90,unit:'metric'}),'bottom-left');
  window.airchgisMap=map;
  // add our layers as soon as the style is parsed: waiting for 'load' would also wait for every
  // terrain/label tile, which never happens offline or behind a firewall
  let ready=false;
  const onReady=()=>{if(ready)return;ready=true;
    if(bounds){const el=map.getContainer();const right=Math.min(340,el.clientWidth*.42);
      map.fitBounds(bounds,{padding:{top:30,bottom:30,left:70,right:right},pitch:0,bearing:0,duration:0});
      if(terrainEnabled)map.jumpTo({pitch:40,bearing:-8});}
    CFG.layers.slice().reverse().forEach(l=>{
      const [w,s,e,n]=l.bounds;
      map.addSource(l.id,{type:'image',url:l.image,coordinates:[[w,n],[e,n],[e,s],[w,s]]});
      map.addLayer({id:l.id,type:'raster',source:l.id,layout:{visibility:l.visible?'visible':'none'},paint:{'raster-opacity':l.opacity,'raster-fade-duration':0,'raster-resampling':'nearest'}});
    });
    if(CFG.labels)addLabels();
    map.addSource('measurement',{type:'geojson',data:emptyFC()});
    map.addLayer({id:'measurement-line',type:'line',source:'measurement',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#e5a23d','line-width':3,'line-dasharray':[2,1.5]}});
  };
  map.once('style.load',onReady);
  map.once('load',onReady);
  if(map.style&&map.style._loaded)onReady();
  map.on('click',e=>{if(measurementActive)handleMeasurementClick(e);else if(coordinateActive)handleCoordinateClick(e);});
}

function addLabels(){
  try{map.addSource('openmaptiles',{type:'vector',url:'https://tiles.openfreemap.org/planet',attribution:'© OpenMapTiles © OpenStreetMap contributors'});}catch(e){return;}
  const layout={'text-field':['coalesce',['get','name:en'],['get','name']],'text-font':['Noto Sans Regular'],'text-anchor':'bottom','text-max-width':9};
  const paint={'text-color':'#fffdf6','text-halo-color':'rgba(35,21,12,.94)','text-halo-width':1.6,'text-opacity':1};
  map.addLayer({id:'locality-cities',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:3,filter:['==',['get','class'],'city'],layout:{...layout,'text-font':['Noto Sans Bold'],'text-size':14},paint});
  map.addLayer({id:'locality-towns',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:6,filter:['==',['get','class'],'town'],layout:{...layout,'text-size':12},paint});
  map.addLayer({id:'locality-villages',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:8.5,filter:['match',['get','class'],['village','hamlet'],true,false],layout:{...layout,'text-size':11},paint});
}

function card(id,icon,name,desc,checked,opacity,meta){
  const el=document.createElement('div');
  el.className='exact-layer-card'+(checked?' active':'');
  el.innerHTML=`<div class="exact-layer-top"><span>${icon} <b></b></span><button class="card-expand" type="button" aria-expanded="false">›</button><label class="exact-switch"><input type="checkbox" ${checked?'checked':''}><em></em></label></div><p class="card-layer-desc"></p><div class="card-expand-content"><div class="exact-opacity"><span>Opacity</span><output>${Math.round(opacity*100)}%</output></div><input class="exact-range" type="range" min="0" max="100" value="${Math.round(opacity*100)}"></div>`;
  el.querySelector('b').textContent=name;el.querySelector('.card-layer-desc').textContent=desc;
  if(meta){const p=document.createElement('p');p.className='layer-meta';p.textContent=meta;el.querySelector('.card-expand-content').prepend(p);}
  el.querySelector('.card-expand').addEventListener('click',ev=>{const open=el.classList.toggle('expanded');ev.currentTarget.textContent=open?'⌄':'›';ev.currentTarget.setAttribute('aria-expanded',String(open));});
  return el;
}

function buildPanel(){
  const box=document.querySelector('.layer-cards');
  CFG.layers.forEach(l=>{
    const el=card(l.id,'◉',l.name,l.description,l.visible,l.opacity);
    const toggle=el.querySelector('input[type=checkbox]'),range=el.querySelector('.exact-range'),out=el.querySelector('output');
    toggle.addEventListener('change',()=>{if(map.getLayer(l.id))map.setLayoutProperty(l.id,'visibility',toggle.checked?'visible':'none');el.classList.toggle('active',toggle.checked);});
    range.addEventListener('input',()=>{out.textContent=`${range.value}%`;if(map.getLayer(l.id))map.setPaintProperty(l.id,'raster-opacity',Number(range.value)/100);});
    box.appendChild(el);
  });
  if(CFG.labels){
    const el=card('labels','⌖','Place names','OpenStreetMap place names.',true,1);
    const toggle=el.querySelector('input[type=checkbox]'),range=el.querySelector('.exact-range'),out=el.querySelector('output');
    toggle.addEventListener('change',()=>{labelIds.forEach(id=>{if(map.getLayer(id))map.setLayoutProperty(id,'visibility',toggle.checked?'visible':'none');});el.classList.toggle('active',toggle.checked);});
    range.addEventListener('input',()=>{out.textContent=`${range.value}%`;labelIds.forEach(id=>{if(map.getLayer(id))map.setPaintProperty(id,'text-opacity',Number(range.value)/100);});});
    box.appendChild(el);
  }
  const sat=card('satellite','▦','Satellite','Base map: satellite imagery.',true,1);
  const st=sat.querySelector('input[type=checkbox]'),sr=sat.querySelector('.exact-range'),so=sat.querySelector('output');
  st.addEventListener('change',()=>{map.setLayoutProperty('satellite','visibility',st.checked?'visible':'none');sat.classList.toggle('active',st.checked);});
  sr.addEventListener('input',()=>{so.textContent=`${sr.value}%`;map.setPaintProperty('satellite','raster-opacity',Number(sr.value)/100);});
  box.appendChild(sat);
}

/* measure (from DetectorLab) */
function distanceBetween(a,b){const r=x=>x*Math.PI/180;const R=6371000;const dLat=r(b[1]-a[1]),dLng=r(b[0]-a[0]);const q=Math.sin(dLat/2)**2+Math.cos(r(a[1]))*Math.cos(r(b[1]))*Math.sin(dLng/2)**2;return R*2*Math.atan2(Math.sqrt(q),Math.sqrt(1-q));}
function formatDistance(m){return m<1000?`${m<10?m.toFixed(1):Math.round(m)} m`:`${(m/1000).toFixed(2)} km`;}
function clearMeasurementMarkers(){measurementMarkers.forEach(m=>m.remove());measurementMarkers=[];}
function addMarker(coords,cls,text,anchor,offset){const el=document.createElement('div');el.className=cls;el.textContent=text;measurementMarkers.push(new maplibregl.Marker({element:el,anchor,offset}).setLngLat(coords).addTo(map));}
function updateMeasurementDrawing(){
  const src=map.getSource('measurement');if(!src)return;
  const f=measurementPoints.length===2?[{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:measurementPoints}}]:[];
  src.setData({type:'FeatureCollection',features:f});clearMeasurementMarkers();
  measurementPoints.forEach((c,i)=>addMarker(c,'measure-point-marker',String(i+1),'center',[0,0]));
  if(measurementPoints.length===2){const d=formatDistance(distanceBetween(measurementPoints[0],measurementPoints[1]));addMarker(measurementPoints[1],'measure-label measure-total',`Total: ${d}`,'left',[14,0]);}
}
function setMeasurementMode(active){if(active&&coordinateActive)setCoordinateMode(false);measurementActive=active;measureButton.classList.toggle('active',active);map.getCanvas().style.cursor=active||coordinateActive?'crosshair':'';if(active){measurementPoints=[];updateMeasurementDrawing();showToast('Select point 1 on the map');}}
function handleMeasurementClick(e){if(measurementPoints.length===2){measurementPoints=[];clearMeasurementMarkers();}measurementPoints.push([e.lngLat.lng,e.lngLat.lat]);updateMeasurementDrawing();showToast(measurementPoints.length===1?'Point 1 set. Select point 2':`Distance: ${formatDistance(distanceBetween(measurementPoints[0],measurementPoints[1]))}`);}

/* UTM coordinates (from DetectorLab) + elevation from the loaded terrain */
function utmBand(lat){if(lat<-80||lat>84)return'';return'CDEFGHJKLMNPQRSTUVWXX'[Math.min(19,Math.floor((lat+80)/8))];}
function utmZone(lon,lat){let z=Math.floor((lon+180)/6)+1;if(lat>=56&&lat<64&&lon>=3&&lon<12)z=32;if(lat>=72&&lat<84){if(lon>=0&&lon<9)z=31;else if(lon<21)z=33;else if(lon<33)z=35;else if(lon<42)z=37;}return Math.max(1,Math.min(60,z));}
function toUtm(lon,lat){const a=6378137,e2=0.00669438,k0=0.9996,zone=utmZone(lon,lat),lon0=((zone-1)*6-180+3)*Math.PI/180,phi=lat*Math.PI/180,lam=lon*Math.PI/180,ep2=e2/(1-e2),s=Math.sin(phi),c=Math.cos(phi),t=Math.tan(phi),N=a/Math.sqrt(1-e2*s*s),T=t*t,C=ep2*c*c,A=c*(lam-lon0),e4=e2*e2,e6=e4*e2;
  const M=a*((1-e2/4-3*e4/64-5*e6/256)*phi-(3*e2/8+3*e4/32+45*e6/1024)*Math.sin(2*phi)+(15*e4/256+45*e6/1024)*Math.sin(4*phi)-(35*e6/3072)*Math.sin(6*phi));
  const E=k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T*T+72*C-58*ep2)*A**5/120)+500000;let Nn=k0*(M+N*t*(A*A/2+(5-T+9*C+4*C*C)*A**4/24+(61-58*T+T*T+600*C-330*ep2)*A**6/720));if(lat<0)Nn+=1e7;
  return`UTM ${zone}${utmBand(lat)} ${Math.round(E)} m E ${Math.round(Nn)} m N`;}
function elevationAt(lon,lat){const g=CFG.elevation;if(!g)return null;const[w,s,e,n]=g.bounds;if(lon<w||lon>e||lat<s||lat>n)return null;const col=Math.min(g.width-1,Math.floor((lon-w)/(e-w)*g.width)),row=Math.min(g.height-1,Math.floor((n-lat)/(n-s)*g.height));return g.values[row*g.width+col];}
function googleEarthUrl(lon,lat){return`https://earth.google.com/web/search/${encodeURIComponent(`${lat.toFixed(6)},${lon.toFixed(6)}`)}`;}
async function copyText(v){try{await navigator.clipboard.writeText(v);return true;}catch(err){return false;}}
function setCoordinateMode(active){if(active&&measurementActive)setMeasurementMode(false);coordinateActive=active;coordinateButton.classList.toggle('active',active);map.getCanvas().style.cursor=active||measurementActive?'crosshair':'';if(active)showToast('Select a point on the map');}
async function handleCoordinateClick(e){
  const lon=e.lngLat.lng,lat=e.lngLat.lat;selectedEarthPoint=[lon,lat];earthButton.disabled=false;
  const utm=toUtm(lon,lat),z=elevationAt(lon,lat);
  const text=`${utm}${z===null||z===undefined?'':` · elevation ${z.toFixed(2)} m`}`;
  const copied=await copyText(text);
  coordinateMarker?.remove();
  const m=document.createElement('div');m.className='coordinate-utm-marker';m.textContent='⌾';
  const box=document.createElement('div');box.className='coordinate-utm-popup';
  const h=document.createElement('b');h.textContent='COORDINATES';const code=document.createElement('code');code.textContent=`${utm}\nlat ${lat.toFixed(6)}, lon ${lon.toFixed(6)}${z===null||z===undefined?'':`\nelevation ${z.toFixed(2)} m`}`;code.style.whiteSpace='pre';
  const a=document.createElement('a');a.href=googleEarthUrl(lon,lat);a.target='_blank';a.rel='noopener';a.textContent='Open in Google Earth';a.className='coordinate-earth-btn';
  box.append(h,code,a);
  coordinateMarker=new maplibregl.Marker({element:m,anchor:'center'}).setLngLat([lon,lat]).setPopup(new maplibregl.Popup({closeButton:true,offset:18,maxWidth:'310px'}).setDOMContent(box)).addTo(map);
  coordinateMarker.togglePopup();setCoordinateMode(false);showToast(copied?`Copied: ${text}`:text);
}

function wireControls(){
  document.querySelector('[data-map-action="zoom-in"]').addEventListener('click',()=>map.zoomIn());
  document.querySelector('[data-map-action="zoom-out"]').addEventListener('click',()=>map.zoomOut());
  measureButton.addEventListener('click',()=>setMeasurementMode(!measurementActive));
  coordinateButton.addEventListener('click',()=>setCoordinateMode(!coordinateActive));
  earthButton.addEventListener('click',()=>{if(selectedEarthPoint)window.open(googleEarthUrl(selectedEarthPoint[0],selectedEarthPoint[1]),'_blank','noopener');});
  const label=()=>{terrainButton.querySelector('small').textContent=terrainEnabled?'Relief on':'Flat view';terrainButton.setAttribute('aria-pressed',String(terrainEnabled));};
  terrainButton.addEventListener('click',()=>{terrainEnabled=!terrainEnabled;map.setTerrain(terrainEnabled?{source:'terrain',exaggeration:1.35}:null);map.easeTo({pitch:terrainEnabled?50:0,bearing:terrainEnabled?-12:0,duration:700});label();});
  label();
  document.querySelector('.panel-handle').addEventListener('click',ev=>{const shell=document.querySelector('.detector-map');const c=shell.classList.toggle('panel-collapsed');ev.currentTarget.textContent=c?'‹':'›';});
  document.querySelector('.map-fullscreen').addEventListener('click',()=>{const el=document.querySelector('.detector-map');if(!document.fullscreenElement&&el.requestFullscreen){el.requestFullscreen();}else if(document.exitFullscreen){document.exitFullscreen();}setTimeout(()=>map.resize(),300);});
}

if(window.maplibregl){initMap();buildPanel();wireControls();}
else{document.getElementById('detectorMap').innerHTML='<p style="color:#f3d68f;padding:24px">The map needs an internet connection (MapLibre and satellite tiles).</p>';}
})();
