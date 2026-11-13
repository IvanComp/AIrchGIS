/* AIrchGIS map workbench.
   Map interface adapted from DetectorLab (https://github.com/IvanComp/DetectorLab), Apache License 2.0:
   satellite base, 3D terrain, place names, measure, UTM coordinates, Google Earth link, panel and cards.
   Tools, layers, downloads and the 3D view talk to Python through the Streamlit component protocol. */
(function(){
// ---------------------------------------------------------------- Streamlit protocol (no build step)
function post(type,data){window.parent.postMessage(Object.assign({isStreamlitMessage:true,type},data),'*');}
function setValue(value){post('streamlit:setComponentValue',{value,dataType:'json'});}
function setHeight(h){post('streamlit:setFrameHeight',{height:h});}

let ARGS=null,map=null,initialized=false,pendingNonce=null,lastDownload=null,last3d=null,nonceCounter=0;
const shownLayers=new Map();      // id -> {visible, opacity} as set by the user
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

// ---------------------------------------------------------------- map
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
    if(bounds){const el=map.getContainer();const right=Math.min(360,el.clientWidth*.42);
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
}
function mapReady(){return map&&map.getLayer&&map.getLayer('measurement-line');}

// ---------------------------------------------------------------- layers (Python -> map)
const mapLayerIds=new Map();      // layer id -> image url, to know when to replace
function syncLayers(){
  if(!mapReady())return;
  const layers=ARGS.layers||[];
  const wanted=new Set(layers.map(l=>l.id));
  [...mapLayerIds.keys()].forEach(id=>{if(!wanted.has(id)){if(map.getLayer('wb-'+id))map.removeLayer('wb-'+id);if(map.getSource('wb-'+id))map.removeSource('wb-'+id);mapLayerIds.delete(id);shownLayers.delete(id);}});
  // bottom to top: the first layer in the list is on top
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
  (ARGS.layers||[]).forEach(l=>{
    const st=shownLayers.get(l.id)||{visible:l.visible,opacity:l.opacity};
    const el=card('◉',l.name,l.description,st.visible,st.opacity);
    const t=el.querySelector('input[type=checkbox]'),r=el.querySelector('.exact-range'),o=el.querySelector('output');
    t.addEventListener('change',()=>{st.visible=t.checked;shownLayers.set(l.id,st);map.setLayoutProperty('wb-'+l.id,'visibility',t.checked?'visible':'none');el.classList.toggle('active',t.checked);});
    r.addEventListener('input',()=>{st.opacity=Number(r.value)/100;shownLayers.set(l.id,st);o.textContent=`${r.value}%`;map.setPaintProperty('wb-'+l.id,'raster-opacity',st.opacity);});
    const tools=document.createElement('div');tools.className='layer-tools';
    tools.innerHTML='<button type="button" data-a="contrast" title="Adaptive histogram equalization, display only">Stronger contrast</button><button type="button" data-a="download">GeoTIFF</button><button type="button" data-a="remove">Remove</button>';
    tools.querySelector('[data-a=contrast]').addEventListener('click',()=>send({action:'contrast',layer:l.id}));
    tools.querySelector('[data-a=download]').addEventListener('click',()=>send({action:'download',layer:l.id}));
    tools.querySelector('[data-a=remove]').addEventListener('click',()=>send({action:'remove',layer:l.id}));
    el.querySelector('.card-expand-content').appendChild(tools);
    box.appendChild(el);
  });
  // fixed layers: place names and satellite
  const lab=card('⌖','Place names','OpenStreetMap place names.',true,1);
  wireFixed(lab,v=>labelIds.forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',v?'visible':'none')),o=>labelIds.forEach(id=>map.getLayer(id)&&map.setPaintProperty(id,'text-opacity',o)),'labels');
  box.appendChild(lab);
  const sat=card('▦','Satellite','Base map: satellite imagery.',true,1);
  wireFixed(sat,v=>map.setLayoutProperty('satellite','visibility',v?'visible':'none'),o=>map.setPaintProperty('satellite','raster-opacity',o),'satellite');
  box.appendChild(sat);
}
const fixedState={labels:{visible:true,opacity:1},satellite:{visible:true,opacity:1}};
function wireFixed(el,onToggle,onOpacity,key){
  const st=fixedState[key],t=el.querySelector('input[type=checkbox]'),r=el.querySelector('.exact-range'),o=el.querySelector('output');
  t.checked=st.visible;r.value=Math.round(st.opacity*100);o.textContent=`${r.value}%`;el.classList.toggle('active',st.visible);
  t.addEventListener('change',()=>{st.visible=t.checked;onToggle(t.checked);el.classList.toggle('active',t.checked);});
  r.addEventListener('input',()=>{st.opacity=Number(r.value)/100;o.textContent=`${r.value}%`;onOpacity(st.opacity);});
}
function card(icon,name,desc,checked,opacity){
  const el=document.createElement('div');
  el.className='exact-layer-card'+(checked?' active':'');
  el.innerHTML=`<div class="exact-layer-top"><span>${icon} <b></b></span><button class="card-expand" type="button" aria-expanded="false" title="Opacity and options">›</button><label class="exact-switch"><input type="checkbox" ${checked?'checked':''}><em></em></label></div><p class="card-layer-desc"></p><div class="card-expand-content"><div class="exact-opacity"><span>Opacity</span><output>${Math.round(opacity*100)}%</output></div><input class="exact-range" type="range" min="0" max="100" value="${Math.round(opacity*100)}"></div>`;
  el.querySelector('b').textContent=name;el.querySelector('.card-layer-desc').textContent=desc||'';
  el.querySelector('.card-expand').addEventListener('click',ev=>{const open=el.classList.toggle('expanded');ev.currentTarget.textContent=open?'⌄':'›';});
  return el;
}

// ---------------------------------------------------------------- tools panel (map -> Python)
function el(html){const t=document.createElement('template');t.innerHTML=html.trim();return t.content.firstElementChild;}
function buildTools(){
  const box=document.querySelector('.wb-tools');box.innerHTML='';
  const tools=ARGS.tools||{};
  // 1. recommended
  const best=el(`<div class="wb-card primary"><h4>Improve and find the best view</h4><p>Recommended. Cleans the terrain, compares many relief views and shows the clearest one for the size of your features.</p>
    <div class="wb-row"><label>Width of the features (m)</label><input type="number" class="wb-width" min="0.1" step="0.5" value="${tools.width||4}"></div>
    <details><summary>Known sites (optional)</summary><p>CSV with lon/lat, GeoJSON, GeoPackage, zipped Shapefile or KML. Each view gets an AUC at your sites.</p><input type="file" class="wb-sites" accept=".csv,.txt,.geojson,.json,.gpkg,.zip,.kml"></details>
    <button type="button" class="wb-run" data-act="best_view">Improve and find the best view</button></div>`);
  best.querySelector('[data-act=best_view]').addEventListener('click',()=>send({action:'best_view',width:Number(best.querySelector('.wb-width').value)}));
  best.querySelector('.wb-sites').addEventListener('change',ev=>{const f=ev.target.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>send({action:'sites',filename:f.name,b64:String(rd.result).split(',')[1]});rd.readAsDataURL(f);});
  box.appendChild(best);
  // 2. relief views
  const views=tools.views||[];
  const rel=el(`<div class="wb-card"><h4>Relief views</h4><p class="wb-view-help"></p>
    <div class="wb-row"><select class="wide wb-view">${views.map(v=>`<option value="${v.id}">${v.name}</option>`).join('')}</select></div>
    <div class="wb-row wb-param" hidden><label class="wb-param-label"></label><input type="number" class="wb-param-value"></div>
    <button type="button" class="wb-run secondary" data-act="relief">Add to the map</button></div>`);
  const sel=rel.querySelector('.wb-view'),help=rel.querySelector('.wb-view-help'),prow=rel.querySelector('.wb-param');
  const syncView=()=>{const v=views.find(x=>x.id===sel.value)||{};help.textContent=v.help||'';if(v.param){prow.hidden=false;rel.querySelector('.wb-param-label').textContent=v.param.label;const i=rel.querySelector('.wb-param-value');i.min=v.param.min;i.max=v.param.max;i.step=v.param.step;i.value=v.param.value;}else prow.hidden=true;};
  sel.addEventListener('change',syncView);syncView();
  rel.querySelector('[data-act=relief]').addEventListener('click',()=>{const v=views.find(x=>x.id===sel.value)||{};send({action:'relief',method:sel.value,value:v.param?Number(rel.querySelector('.wb-param-value').value):null});});
  box.appendChild(rel);
  // 3. fused view
  const fu=el(`<div class="wb-card"><h4>Fused view</h4><p>Blends the four best views with weights that make features stand out most. If the blend is not clearer, the best view is kept.</p><button type="button" class="wb-run secondary" data-act="fused">Build the fused view</button></div>`);
  fu.querySelector('[data-act=fused]').addEventListener('click',()=>send({action:'fused',width:Number(document.querySelector('.wb-width').value)}));
  box.appendChild(fu);
  // 4. 3D
  const td=el(`<div class="wb-card"><h4>3D</h4><p>Look at your terrain in 3D, save a high-quality image for a paper, or export open 3D data.</p>
    <button type="button" class="wb-run secondary" data-act="view3d">Open the 3D view of my terrain</button>
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
  td.querySelector('[data-act=view3d]').addEventListener('click',()=>send({action:'view3d'}));
  td.querySelector('[data-act=figure]').addEventListener('click',()=>{
    const top=(ARGS.layers||[]).find(l=>(shownLayers.get(l.id)||l).visible);
    send({action:'figure',fmt:td.querySelector('.wb-fmt').value,dpi:Number(td.querySelector('.wb-dpi').value),width_mm:Number(td.querySelector('.wb-wmm').value),
      azimuth:Number(td.querySelector('.wb-az').value),elevation:Number(td.querySelector('.wb-el').value),ve:Number(td.querySelector('.wb-ve').value),
      scale_bar:td.querySelector('.wb-sb').checked,north_arrow:td.querySelector('.wb-na').checked,drape:top?top.id:null});});
  td.querySelector('[data-act=research]').addEventListener('click',()=>send({action:'research'}));
  box.appendChild(td);
  // 5. details
  const de=el(`<div class="wb-card wb-details"><details><summary>Details: measures, all views, script</summary><div class="wb-details-body"><p>Run <b>Improve and find the best view</b> to see the measures.</p></div>
    <button type="button" class="wb-run secondary" data-act="script">Download the steps as a Python script</button></details></div>`);
  de.querySelector('[data-act=script]').addEventListener('click',()=>send({action:'script'}));
  box.appendChild(de);
  document.querySelector('[data-act=load_another]').addEventListener('click',()=>send({action:'load_another'}));
}
function fmt(v){if(v===null||v===undefined)return'';if(typeof v!=='number')return String(v);return Math.abs(v)>=100||v===0?v.toFixed(0):Number(v.toPrecision(3)).toString();}
function renderDetails(){
  const d=ARGS.details||{};const body=document.querySelector('.wb-details-body');if(!body||!d.cleaning)return;
  let h='<p>Cleaning: before and after</p><table class="wb-table"><tr><th>Measure</th><th>Before</th><th>After</th></tr>';
  d.cleaning.forEach(r=>{h+=`<tr><td>${r.measure}</td><td class="num">${fmt(r.before)}</td><td class="num">${fmt(r.after)}</td></tr>`;});
  h+='</table><ul class="wb-notes">'+(d.notes||[]).map(n=>`<li>${n.replace(/</g,'&lt;')}</li>`).join('')+'</ul>';
  h+='<p>All views, best first</p><table class="wb-table"><tr><th>View</th><th>Visibility</th>'+((d.ranking||[]).some(r=>'auc' in r)?'<th>AUC</th>':'')+'</tr>';
  (d.ranking||[]).forEach(r=>{h+=`<tr><td>${r.view}</td><td class="num">${fmt(r.visibility)}</td>${'auc' in r?`<td class="num">${fmt(r.auc)}</td>`:''}</tr>`;});
  h+='</table>'+(d.explanation?`<p>${d.explanation.replace(/</g,'&lt;')}</p>`:'');
  body.innerHTML=h;
}

// ---------------------------------------------------------------- updates from Python
function update(){
  document.querySelector('.wb-file-name').textContent=ARGS.name||'';
  if(ARGS.message){messageBox.hidden=false;messageBox.textContent=ARGS.message;messageBox.classList.toggle('error',/^Not completed|cannot|refused/i.test(ARGS.message));}else messageBox.hidden=true;
  if(pendingNonce&&ARGS.done_nonce===pendingNonce){pendingNonce=null;busy.hidden=true;document.querySelectorAll('.wb-run').forEach(b=>b.disabled=false);}
  syncLayers();renderDetails();
  const dl=ARGS.download;
  if(dl&&dl.id!==lastDownload){lastDownload=dl.id;const bytes=Uint8Array.from(atob(dl.b64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:dl.mime}));const a=document.createElement('a');a.href=url;a.download=dl.filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);showToast(`Saved: ${dl.filename}`);}
  const v3=ARGS.view3d;
  if(v3&&v3.id!==last3d){last3d=v3.id;const m=document.querySelector('.wb-modal');m.querySelector('iframe').srcdoc=v3.html;m.hidden=false;}
}
function init(){initMap();buildTools();wireControls();renderLayerCards();}

// ---------------------------------------------------------------- map tools (from DetectorLab)
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
  document.querySelector('.panel-handle').addEventListener('click',ev=>{const c=document.querySelector('.detector-map').classList.toggle('panel-collapsed');ev.currentTarget.textContent=c?'‹':'›';});
  document.querySelector('.map-fullscreen').addEventListener('click',()=>{const e=document.querySelector('.detector-map');if(!document.fullscreenElement&&e.requestFullscreen)e.requestFullscreen();else if(document.exitFullscreen)document.exitFullscreen();setTimeout(()=>map.resize(),300);});
  document.querySelector('.wb-modal-close').addEventListener('click',()=>{const m=document.querySelector('.wb-modal');m.hidden=true;m.querySelector('iframe').srcdoc='';});
}
})();
