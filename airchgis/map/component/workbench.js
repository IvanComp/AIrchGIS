(function(){

function post(type,data){window.parent.postMessage(Object.assign({isStreamlitMessage:true,type},data),'*');}
function setValue(value){post('streamlit:setComponentValue',{value,dataType:'json'});}
function setHeight(h){post('streamlit:setFrameHeight',{height:h});}

let ARGS=null,map=null,initialized=false,pendingNonce=null,lastDownload=null,last3d=null,nonceCounter=0;
let rvtWorkspace=null;
const shownLayers=new Map();
const toast=document.querySelector('.toast');
const busy=document.querySelector('.wb-busy');
const messageBox=document.querySelector('.wb-message');

function showToast(m){toast.textContent=m;toast.classList.add('show');clearTimeout(window.tt);window.tt=setTimeout(()=>toast.classList.remove('show'),2600);}
function send(event){
  if(pendingNonce)return;
  nonceCounter+=1;
  event.nonce=`${Date.now()}-${nonceCounter}`;
  pendingNonce=event.nonce;
  busy.hidden=false;
  rvtWorkspace?.setBusy(true);
  document.querySelector('.wb-3d-busy').hidden=document.querySelector('.wb-modal').hidden;
  document.querySelector('.wb-3d-busy').textContent=event.action==='view3d'?'Preparing 3D view…':'Preparing export…';
  document.querySelector('.wb-cloud').disabled=true;
  document.querySelectorAll('.wb-run').forEach(b=>b.disabled=true);
  setValue(event);
}

window.addEventListener('message',ev=>{
  const d=ev.data||{};
  if(d.type!=='streamlit:render')return;
  ARGS=(d.args&&d.args.args)||d.args||{};
  if(!initialized){initialized=true;setHeight(ARGS.height||760);init();}
  update();
});
post('streamlit:componentReady',{apiVersion:1});

let terrainEnabled=true,measurementActive=false,coordinateActive=false,measurementPoints=[],measurementMarkers=[],coordinateMarker=null,selectedEarthPoint=null;
const labelIds=['locality-cities','locality-towns','locality-villages'];

function layerBounds(){
  let w=180,s=90,e=-180,n=-90;
  (ARGS.layers||[]).forEach(l=>{w=Math.min(w,l.bounds[0]);s=Math.min(s,l.bounds[1]);e=Math.max(e,l.bounds[2]);n=Math.max(n,l.bounds[3]);});
  if(ARGS.elevation){const b=ARGS.elevation.bounds;w=Math.min(w,b[0]);s=Math.min(s,b[1]);e=Math.max(e,b[2]);n=Math.max(n,b[3]);}
  return w<e?[[w,s],[e,n]]:null;
}

function initMap(){
  if(!window.maplibregl){document.getElementById('detectorMap').innerHTML='<p style="color:#f3d68f;padding:24px">The map needs an internet connection (MapLibre and satellite tiles).</p>';return;}
  const bounds=layerBounds();
  map=new maplibregl.Map({container:'detectorMap',center:bounds?[(bounds[0][0]+bounds[1][0])/2,(bounds[0][1]+bounds[1][1])/2]:[12.5,42.5],zoom:bounds?14:5,
    maxPitch:80,maxZoom:19,antialias:true,attributionControl:false,preserveDrawingBuffer:true,
    style:{version:8,glyphs:'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
      sources:{
        satellite:{type:'raster',tiles:[ARGS.basemap||'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,attribution:'© Esri, Maxar, Earthstar Geographics'},
        terrain:{type:'raster-dem',tiles:['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],tileSize:256,maxzoom:15,encoding:'terrarium',attribution:'Terrain © AWS Terrain Tiles'}},
      layers:[{id:'satellite',type:'raster',source:'satellite'}],
      terrain:{source:'terrain',exaggeration:1.35},
      sky:{'sky-color':'#ead7b5','horizon-color':'#7a5a37','fog-color':'#2c1b11','sky-horizon-blend':.18,'horizon-fog-blend':.12,'fog-ground-blend':.55}}});
  map.on('error',e=>console.warn('map:',e&&e.error&&e.error.message));
  map.addControl(new maplibregl.AttributionControl({compact:true}),'bottom-right');
  map.addControl(new maplibregl.ScaleControl({maxWidth:90,unit:'metric'}),'bottom-left');
  let ready=false;
  const onReady=()=>{if(ready)return;ready=true;
    if(bounds){const el=map.getContainer();const right=document.querySelector('.exact-layer-panel').getBoundingClientRect().width+24;
      map.fitBounds(bounds,{padding:{top:30,bottom:30,left:70,right},pitch:0,bearing:0,duration:0});map.jumpTo({pitch:40,bearing:-8});}
    addLabels();
    map.addSource('measurement',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'measurement-line',type:'line',source:'measurement',filter:['==',['geometry-type'],'LineString'],paint:{'line-color':'#e5a23d','line-width':3,'line-dasharray':[2,1.5]}});
    syncLayers();
  };
  map.once('style.load',onReady);map.once('load',onReady);
  map.on('click',e=>{if(measurementActive)handleMeasurementClick(e);else if(coordinateActive)handleCoordinateClick(e);});
}
function addLabels(){
  try{map.addSource('openmaptiles',{type:'vector',url:'https://tiles.openfreemap.org/planet',attribution:'© OpenMapTiles © OpenStreetMap contributors'});}catch(e){return;}
  const layout={'text-field':['coalesce',['get','name:en'],['get','name']],'text-font':['Noto Sans Regular'],'text-anchor':'bottom','text-max-width':9};
  const paint={'text-color':'#fffdf6','text-halo-color':'rgba(35,21,12,.94)','text-halo-width':1.6};
  map.addLayer({id:'locality-cities',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:3,filter:['==',['get','class'],'city'],layout:{...layout,'text-font':['Noto Sans Bold'],'text-size':14},paint});
  map.addLayer({id:'locality-towns',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:6,filter:['==',['get','class'],'town'],layout:{...layout,'text-size':12},paint});
  map.addLayer({id:'locality-villages',type:'symbol',source:'openmaptiles','source-layer':'place',minzoom:8.5,filter:['match',['get','class'],['village','hamlet'],true,false],layout:{...layout,'text-size':11},paint});
  labelIds.forEach(id=>{map.setLayoutProperty(id,'visibility',fixedState.labels.visible?'visible':'none');map.setPaintProperty(id,'text-opacity',fixedState.labels.opacity);});
}
function mapReady(){return map&&map.getLayer&&map.getLayer('measurement-line');}

const mapLayerIds=new Map();
function syncLayers(){
  if(!mapReady())return;
  const layers=ARGS.layers||[];
  const wanted=new Set(layers.map(l=>l.id));
  [...mapLayerIds.keys()].forEach(id=>{if(!wanted.has(id)){if(map.getLayer('wb-'+id))map.removeLayer('wb-'+id);if(map.getSource('wb-'+id))map.removeSource('wb-'+id);mapLayerIds.delete(id);shownLayers.delete(id);}});

  layers.slice().reverse().forEach(l=>{
    const [w,s,e,n]=l.bounds,coords=[[w,n],[e,n],[e,s],[w,s]];
    if(mapLayerIds.get(l.id)!==l.image){
      if(map.getLayer('wb-'+l.id))map.removeLayer('wb-'+l.id);
      if(map.getSource('wb-'+l.id))map.removeSource('wb-'+l.id);
      map.addSource('wb-'+l.id,{type:'image',url:l.image,coordinates:coords});
      map.addLayer({id:'wb-'+l.id,type:'raster',source:'wb-'+l.id,paint:{'raster-opacity':l.opacity,'raster-fade-duration':0}},map.getLayer('locality-cities')?'locality-cities':'measurement-line');
      mapLayerIds.set(l.id,l.image);
      shownLayers.set(l.id,{visible:l.visible,opacity:l.opacity});
    }else if(map.getLayer('wb-'+l.id)){
      map.moveLayer('wb-'+l.id,map.getLayer('locality-cities')?'locality-cities':'measurement-line');
    }
    const st=shownLayers.get(l.id)||{visible:l.visible,opacity:l.opacity};
    if(l.visible!==undefined&&l._forced)st.visible=l.visible;
    map.setLayoutProperty('wb-'+l.id,'visibility',st.visible?'visible':'none');
    map.setPaintProperty('wb-'+l.id,'raster-opacity',st.opacity);
  });
  renderLayerCards();
}
function renderLayerCards(){
  const box=document.querySelector('.layer-cards');box.innerHTML='';
  const lab=card('⌖','Place','OpenStreetMap place names.',true,1);
  wireFixed(lab,v=>labelIds.forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',v?'visible':'none')),o=>labelIds.forEach(id=>map.getLayer(id)&&map.setPaintProperty(id,'text-opacity',o)),'labels');
  box.appendChild(lab);
  const sat=card('▦','Base map','Satellite imagery.',true,1);
  wireFixed(sat,setBaseMapVisible,o=>map.getLayer('satellite')&&map.setPaintProperty('satellite','raster-opacity',o),'satellite');
  box.appendChild(sat);
  (ARGS.layers||[]).forEach(l=>{
    const st=shownLayers.get(l.id)||{visible:l.visible,opacity:l.opacity};
    const el=card('◉',l.name,l.description,st.visible,st.opacity);
    if(l.id==='rvt_current'||/^view\d+(?:_clahe)*$/.test(l.id))el.querySelector('b').textContent='Relief view';
    const t=el.querySelector('input[type=checkbox]'),r=el.querySelector('.exact-range'),o=el.querySelector('output');
    t.addEventListener('change',()=>{st.visible=t.checked;shownLayers.set(l.id,st);map.setLayoutProperty('wb-'+l.id,'visibility',t.checked?'visible':'none');el.classList.toggle('active',t.checked);});
    r.addEventListener('input',()=>{st.opacity=Number(r.value)/100;shownLayers.set(l.id,st);o.textContent=`${r.value}%`;map.setPaintProperty('wb-'+l.id,'raster-opacity',st.opacity);});
    const tools=document.createElement('div');tools.className='layer-tools';
    tools.innerHTML='<button type="button" data-a="contrast" title="Adaptive histogram equalization, display only">Contrast</button><button type="button" data-a="download">GeoTIFF</button>';
    tools.querySelector('[data-a=contrast]').addEventListener('click',()=>send({action:'contrast',layer:l.id,replace:true}));
    tools.querySelector('[data-a=download]').addEventListener('click',()=>send({action:'download',layer:l.id}));
    el.querySelector('.card-expand-content').appendChild(tools);
    box.appendChild(el);
  });


}
const fixedState={labels:{visible:true,opacity:1},satellite:{visible:true,opacity:1}};
function setBaseMapVisible(visible){
  if(map.getLayer('satellite'))map.setLayoutProperty('satellite','visibility',visible?'visible':'none');
  if(!visible){
    fixedState.labels.visible=false;
    labelIds.forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility','none'));
    renderLayerCards();
  }
}
function wireFixed(el,onToggle,onOpacity,key){
  const st=fixedState[key],t=el.querySelector('input[type=checkbox]'),r=el.querySelector('.exact-range'),o=el.querySelector('output');
  t.checked=st.visible;r.value=Math.round(st.opacity*100);o.textContent=`${r.value}%`;el.classList.toggle('active',st.visible);
  t.addEventListener('change',()=>{st.visible=t.checked;onToggle(t.checked);el.classList.toggle('active',t.checked);});
  r.addEventListener('input',()=>{st.opacity=Number(r.value)/100;o.textContent=`${r.value}%`;onOpacity(st.opacity);});
}
function card(icon,name,desc,checked,opacity){
  const el=document.createElement('div');
  el.className='exact-layer-card expanded'+(checked?' active':'');
  el.innerHTML=`<div class="exact-layer-top"><span class="wb-layer-name">${icon} <b></b></span><label class="exact-switch"><input type="checkbox" ${checked?'checked':''}><em></em></label><input class="exact-range" type="range" min="0" max="100" value="${Math.round(opacity*100)}"><output>${Math.round(opacity*100)}%</output></div><p class="card-layer-desc"></p><div class="card-expand-content"></div>`;
  el.querySelector('b').textContent=name;
  el.querySelector('.wb-layer-name').title=desc?`${name}: ${desc}`:name;
  el.querySelector('.card-layer-desc').textContent=desc||'';
  el.querySelector('input[type=checkbox]').setAttribute('aria-label',`Toggle ${name}`);
  el.querySelector('.exact-range').setAttribute('aria-label',`Opacity of ${name}`);
  return el;
}

function el(html){const t=document.createElement('template');t.innerHTML=html.trim();return t.content.firstElementChild;}
function buildTools(){
  const box=document.querySelector('.wb-tools');box.innerHTML='';
  const tools=ARGS.tools||{};
  const launch=el('<button type="button" class="wb-run wb-api-open">Open RVT workspace</button>');
  launch.addEventListener('click',()=>rvtWorkspace.open());
  box.appendChild(launch);

  const views=tools.views||[];
  const rel=el(`<div class="wb-card"><h4>Relief types</h4><p class="wb-view-help"></p>
    <div class="wb-row"><select class="wide wb-view">${views.map(v=>`<option value="${v.id}">${v.name}</option>`).join('')}</select></div>
    <div class="wb-row wb-param" hidden><label class="wb-param-label" for="wb-relief-param"></label><input id="wb-relief-param" type="number" class="wb-param-value"><output class="wb-param-output" for="wb-relief-param" hidden></output></div>
    <button type="button" class="wb-run secondary" data-act="relief">Add to the map</button></div>`);
  const sel=rel.querySelector('.wb-view'),help=rel.querySelector('.wb-view-help'),prow=rel.querySelector('.wb-param');
  const paramInput=rel.querySelector('.wb-param-value'),paramOutput=rel.querySelector('.wb-param-output');
  paramInput.addEventListener('input',()=>{paramOutput.textContent=`${paramInput.value}°`;});
  const syncView=()=>{
    const v=views.find(x=>x.id===sel.value)||{};help.textContent=v.help||'';
    prow.hidden=!v.param;
    if(v.param){
      const slider=v.param.key==='azimuth';
      prow.classList.toggle('wb-param-slider',slider);
      rel.querySelector('.wb-param-label').textContent=v.param.label;
      paramInput.type=slider?'range':'number';
      paramInput.min=v.param.min;paramInput.max=v.param.max;paramInput.step=v.param.step;paramInput.value=v.param.value;
      paramOutput.hidden=!slider;paramOutput.textContent=`${paramInput.value}°`;
    }
  };
  sel.addEventListener('change',syncView);syncView();
  rel.querySelector('[data-act=relief]').addEventListener('click',()=>{const v=views.find(x=>x.id===sel.value)||{};send({action:'relief',replace:true,method:sel.value,value:v.param?Number(rel.querySelector('.wb-param-value').value):null});});
  box.appendChild(rel);

  const profiles=tools.cloud_profiles||[];
  const rendering=el(`<div class="wb-card"><h4>Terrain rendering</h4>
    <div class="wb-row"><label for="wb-cloud-mode">Mode</label><select id="wb-cloud-mode" class="wb-cloud">${profiles.map(p=>`<option value="${p.id}">${p.name}</option>`).join('')}</select></div>
    <p class="wb-cloud-help"></p><p>Rendering modes affect the interactive view. Exports use the source terrain.</p></div>`);
  rendering.querySelector('.wb-cloud').addEventListener('change',ev=>send({action:'view3d',cloud_key:ev.target.value}));
  document.querySelector('.wb-3d-tools').appendChild(rendering);

  const td=el(`<div class="wb-card"><h4>Export</h4><p>Save a terrain figure or download georeferenced 3D data.</p>
    <div class="wb-row"><label>High-quality image</label><select class="wb-fmt"><option value="pdf">PDF</option><option value="png">PNG</option></select></div>
    <details><summary>Image options</summary>
      <div class="wb-row"><label>Resolution (dpi)</label><select class="wb-dpi"><option>300</option><option>600</option><option>150</option></select></div>
      <div class="wb-row"><label>Width (mm)</label><input type="number" class="wb-wmm" value="190" min="40" max="500" step="5"></div>
      <div class="wb-row"><label>Camera direction (°)</label><input type="number" class="wb-az" value="-44" min="-180" max="180"></div>
      <div class="wb-row"><label>Camera height (°)</label><input type="number" class="wb-el" value="29" min="5" max="90"></div>
      <div class="wb-row"><label>Vertical exaggeration (0 = auto)</label><input type="number" class="wb-ve" value="0" min="0" max="20" step="0.1"></div>
      <div class="wb-row"><label><input type="checkbox" class="wb-sb" checked> Scale bar</label><label><input type="checkbox" class="wb-na" checked> North arrow</label></div>
    </details>
    <button type="button" class="wb-run secondary" data-act="figure">Download high-quality image</button>
    <button type="button" class="wb-run secondary" data-act="research">Download open 3D data (LAZ, PLY, glTF)</button></div>`);
  td.querySelector('[data-act=figure]').addEventListener('click',()=>{
    const top=(ARGS.layers||[]).find(l=>(shownLayers.get(l.id)||l).visible);
    send({action:'figure',fmt:td.querySelector('.wb-fmt').value,dpi:Number(td.querySelector('.wb-dpi').value),width_mm:Number(td.querySelector('.wb-wmm').value),
      azimuth:Number(td.querySelector('.wb-az').value),elevation:Number(td.querySelector('.wb-el').value),ve:Number(td.querySelector('.wb-ve').value),
      scale_bar:td.querySelector('.wb-sb').checked,north_arrow:td.querySelector('.wb-na').checked,drape:top?top.id:null});});
  td.querySelector('[data-act=research]').addEventListener('click',()=>send({action:'research'}));
  document.querySelector('.wb-3d-tools').appendChild(td);
}

function update(){
  for(const box of [messageBox,document.querySelector('.wb-3d-message')]){box.hidden=!ARGS.message;box.textContent=ARGS.message||'';box.classList.toggle('error',ARGS.message_level==='error');}
  if(pendingNonce&&ARGS.done_nonce===pendingNonce){pendingNonce=null;busy.hidden=true;document.querySelector('.wb-3d-busy').hidden=true;document.querySelectorAll('.wb-run').forEach(b=>b.disabled=false);document.querySelector('.wb-cloud').disabled=false;rvtWorkspace?.setBusy(false);}
  syncLayers();
  rvtWorkspace?.update(ARGS.rvt_api,ARGS.message);
  const cloud=document.querySelector('.wb-cloud');
  cloud.value=ARGS.cloud_key||'original';
  const profile=(ARGS.tools.cloud_profiles||[]).find(p=>p.id===cloud.value);
  document.querySelector('.wb-cloud-help').textContent=profile?profile.description:'';
  const dl=ARGS.download;
  if(dl&&dl.id!==lastDownload){lastDownload=dl.id;const bytes=Uint8Array.from(atob(dl.b64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:dl.mime}));const a=document.createElement('a');a.href=url;a.download=dl.filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);showToast(`Saved: ${dl.filename}`);}
  const v3=ARGS.view3d;
  if(v3&&v3.id!==last3d){last3d=v3.id;const m=document.querySelector('.wb-modal');m.querySelector('iframe').srcdoc=v3.html;m.hidden=false;}
}
function init(){rvtWorkspace=new window.RVTWorkspace(send);initMap();buildTools();wireControls();renderLayerCards();}

function distanceBetween(a,b){const r=x=>x*Math.PI/180,R=6371000,dLat=r(b[1]-a[1]),dLng=r(b[0]-a[0]);const q=Math.sin(dLat/2)**2+Math.cos(r(a[1]))*Math.cos(r(b[1]))*Math.sin(dLng/2)**2;return R*2*Math.atan2(Math.sqrt(q),Math.sqrt(1-q));}
function formatDistance(m){return m<1000?`${m<10?m.toFixed(1):Math.round(m)} m`:`${(m/1000).toFixed(2)} km`;}
function clearMarkers(){measurementMarkers.forEach(m=>m.remove());measurementMarkers=[];}
function addMarker(c,cls,text,anchor,offset){const e=document.createElement('div');e.className=cls;e.textContent=text;measurementMarkers.push(new maplibregl.Marker({element:e,anchor,offset}).setLngLat(c).addTo(map));}
function drawMeasure(){const src=map.getSource('measurement');if(!src)return;src.setData({type:'FeatureCollection',features:measurementPoints.length===2?[{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:measurementPoints}}]:[]});clearMarkers();measurementPoints.forEach((c,i)=>addMarker(c,'measure-point-marker',String(i+1),'center',[0,0]));if(measurementPoints.length===2)addMarker(measurementPoints[1],'measure-label measure-total',`Total: ${formatDistance(distanceBetween(measurementPoints[0],measurementPoints[1]))}`,'left',[14,0]);}
function setMeasure(a){if(a&&coordinateActive)setCoord(false);measurementActive=a;document.querySelector('[data-map-action=measure]').classList.toggle('active',a);map.getCanvas().style.cursor=a||coordinateActive?'crosshair':'';if(a){measurementPoints=[];drawMeasure();showToast('Select point 1 on the map');}}
function handleMeasurementClick(e){if(measurementPoints.length===2){measurementPoints=[];clearMarkers();}measurementPoints.push([e.lngLat.lng,e.lngLat.lat]);drawMeasure();showToast(measurementPoints.length===1?'Point 1 set. Select point 2':`Distance: ${formatDistance(distanceBetween(measurementPoints[0],measurementPoints[1]))}`);}
function utmBand(lat){if(lat<-80||lat>84)return'';return'CDEFGHJKLMNPQRSTUVWXX'[Math.min(19,Math.floor((lat+80)/8))];}
function utmZone(lon,lat){let z=Math.floor((lon+180)/6)+1;if(lat>=56&&lat<64&&lon>=3&&lon<12)z=32;if(lat>=72&&lat<84){if(lon>=0&&lon<9)z=31;else if(lon<21)z=33;else if(lon<33)z=35;else if(lon<42)z=37;}return Math.max(1,Math.min(60,z));}
function toUtm(lon,lat){const a=6378137,e2=0.00669438,k0=0.9996,zone=utmZone(lon,lat),lon0=((zone-1)*6-180+3)*Math.PI/180,phi=lat*Math.PI/180,lam=lon*Math.PI/180,ep2=e2/(1-e2),s=Math.sin(phi),c=Math.cos(phi),t=Math.tan(phi),N=a/Math.sqrt(1-e2*s*s),T=t*t,C=ep2*c*c,A=c*(lam-lon0),e4=e2*e2,e6=e4*e2;
  const M=a*((1-e2/4-3*e4/64-5*e6/256)*phi-(3*e2/8+3*e4/32+45*e6/1024)*Math.sin(2*phi)+(15*e4/256+45*e6/1024)*Math.sin(4*phi)-(35*e6/3072)*Math.sin(6*phi));
  const E=k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T*T+72*C-58*ep2)*A**5/120)+500000;let Nn=k0*(M+N*t*(A*A/2+(5-T+9*C+4*C*C)*A**4/24+(61-58*T+T*T+600*C-330*ep2)*A**6/720));if(lat<0)Nn+=1e7;
  return`UTM ${zone}${utmBand(lat)} ${Math.round(E)} m E ${Math.round(Nn)} m N`;}
function elevationAt(lon,lat){const g=ARGS.elevation;if(!g)return null;const[w,s,e,n]=g.bounds;if(lon<w||lon>e||lat<s||lat>n)return null;const col=Math.min(g.width-1,Math.floor((lon-w)/(e-w)*g.width)),row=Math.min(g.height-1,Math.floor((n-lat)/(n-s)*g.height));return g.values[row*g.width+col];}
function earthUrl(lon,lat){return`https://earth.google.com/web/search/${encodeURIComponent(`${lat.toFixed(6)},${lon.toFixed(6)}`)}`;}
function setCoord(a){if(a&&measurementActive)setMeasure(false);coordinateActive=a;document.querySelector('[data-map-action=coordinates]').classList.toggle('active',a);map.getCanvas().style.cursor=a||measurementActive?'crosshair':'';if(a)showToast('Select a point on the map');}
async function handleCoordinateClick(e){
  const lon=e.lngLat.lng,lat=e.lngLat.lat;selectedEarthPoint=[lon,lat];document.querySelector('[data-map-action=earth]').disabled=false;
  const utm=toUtm(lon,lat),z=elevationAt(lon,lat),hasZ=z!==null&&z!==undefined;
  const text=`${utm}${hasZ?` · elevation ${z.toFixed(2)} m`:''}`;
  let copied=false;try{await navigator.clipboard.writeText(text);copied=true;}catch(err){}
  coordinateMarker&&coordinateMarker.remove();
  const m=document.createElement('div');m.className='coordinate-utm-marker';m.textContent='⌾';
  const box=document.createElement('div');box.className='coordinate-utm-popup';
  const h=document.createElement('b');h.textContent='COORDINATES';const code=document.createElement('code');code.style.whiteSpace='pre';
  code.textContent=`${utm}\nlat ${lat.toFixed(6)}, lon ${lon.toFixed(6)}${hasZ?`\nelevation ${z.toFixed(2)} m`:''}`;
  const a=document.createElement('a');a.href=earthUrl(lon,lat);a.target='_blank';a.rel='noopener';a.textContent='Open in Google Earth';a.className='coordinate-earth-btn';
  box.append(h,code,a);
  coordinateMarker=new maplibregl.Marker({element:m,anchor:'center'}).setLngLat([lon,lat]).setPopup(new maplibregl.Popup({closeButton:true,offset:18,maxWidth:'310px'}).setDOMContent(box)).addTo(map);
  coordinateMarker.togglePopup();setCoord(false);showToast(copied?`Copied: ${text}`:text);
}
function wireControls(){
  if(!map)return;
  document.querySelector('[data-map-action=zoom-in]').addEventListener('click',()=>map.zoomIn());
  document.querySelector('[data-map-action=zoom-out]').addEventListener('click',()=>map.zoomOut());
  document.querySelector('[data-map-action=measure]').addEventListener('click',()=>setMeasure(!measurementActive));
  document.querySelector('[data-map-action=coordinates]').addEventListener('click',()=>setCoord(!coordinateActive));
  document.querySelector('[data-map-action=earth]').addEventListener('click',()=>{if(selectedEarthPoint)window.open(earthUrl(selectedEarthPoint[0],selectedEarthPoint[1]),'_blank','noopener');});
  const tb=document.querySelector('.terrain-toggle');const label=()=>{tb.querySelector('small').textContent=terrainEnabled?'Relief on':'Flat view';};
  tb.addEventListener('click',()=>{terrainEnabled=!terrainEnabled;map.setTerrain(terrainEnabled?{source:'terrain',exaggeration:1.35}:null);map.easeTo({pitch:terrainEnabled?50:0,bearing:terrainEnabled?-12:0,duration:700});label();});
  document.querySelector('.panel-handle').addEventListener('click',ev=>{const c=document.querySelector('.detector-map').classList.toggle('panel-collapsed');ev.currentTarget.textContent=c?'‹':'›';ev.currentTarget.title=c?'Show tools':'Hide tools';ev.currentTarget.setAttribute('aria-expanded',String(!c));});
  document.querySelector('.map-fullscreen').addEventListener('click',()=>{const e=document.querySelector('.detector-map');if(!document.fullscreenElement&&e.requestFullscreen)e.requestFullscreen();else if(document.exitFullscreen)document.exitFullscreen();setTimeout(()=>map.resize(),300);});
  document.querySelector('.wb-modal-close').addEventListener('click',()=>{const m=document.querySelector('.wb-modal');m.hidden=true;m.querySelector('iframe').srcdoc='';});
}
})();
