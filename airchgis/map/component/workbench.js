(function(){

function post(type,data){window.parent.postMessage(Object.assign({isStreamlitMessage:true,type},data),'*');}
function setValue(value){post('streamlit:setComponentValue',{value,dataType:'json'});}
function setHeight(h){post('streamlit:setFrameHeight',{height:h});}
function fitHeight(){let height=ARGS?.height||760;try{const top=window.frameElement.getBoundingClientRect().top;height=Math.min(height,Math.max(420,window.parent.innerHeight-Math.max(0,top)-16));}catch{}setHeight(height);}

let ARGS=null,map=null,initialized=false,pendingNonce=null,lastDownload=null,last3d=null,nonceCounter=0;
let rvtWorkspace=null,captureRequest=null,captureTimeout=null,viewerReady=false;
const display3D={background:'none',contrast:65,brightness:40,verticalExaggeration:1,reliefOpacity:100,elevationColor:35};
let automaticExaggeration=1;
function update3DDisplay(){const toolbar=document.querySelector('.wb-3d-toolbar');if(!toolbar)return;display3D.elevationColor=Number(toolbar.querySelector('.wb-elevation-color-3d').value);toolbar.querySelector('.wb-elevation-color-readout').textContent=Math.round(display3D.elevationColor)+'%';display3D.contrast=Number(toolbar.querySelector('.wb-contrast-3d').value);display3D.brightness=Number(toolbar.querySelector('.wb-brightness-3d').value);display3D.reliefOpacity=Number(toolbar.querySelector('.wb-relief-opacity-3d').value);toolbar.querySelector('.wb-relief-opacity-readout').textContent=Math.round(display3D.reliefOpacity)+'%';toolbar.querySelector('.wb-contrast-readout').textContent=Math.round(display3D.contrast)+'%';toolbar.querySelector('.wb-brightness-readout').textContent=Math.round(display3D.brightness)+'%';const ve=display3D.verticalExaggeration||automaticExaggeration;toolbar.querySelector('.wb-exaggeration-readout').textContent=Math.abs(ve-automaticExaggeration)<.00001?'Auto':'×'+Number(ve).toFixed(2);if(viewerReady)document.querySelector('.wb-modal iframe').contentWindow.postMessage({type:'airchgis:3d-options',...display3D,controlPanelWidth:0,verticalExaggeration:display3D.verticalExaggeration||automaticExaggeration},'*');}
function sync3DButtons(){for(const b of document.querySelectorAll('[data-3d-export]'))b.disabled=Boolean(pendingNonce||captureRequest)||(['pdf','png'].includes(b.dataset['3dExport'])&&!viewerReady);}
function capture3D(format){if(pendingNonce||captureRequest||!viewerReady)return;const id=String(Date.now())+'-'+(++nonceCounter);captureRequest={id,format};document.querySelector('.wb-3d-busy').hidden=false;document.querySelector('.wb-3d-busy').textContent='Preparing '+format.toUpperCase()+'…';sync3DButtons();document.querySelector('.wb-modal iframe').contentWindow.postMessage({type:'airchgis:capture3d',id},'*');captureTimeout=setTimeout(()=>{captureRequest=null;document.querySelector('.wb-3d-busy').hidden=true;showToast('Image export timed out. Try again.');sync3DButtons();},60000);}
window.addEventListener('message',ev=>{const frame=document.querySelector('.wb-modal iframe');if(!frame||ev.source!==frame.contentWindow)return;const d=ev.data||{};if(d.type==='airchgis:3d-ready'){viewerReady=true;const tint=document.querySelector('.wb-elevation-color-3d');tint.disabled=!d.elevationColorAvailable;tint.closest('.wb-elevation-color-row').hidden=!d.elevationColorAvailable;const opacity=document.querySelector('.wb-relief-opacity-3d');opacity.disabled=!d.basemapAvailable;opacity.parentElement.title=d.basemapAvailable?'100% relief; 0% satellite imagery draped on the terrain.':'Satellite imagery could not be loaded. Reopen the 3D view to retry.';if(!d.basemapAvailable){display3D.reliefOpacity=100;opacity.value=100;}automaticExaggeration=Math.max(1,Number(d.verticalExaggeration)||1);if(display3D.verticalExaggeration!==null)display3D.verticalExaggeration=Math.min(automaticExaggeration,Math.max(1,display3D.verticalExaggeration));const slider=document.querySelector('.wb-exaggeration-3d');slider.max=automaticExaggeration;slider.value=display3D.verticalExaggeration||automaticExaggeration;slider.disabled=automaticExaggeration===1;sync3DButtons();update3DDisplay();}else if(d.type==='airchgis:3d-capture'&&captureRequest&&d.id===captureRequest.id){const request=captureRequest;captureRequest=null;clearTimeout(captureTimeout);if(d.error){document.querySelector('.wb-3d-busy').hidden=true;showToast(d.error);sync3DButtons();return;}send({action:'capture3d',fmt:request.format,b64:d.png.split(',')[1],view:d.view});}});
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
  rvtWorkspace?.setBusy(true,event.action);
  sync3DButtons();
  document.querySelector('.wb-3d-busy').hidden=document.querySelector('.wb-modal').hidden;
  document.querySelector('.wb-3d-busy').textContent=event.action==='view3d'?(event.cloud_key==='ai_relief'&&!ARGS.ai3d?.available?'Analysing terrain for AI Relief…':'Preparing 3D view…'):'Preparing export…';
  document.querySelector('.wb-cloud').disabled=true;
  document.querySelectorAll('.wb-run').forEach(b=>b.disabled=true);
  setValue(event);
}

window.addEventListener('message',ev=>{
  const d=ev.data||{};
  if(d.type!=='streamlit:render')return;
  ARGS=(d.args&&d.args.args)||d.args||{};
  if(!initialized){initialized=true;fitHeight();init();}
  update();
});
try{window.parent.addEventListener('resize',fitHeight);}catch{window.addEventListener('resize',fitHeight);}
post('streamlit:componentReady',{apiVersion:1});

let terrainEnabled=true,measurementActive=false,coordinateActive=false,measurementPoints=[],measurementMarkers=[],coordinateMarker=null;
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
    if(bounds){const el=map.getContainer();const right=document.querySelector('.detector-map').classList.contains('rvt-open')?24:document.querySelector('.exact-layer-panel').getBoundingClientRect().width+24;
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
      map.addLayer({id:'wb-'+l.id,type:'raster',source:'wb-'+l.id,paint:{'raster-opacity':l.opacity,'raster-fade-duration':0,'raster-resampling':'nearest'}},map.getLayer('locality-cities')?'locality-cities':'measurement-line');
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
  // pre-processing: what was done to reach the terrain on the map, and the choices to do it again
  const prep=el(`<div class="wb-card primary wb-prep"><h4>Pre-processing</h4><p>From your file to the terrain on the map. Each step is recorded in the script.</p>
    <ol class="wb-prep-steps"></ol>
    <details class="wb-prep-options"><summary>Change the pre-processing</summary>
      <div class="wb-pc-only">
        <div class="wb-row"><label for="wb-pc-method">Interpolation</label><select id="wb-pc-method" class="wb-pc-method">
          <option value="tin">TIN (linear)</option><option value="idw">IDW</option><option value="mean">Mean per cell</option><option value="min">Lowest point</option></select></div>
        <div class="wb-row"><label for="wb-pc-cell">Cell size (m, 0 = suggested)</label><input id="wb-pc-cell" type="number" class="wb-pc-cell" min="0" step="0.25" value="0"></div>
        <div class="wb-row"><label><input type="checkbox" class="wb-pc-ground" checked> Ground points only (class 2)</label></div>
        <div class="wb-row"><label><input type="checkbox" class="wb-pc-outliers" checked> Remove isolated points</label></div>
      </div>
      <div class="wb-raster-only">
        <div class="wb-row"><label for="wb-dtm-cell">Resample to (m, 0 = keep)</label><input id="wb-dtm-cell" type="number" class="wb-dtm-cell" min="0" step="0.5" value="0"></div>
      </div>
      <div class="wb-row"><label><input type="checkbox" class="wb-fill" checked> Fill small voids inside the survey</label></div>
      <button type="button" class="wb-run secondary" data-act="reprocess">Run the pre-processing again</button>
    </details></div>`);
  prep.querySelector('[data-act=reprocess]').addEventListener('click',()=>{
    const fill=prep.querySelector('.wb-fill').checked;
    if((ARGS.prep||{}).kind==='points'){
      send({action:'regrid',method:prep.querySelector('.wb-pc-method').value,cell_m:Number(prep.querySelector('.wb-pc-cell').value)||0,
        ground_only:prep.querySelector('.wb-pc-ground').checked,remove_outliers:prep.querySelector('.wb-pc-outliers').checked,fill_voids:fill});
    }else send({action:'prepare',fill_voids:fill,cell_m:Number(prep.querySelector('.wb-dtm-cell').value)||0});
  });
  box.appendChild(prep);
  const reso=el(`<div class="wb-card wb-reso"><h4>Resolution check</h4><p>Can features of this width be seen at the cell size of your terrain?</p>
    <div class="wb-row"><label for="wb-reso-width">Feature width (m)</label><input id="wb-reso-width" type="number" class="wb-reso-width" min="0.1" step="0.5" value="2"></div>
    <p class="wb-reso-result" hidden></p>
    <button type="button" class="wb-run secondary" data-act="resolution">Check</button></div>`);
  reso.querySelector('[data-act=resolution]').addEventListener('click',()=>send({action:'resolution',width:Number(reso.querySelector('.wb-reso-width').value)}));
  box.appendChild(reso);
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

  const ai=el(`<div class="wb-card wb-ai"><h4>Find hidden features (AI)</h4><p>Reads several RVT views together and marks the places whose relief does not look like the rest of this terrain. They are priorities to check, not sites: modern features and data artefacts show up too.</p>
    <div class="wb-row"><label for="wb-ai-width">Feature width (m)</label><input id="wb-ai-width" type="number" class="wb-ai-width" min="0.5" step="0.5" value="5"></div>
    <div class="wb-row"><label for="wb-ai-sens">Sensitivity</label><select id="wb-ai-sens" class="wb-ai-sens"><option value="low">Low · check up to 0.5% of the area</option><option value="medium" selected>Medium · up to 1%</option><option value="high">High · up to 2%</option></select></div>
    <details class="wb-ai-advanced"><summary>Advanced</summary>
      <div class="wb-row"><label><input type="checkbox" class="wb-ai-larger" checked> Also look for larger structures (3 × the width)</label></div>
      <div class="wb-row"><label><input type="checkbox" class="wb-ai-water" checked> Leave out level water surfaces (lakes, sea)</label></div>
      <div class="wb-row"><label for="wb-ai-water-tilt">Water: largest tilt (°)</label><input id="wb-ai-water-tilt" type="number" class="wb-ai-water-tilt" min="0.05" max="5" step="0.05" value="0.4"></div>
      <div class="wb-row"><label for="wb-ai-water-area">Water: smallest area (m²)</label><input id="wb-ai-water-area" type="number" class="wb-ai-water-area" min="100" step="500" value="5000"></div>
      <div class="wb-row"><label for="wb-ai-seed">Random seed</label><input id="wb-ai-seed" type="number" class="wb-ai-seed" min="0" step="1" value="0"></div>
      <div class="wb-row"><label><input type="checkbox" class="wb-ai-compare" checked> With known features, also compare with VAT and e3MSTP</label></div>
      <div class="wb-row"><label for="wb-ai-sites">Known features (CSV or GeoJSON)</label><input id="wb-ai-sites" type="file" class="wb-ai-sites" accept=".csv,.txt,.geojson,.json,.gpkg,.kml,.zip"></div>
      <p class="wb-ai-sites-state"></p>
    </details>
    <button type="button" class="wb-run" data-act="ai">Find hidden features</button>
    <div class="wb-ai-result" hidden>
      <p class="wb-ai-note"></p>
      <div class="wb-ai-legend"><span>usual</span><i></i><span>unusual</span></div>
      <div class="wb-ai-kinds"><span><b style="background:#ff7f0e"></b>ring</span><span><b style="background:#2ca02c"></b>curved line</span><span><b style="background:#d62728"></b>compact</span><span><b style="background:#7f7f7f"></b>straight line</span><span><b style="background:#8c8c8c;opacity:.5"></b>not analysed</span></div>
      <button type="button" class="wb-ai-compare-btn secondary">Before / after</button>
      <p class="wb-ai-known"></p>
      <ol class="wb-ai-areas"></ol>
    </div></div>`);
  ai.querySelector('[data-act=ai]').addEventListener('click',()=>send({action:'unusual_relief',...aiSettings()}));
  ai.querySelector('.wb-ai-sites').addEventListener('change',ev=>{const f=ev.target.files[0];if(!f)return;const rd=new FileReader();
    rd.onload=()=>send({action:'sites',filename:f.name,b64:String(rd.result).split(',')[1]});rd.readAsDataURL(f);});
  ai.querySelector('.wb-ai-compare-btn').addEventListener('click',()=>{
    const ids=['ai_score','ai_areas','ai_excluded'].filter(id=>map.getLayer('wb-'+id));if(!ids.length)return;
    const show=!(shownLayers.get(ids[0])||{visible:true}).visible;
    ids.forEach(id=>{const st=shownLayers.get(id)||{visible:true,opacity:1};st.visible=show;shownLayers.set(id,st);map.setLayoutProperty('wb-'+id,'visibility',show?'visible':'none');});
    renderLayerCards();showToast(show?'After: with the AI layer':'Before: relief view only');});
  box.appendChild(ai);

  const profiles=tools.cloud_profiles||[];
  const toolbar=document.querySelector('.wb-3d-toolbar');
  toolbar.innerHTML=`<h4>View settings</h4><div class="wb-3d-look"><label class="wb-3d-mode">View <select id="wb-cloud-mode" class="wb-cloud" aria-label="Terrain rendering">${profiles.map(p=>`<option value="${p.id}">${p.name}</option>`).join('')}</select><span class="wb-cloud-help"></span><span class="wb-3d-ai-legend" aria-label="AI Relief anomaly score: usual to unusual" hidden><span>Usual</span><i aria-hidden="true"></i><span>Unusual</span></span></label><label class="wb-3d-adjust">Relief view <input class="wb-relief-opacity-3d" aria-label="3D Relief view opacity" type="range" min="0" max="100" step="1" value="${display3D.reliefOpacity}" disabled><output class="wb-relief-opacity-readout">${display3D.reliefOpacity}%</output></label><label class="wb-3d-adjust wb-elevation-color-row" title="0% grayscale relief; add elevation colors while preserving the grayscale luminance.">Elevation color <input class="wb-elevation-color-3d" aria-label="Elevation color" type="range" min="0" max="100" step="1" value="${display3D.elevationColor}" disabled><output class="wb-elevation-color-readout">${display3D.elevationColor}%</output></label><label class="wb-3d-adjust">Contrast <input class="wb-contrast-3d" aria-label="3D contrast" type="range" min="0" max="100" step="1" value="${display3D.contrast}"><output class="wb-contrast-readout">65%</output></label><label class="wb-3d-adjust">Brightness <input class="wb-brightness-3d" aria-label="3D brightness" type="range" min="0" max="100" step="1" value="${display3D.brightness}"><output class="wb-brightness-readout">40%</output></label></div><div class="wb-3d-elevation"><div class="wb-3d-setting-title"><span class="wb-boost-title">Vertical Boost <span class="wb-boost-info"><button type="button" class="wb-boost-help" aria-label="About Vertical Boost" aria-describedby="wb-boost-tooltip">?</button><span id="wb-boost-tooltip" class="wb-boost-tooltip" role="tooltip">Increasing this value stretches terrain heights and distorts its proportions. This can help reveal subtle height differences. ×1 preserves true proportions; the original elevation data remain unchanged.</span></span></span><output class="wb-exaggeration-readout">×1.00</output></div><div class="wb-3d-elevation-range"><button type="button" class="wb-true-scale" title="Show true proportions">×1</button><input class="wb-exaggeration-3d" aria-label="Vertical Boost" type="range" min="1" max="${automaticExaggeration}" step="any" value="${display3D.verticalExaggeration||automaticExaggeration}"><button type="button" class="wb-auto-scale" title="Use the automatic exaggeration calculated for this terrain">Auto</button></div></div><div class="wb-3d-downloads" role="group" aria-label="Export as"><h4>EXPORT AS</h4><button type="button" data-3d-export="pdf" title="High-resolution PDF of the current view">PDF</button><button type="button" data-3d-export="png" title="High-resolution PNG of the current view">PNG</button><button type="button" data-3d-export="laz" title="Full-resolution georeferenced point cloud">LAZ</button><button type="button" data-3d-export="ply" title="Full-resolution point data">PLY</button><button type="button" data-3d-export="glb" title="Full-resolution terrain mesh">glTF</button></div>`;
  const exaggeration=toolbar.querySelector('.wb-exaggeration-3d');
  exaggeration.addEventListener('input',()=>{display3D.verticalExaggeration=Number(exaggeration.value);update3DDisplay();});
  toolbar.querySelector('.wb-true-scale').onclick=()=>{display3D.verticalExaggeration=1;exaggeration.value=1;update3DDisplay();};
  toolbar.querySelector('.wb-auto-scale').onclick=()=>{display3D.verticalExaggeration=null;exaggeration.value=automaticExaggeration;update3DDisplay();};
  for(const element of toolbar.querySelectorAll('.wb-contrast-3d,.wb-brightness-3d,.wb-relief-opacity-3d,.wb-elevation-color-3d'))element.addEventListener('input',update3DDisplay);
  const view3dEvent=()=>({action:'view3d',cloud_key:toolbar.querySelector('.wb-cloud').value,ai_show:true,ai_ve:false,...aiSettings()});
  toolbar.querySelector('.wb-cloud').addEventListener('change',()=>{
    const ev=view3dEvent();
    if(ev.cloud_key==='ai_relief'&&!(ARGS.ai3d||{}).available){
      setTimeout(()=>{const b=document.querySelector('.wb-3d-busy');if(b){b.hidden=false;b.textContent='Finding unusual relief… about 10–30 s';}},0);
    }
    send(ev);
  });
  for(const button of toolbar.querySelectorAll('[data-3d-export]'))button.onclick=()=>{
    const format=button.dataset['3dExport'];
    if(format==='pdf'||format==='png')capture3D(format);else send({action:'research',format});
  };
  const downloads=toolbar.querySelector('.wb-3d-downloads');
  const icons={pdf:'<path d="M6 2h8l4 4v8M14 2v5h5M6 2v12M5 18h14M12 14v8m-3-3 3 3 3-3"/>',png:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>',laz:'<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',ply:'<path d="m12 3 9 17H3L12 3Zm0 0v11m-9 6 9-6 9 6"/><circle cx="12" cy="14" r="1"/>',glb:'<path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm0 10 9-5M12 12 3 7m9 5v10"/>'};
  for(const button of downloads.querySelectorAll('button')){
    const label=button.textContent,format=button.dataset['3dExport'];
    button.setAttribute('aria-label','Download '+label);
    button.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[format]}</svg><span>${label}</span>`;
  }
  document.querySelector('.wb-modal-content').appendChild(downloads);
  sync3DButtons();
  const sc=el(`<div class="wb-card"><h4>Script</h4><p>Every step of this session (pre-processing, relief views, exports) with its settings and input checksums, as a Python script that repeats it.</p>
    <button type="button" class="wb-run secondary" data-act="script">Download the steps as a Python script</button></div>`);
  sc.querySelector('[data-act=script]').addEventListener('click',()=>send({action:'script'}));
  box.appendChild(sc);
  const credit=el('<p class="wb-credit">Visualizations computed with <a href="https://github.com/EarthObservation/RVT_py" target="_blank" rel="noopener">RVT_py</a> (Relief Visualization Toolbox, ZRC SAZU and University of Ljubljana).</p>');
  box.appendChild(credit);
}
function fmtMeasure(v){if(typeof v!=='number')return String(v);if(Math.abs(v)>=1000)return v.toLocaleString('en');return Number(v.toPrecision(3)).toString();}
function renderPrep(){
  const p=ARGS.prep||{};const list=document.querySelector('.wb-prep-steps');if(!list)return;
  list.innerHTML='';
  (p.steps||[]).forEach(s=>{const li=document.createElement('li');const n=document.createElement('span');n.textContent=s.note;li.appendChild(n);
    const m=Object.entries(s.measures||{});if(m.length){const small=document.createElement('small');small.textContent=m.map(([k,v])=>`${k.replace(/_/g,' ')}: ${fmtMeasure(v)}`).join(' · ');li.appendChild(small);}
    list.appendChild(li);});
  document.querySelector('.wb-pc-only').hidden=p.kind!=='points';
  document.querySelector('.wb-raster-only').hidden=p.kind==='points';
  const g=p.grid||{};if(p.kind==='points'){document.querySelector('.wb-pc-method').value=g.method||'tin';}
  const r=ARGS.resolution,out=document.querySelector('.wb-reso-result');
  if(r&&out){out.hidden=false;out.textContent=`${r.message} (cell ${r.cell_m} m)`;out.className='wb-reso-result '+(r.verdict||'');}
  renderAI();
}
function aiSettings(){
  const q=s=>document.querySelector(s);
  return {width:Number(q('.wb-ai-width')?.value)||5,sensitivity:q('.wb-ai-sens')?.value||'medium',seed:Number(q('.wb-ai-seed')?.value)||0,
    compare:q('.wb-ai-compare')?q('.wb-ai-compare').checked:true,larger:q('.wb-ai-larger')?q('.wb-ai-larger').checked:true,
    mask_water:q('.wb-ai-water')?q('.wb-ai-water').checked:true,water_tilt_deg:Number(q('.wb-ai-water-tilt')?.value)||0.4,
    water_min_area_m2:Number(q('.wb-ai-water-area')?.value)||5000};
}
function renderAI(){
  const box=document.querySelector('.wb-ai-result');if(!box)return;
  const st=document.querySelector('.wb-ai-sites-state');if(st)st.textContent=ARGS.sites?'Known features loaded.':'';
  const a=ARGS.ai;box.hidden=!a;if(!a)return;
  box.querySelector('.wb-ai-note').textContent=a.note;
  box.querySelector('.wb-ai-known').textContent=a.known||'';
  const list=box.querySelector('.wb-ai-areas');list.innerHTML='';
  (a.areas||[]).forEach(x=>{const li=document.createElement('li');li.tabIndex=0;li.title='Show on the map';
    const dot=document.createElement('b');dot.className='wb-ai-dot';dot.style.background=x.colour||'#d62728';dot.title=x.kind||'';li.appendChild(dot);
    const n=document.createElement('span');n.textContent=x.note;li.appendChild(n);
    const s=document.createElement('small');s.textContent=`Score ${x.score} · driven by ${x.drivers.join(', ')}`;li.appendChild(s);
    const go=()=>map&&map.flyTo({center:[x.lon,x.lat],zoom:Math.max(map.getZoom(),17),duration:600});
    li.addEventListener('click',go);li.addEventListener('keydown',e=>{if(e.key==='Enter')go();});list.appendChild(li);});
}

function renderSiteInfo(){
  const box=document.querySelector('.wb-site'),site=ARGS.use_case;
  box.hidden=!site?.summary;
  if(box.hidden)return;
  box.querySelector('.wb-site-title').textContent=site.label;
  box.querySelector('.wb-site-summary').textContent=site.summary;
  box.querySelector('.wb-site-terrain').textContent=site.terrain;
  const refs=box.querySelector('.wb-site-references');refs.replaceChildren();
  for(const ref of site.references||[]){
    const p=document.createElement('p'),a=document.createElement('a');
    a.textContent=ref.citation;a.href=ref.url;a.target='_blank';a.rel='noopener noreferrer';p.append(a);
    if(ref.pdf){const pdf=document.createElement('a');pdf.textContent='Open paper (PDF)';pdf.href=ref.pdf;pdf.target='_blank';pdf.rel='noopener noreferrer';pdf.className='wb-site-pdf';p.append(pdf);}
    refs.append(p);
  }
}

function update(){
  renderSiteInfo();
  for(const box of [messageBox,document.querySelector('.wb-3d-message')]){box.hidden=!ARGS.message;box.textContent=ARGS.message||'';box.classList.toggle('error',ARGS.message_level==='error');}
  if(pendingNonce&&ARGS.done_nonce===pendingNonce){pendingNonce=null;busy.hidden=true;document.querySelector('.wb-3d-busy').hidden=true;document.querySelectorAll('.wb-run').forEach(b=>b.disabled=false);document.querySelector('.wb-cloud').disabled=false;rvtWorkspace?.setBusy(false);sync3DButtons();}
  syncLayers();
  renderPrep();
  rvtWorkspace?.update(ARGS.rvt_api,ARGS.message);
  const cloud=document.querySelector('.wb-cloud');
  cloud.value=ARGS.cloud_key||'original';
  document.querySelector('.wb-3d-ai-legend').hidden=cloud.value!=='ai_relief';
  const profile=(ARGS.tools.cloud_profiles||[]).find(p=>p.id===cloud.value);
  document.querySelector('.wb-cloud-help').textContent=profile?profile.description:'';
  const aiOpt=cloud.querySelector('option[value=ai_relief]');if(aiOpt){aiOpt.disabled=false;aiOpt.textContent='AI Relief';}
  const dl=ARGS.download;
  if(dl&&dl.id!==lastDownload){lastDownload=dl.id;const bytes=Uint8Array.from(atob(dl.b64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:dl.mime}));const a=document.createElement('a');a.href=url;a.download=dl.filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),4000);showToast(`Saved: ${dl.filename}`);}
  const v3=ARGS.view3d;
  if(v3&&v3.id!==last3d){last3d=v3.id;const m=document.querySelector('.wb-modal');viewerReady=false;sync3DButtons();m.querySelector('iframe').srcdoc=v3.html;m.hidden=false;}
}
function init(){rvtWorkspace=new window.RVTWorkspace(send,fit=>{if(!map)return;map.resize();const docked=document.querySelector('.detector-map').classList.contains('rvt-open');const padding={top:24,bottom:24,left:64,right:docked?24:document.querySelector('.exact-layer-panel').getBoundingClientRect().width+24};map.setPadding(padding);if(fit&&layerBounds())map.fitBounds(layerBounds(),{padding,pitch:0,bearing:0,duration:0});});initMap();buildTools();wireControls();renderLayerCards();}

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
  const lon=e.lngLat.lng,lat=e.lngLat.lat;
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
  const tb=document.querySelector('.terrain-toggle');const label=()=>{tb.querySelector('small').textContent=terrainEnabled?'Relief on':'Flat view';};
  tb.addEventListener('click',()=>{terrainEnabled=!terrainEnabled;map.setTerrain(terrainEnabled?{source:'terrain',exaggeration:1.35}:null);map.easeTo({pitch:terrainEnabled?50:0,bearing:terrainEnabled?-12:0,duration:700});label();});
  document.querySelector('.panel-handle').addEventListener('click',ev=>{const c=document.querySelector('.detector-map').classList.toggle('panel-collapsed');ev.currentTarget.textContent=c?'‹':'›';ev.currentTarget.title=c?'Show tools':'Hide tools';ev.currentTarget.setAttribute('aria-expanded',String(!c));});
  document.querySelector('.map-fullscreen').addEventListener('click',()=>{const e=document.querySelector('.detector-map');if(!document.fullscreenElement&&e.requestFullscreen)e.requestFullscreen();else if(document.exitFullscreen)document.exitFullscreen();setTimeout(()=>map.resize(),300);});
  document.querySelector('.wb-modal-close').addEventListener('click',()=>{const m=document.querySelector('.wb-modal');m.hidden=true;m.querySelector('iframe').srcdoc='';viewerReady=false;captureRequest=null;clearTimeout(captureTimeout);sync3DButtons();});
}
})();
