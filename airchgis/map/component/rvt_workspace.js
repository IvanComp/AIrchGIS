(function(){
const make=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
const option=(value,label)=>{const e=make('option','',label);e.value=value;return e;};
const parse=value=>{if(value.trim()==='')return null;try{return JSON.parse(value);}catch{return value;}};
const summary=item=>{const s=item.summary;if(!s)return '';if(s.type==='array')return `${s.shape.join(' × ')} · ${s.dtype}`;if(s.type==='file')return s.name;return typeof s==='object'?s.type:String(s);};
class Workspace{
  constructor(send,onLayout){
    this.send=send;this.onLayout=onLayout;this.pendingPreview=false;this.lastPreview=null;this.state=null;this.operation=null;this.fields=new Map();this.dirtyFields=new Map();this.busy=false;
    this.root=make('div','rvt-workspace');this.root.hidden=true;this.root.setAttribute('role','region');this.root.setAttribute('aria-label','RVT visualization tools');
    this.root.innerHTML=`<div class="rvt-window"><header class="rvt-header"><div><h2>Visualization tools</h2><p class="rvt-version"></p></div><button type="button" class="rvt-close" aria-label="Close RVT tools">×</button></header><nav class="rvt-tabs" aria-label="Workspace sections"></nav><div class="rvt-feedback" role="status" hidden></div><div class="rvt-map-layers"></div><div class="rvt-live-row"><label><input type="checkbox" class="rvt-live" checked> Live preview</label><span class="rvt-preview-status" role="status">Change a parameter to update the map.</span></div><div class="rvt-operation-layout"><aside class="rvt-operation-list"><input class="rvt-search" type="search" placeholder="Find a tool" aria-label="Find a tool"><select class="rvt-group" aria-label="Tool group"></select><select class="rvt-operations" aria-label="RVT operation"></select></aside><main class="rvt-operation-form"><h3 class="rvt-title"></h3><p class="rvt-operation-help"></p><p class="rvt-operation-id"></p><div class="rvt-instance-wrap"><label>Object instance<select class="rvt-instance"></select></label><button type="button" class="rvt-create-instance">Create an instance</button></div><div class="rvt-parameters"></div><div class="rvt-run-row"><label><input type="checkbox" class="rvt-auto-show" checked> Display spatial result on map</label><button type="button" class="rvt-run">Run operation</button></div></main><details class="rvt-output-panel"><summary>Results &amp; exports</summary><div class="rvt-results"></div></details></div><section class="rvt-settings-panel" hidden><label>Settings or composition object<select class="rvt-settings-object"></select></label><input type="search" class="rvt-settings-search" placeholder="Filter settings" aria-label="Filter settings"><div class="rvt-settings-fields"></div><button type="button" class="rvt-save-settings">Apply settings</button></section><section class="rvt-presets-panel" hidden><h3>RVT compositions</h3><label>Composition<select class="rvt-preset"></select></label><label>Terrain settings<select class="rvt-terrain"></select></label><label>General VAT opacity (%)<input type="number" class="rvt-vat-opacity" min="0" max="100" value="50"></label><button type="button" class="rvt-run-preset">Render composition</button><h3>Custom compositions</h3><p>Create a BlenderCombination object under Operations. Add layers with Create layer, set normalization, blend mode, opacity and colour map, then run Render all images. JSON compositions can be imported and exported through the library operations.</p></section><section class="rvt-files-panel" hidden><h3>Inputs and results</h3><label class="rvt-upload-label">Import rasters or configuration files<input type="file" class="rvt-upload" multiple accept=".tif,.tiff,.asc,.json,.npy,.npz,.txt"></label><div class="rvt-all-results"></div><button type="button" class="rvt-package">Download session package</button></section><section class="rvt-batch-panel" hidden><h3>Batch processing</h3><p>Select an operation and its parameters under Operations, then choose raster files below. Each input is processed with its own grid and resolution. For tiled processing, use the Tiled processing group in Operations.</p><div class="rvt-batch-files"></div><button type="button" class="rvt-run-batch">Run selected operation on files</button></section><footer class="rvt-footer"><span class="rvt-busy" role="status" hidden>Processing…</span><span>Inputs, settings and results remain available for subsequent operations.</span></footer></div>`;
    document.querySelector('.map-stage').appendChild(this.root);
    this.$=s=>this.root.querySelector(s);
    this.$('.rvt-close').onclick=()=>this.close();
    this.$('.rvt-live').onchange=()=>{this.lastPreview=null;this.queuePreview();};
    this.$('.rvt-instance').onchange=()=>{this.lastPreview=null;this.queuePreview();};
    for(const [id,label] of [['operations','Operations'],['settings','Settings'],['presets','Compositions'],['files','Inputs & results'],['batch','Batch']]){const b=make('button','',label);b.type='button';b.dataset.tab=id;b.onclick=()=>this.tab(id);this.$('.rvt-tabs').appendChild(b);}
    for(const [id,label] of [['','All operations'],['vis','Visualizations'],['blend','Compositions & objects'],['blend_func','Image transformations'],['default','Defaults, files & output'],['tile','Tiled processing']])this.$('.rvt-group').appendChild(option(id,label));
    this.$('.rvt-search').oninput=()=>this.operationList();this.$('.rvt-group').onchange=()=>this.operationList();
    this.$('.rvt-operations').onchange=()=>this.selectOperation(this.$('.rvt-operations').value);
    this.$('.rvt-run').onclick=()=>this.run();
    this.$('.rvt-create-instance').onclick=()=>this.selectOperation(this.operation.class);
    this.$('.rvt-settings-object').onchange=()=>this.settingsFields();
    this.$('.rvt-settings-search').oninput=()=>this.filterSettings();
    this.$('.rvt-save-settings').onclick=()=>{this.lastPreview=null;this.pendingPreview=true;this.send({action:'rvt_settings',artifact:this.$('.rvt-settings-object').value,fields:Object.fromEntries(this.dirtyFields)});};
    this.$('.rvt-run-preset').onclick=()=>this.send({action:'rvt_preset',preset:this.$('.rvt-preset').value,terrain:this.$('.rvt-terrain').value,opacity:Number(this.$('.rvt-vat-opacity').value)});
    for(const selector of ['.rvt-preset','.rvt-terrain','.rvt-vat-opacity'])this.$(selector).addEventListener('change',()=>this.queuePreview());
    this.$('.rvt-vat-opacity').addEventListener('input',()=>this.queuePreview());
    this.$('.rvt-upload').onchange=async ev=>{this.uploadQueue=[...ev.target.files];this.uploadNext();};
    this.$('.rvt-package').onclick=()=>this.send({action:'rvt_package'});
    this.$('.rvt-run-batch').onclick=()=>{if(!this.operation)return;const files=[...this.root.querySelectorAll('.rvt-batch-files input:checked')].map(e=>e.value);if(!files.length){this.feedback('Select at least one raster file.');return;}this.send({action:'rvt_batch',operation:this.operation.id,parameters:this.values(),instance:this.$('.rvt-instance').value||null,files});};
    this.tab('operations');
  }
  open(){
    this.root.hidden=false;document.querySelector('.detector-map').classList.add('rvt-open');
    const layers=document.querySelector('.wb-layers');layers.open=false;this.$('.rvt-map-layers').appendChild(layers);
    this.onLayout?.(!this.hasOpened);this.hasOpened=true;if(!this.state)this.send({action:'rvt_open'});else this.queuePreview();
  }
  close(){
    this.root.hidden=true;this.pendingPreview=false;clearTimeout(this.previewTimer);
    const panel=document.querySelector('.exact-layer-panel');panel.insertBefore(this.$('.wb-layers'),panel.querySelector('.wb-toolbox'));
    document.querySelector('.detector-map').classList.remove('rvt-open');this.onLayout?.();
  }
  tab(id){this.currentTab=id;this.$('.rvt-live').disabled=id==='presets'?false:!this.operation?.preview;for(const b of this.root.querySelectorAll('.rvt-tabs button'))b.classList.toggle('active',b.dataset.tab===id);for(const [key,selector] of Object.entries({operations:'.rvt-operation-layout',settings:'.rvt-settings-panel',presets:'.rvt-presets-panel',files:'.rvt-files-panel',batch:'.rvt-batch-panel'}))this.$(selector).hidden=key!==id;}
  feedback(message,error=true){const e=this.$('.rvt-feedback');e.hidden=!message;e.textContent=message||'';e.classList.toggle('error',error);}
  setBusy(value,action){
    this.busy=value;this.$('.rvt-busy').hidden=!value;
    for(const e of this.root.querySelectorAll('.rvt-run,.rvt-save-settings,.rvt-run-preset,.rvt-run-batch,.rvt-package,.rvt-result-actions button'))e.disabled=value;
    if(value&&['rvt_preview','rvt_preset_preview'].includes(action))this.$('.rvt-preview-status').textContent='Updating map…';
    if(!value&&this.pendingPreview){clearTimeout(this.previewTimer);this.previewTimer=setTimeout(()=>this.flushPreview(),80);}
  }
  queuePreview(){
    clearTimeout(this.previewTimer);
    if(this.root.hidden||!this.$('.rvt-live').checked||(!this.operation?.preview&&this.currentTab!=='presets')){this.pendingPreview=false;return;}
    this.pendingPreview=true;this.previewTimer=setTimeout(()=>this.flushPreview(),650);
  }
  flushPreview(){
    if(!this.pendingPreview||this.busy||this.root.hidden||!this.$('.rvt-live').checked||(!this.operation?.preview&&this.currentTab!=='presets'))return;
    if(this.currentTab==='presets'){
      const event={action:'rvt_preset_preview',preset:this.$('.rvt-preset').value,terrain:this.$('.rvt-terrain').value,opacity:Number(this.$('.rvt-vat-opacity').value)};
      const signature=JSON.stringify(event);this.pendingPreview=false;if(signature===this.lastPreview)return;this.lastPreview=signature;this.send(event);return;
    }
    if(this.operation.kind==='method'&&!this.$('.rvt-instance').value)return;
    const automatic=new Set(['dem','dem_arr','height_arr','dem_fine','data','image','gray_scale','float_arr','resolution','resolution_x','resolution_y','x_res','y_res','dem_resolution','visualization','rvt_visualization']);
    for(const [name,f] of this.fields){if(f.p.required&&((f.binding.value==='auto'&&!automatic.has(name))||(f.binding.value==='value'&&f.value.value.trim()==='')||f.binding.value==='none')){this.$('.rvt-preview-status').textContent='Set the required inputs to preview.';return;}}
    const event={action:'rvt_preview',operation:this.operation.id,parameters:this.values(),instance:this.$('.rvt-instance').value||null};
    const signature=JSON.stringify(event);this.pendingPreview=false;if(signature===this.lastPreview)return;
    this.lastPreview=signature;this.send(event);
  }
  update(state,message){
    if(message)this.feedback(message);else this.feedback('');
    if(!state)return;
    const first=!this.state;const oldSettings=this.$('.rvt-settings-object').value;
    this.state=state;this.$('.rvt-version').textContent=`RVT_py ${state.catalog.version} · ${state.catalog.count} public library operations`;
    if(first){this.operationList();for(const name of state.catalog.presets)this.$('.rvt-preset').appendChild(option(name,name));for(const name of state.catalog.terrains)this.$('.rvt-terrain').appendChild(option(name,name));}
    for(const [key,field] of this.fields)this.bindingOptions(field.binding,key,field.binding.value);
    this.instances();
    const objectSelect=this.$('.rvt-settings-object');objectSelect.replaceChildren();
    for(const item of state.artifacts.filter(a=>a.fields.length))objectSelect.appendChild(option(item.id,item.label+' · '+item.summary.type));
    if([...objectSelect.options].some(o=>o.value===oldSettings))objectSelect.value=oldSettings;
    this.settingsFields();this.results();this.batchFiles();
    if(state.preview_status&&!this.busy)this.$('.rvt-preview-status').textContent=`Map updated · ${state.preview_status.duration.toFixed(2)} s`;
    if(this.uploadQueue&&this.uploadQueue.length&&!this.busy)this.uploadNext();
  }
  operationList(){
    if(!this.state)return;
    const query=this.$('.rvt-search').value.toLowerCase(),group=this.$('.rvt-group').value;
    const select=this.$('.rvt-operations'),previous=this.operation?.id;select.replaceChildren();
    for(const op of this.state.catalog.operations.filter(o=>(!group||o.module===group)&&(!query||(o.label+' '+o.id+' '+o.help).toLowerCase().includes(query))))select.appendChild(option(op.id,op.label));
    if([...select.options].some(o=>o.value===previous))select.value=previous;
    else if([...select.options].some(o=>o.value==='vis.hillshade'))select.value='vis.hillshade';
    if(select.value)this.selectOperation(select.value);
  }
  selectOperation(id){
    if(!this.state)return;
    this.operation=this.state.catalog.operations.find(o=>o.id===id);if(!this.operation)return;
    const select=this.$('.rvt-operations');if(![...select.options].some(o=>o.value===id)){this.$('.rvt-group').value='';this.$('.rvt-search').value='';this.operationList();}select.value=id;
    this.$('.rvt-title').textContent=this.operation.label;this.$('.rvt-operation-help').textContent=this.operation.help;this.$('.rvt-operation-id').textContent=this.operation.id;
    this.fields.clear();this.$('.rvt-parameters').replaceChildren();
    for(const p of this.operation.parameters)this.parameter(p);
    this.instances();this.tab('operations');
    this.$('.rvt-live').disabled=!this.operation.preview;
    this.$('.rvt-run').textContent=this.operation.preview?'Keep result':'Run operation';
    this.$('.rvt-preview-status').textContent=this.operation.preview?'Change a parameter to update the map.':'Use Run operation for this action.';
    this.queuePreview();
  }
  instances(){
    if(!this.operation)return;
    const select=this.$('.rvt-instance'),previous=select.value;select.replaceChildren();
    this.$('.rvt-instance-wrap').hidden=this.operation.kind!=='method';
    if(this.operation.kind==='method')for(const a of this.state.artifacts.filter(a=>a.class===this.operation.class))select.appendChild(option(a.id,a.label));
    if([...select.options].some(o=>o.value===previous))select.value=previous;
    this.$('.rvt-create-instance').hidden=select.options.length>0;
  }
  bindingOptions(select,key,previous='auto'){
    const p=this.operation.parameters.find(p=>p.name===key);select.replaceChildren();
    select.appendChild(option('auto','Automatic'));
    if(!p.required)select.appendChild(option('default','Library default'));
    select.appendChild(option('value','Custom value'));select.appendChild(option('none','None'));
    for(const a of this.state.artifacts)select.appendChild(option('artifact:'+a.id,a.label+' · '+summary(a)));
    if([...select.options].some(o=>o.value===previous))select.value=previous;
  }
  parameter(p){
    const wrapper=make('div','rvt-param');const label=make('label','rvt-param-label',p.label+(p.required?' *':''));wrapper.appendChild(label);
    const binding=make('select','rvt-binding');binding.setAttribute('aria-label',p.label+' input');this.bindingOptions(binding,p.name);
    wrapper.appendChild(binding);
    let value;
    if(p.kind==='boolean'){value=make('select');value.append(option('true','True'),option('false','False'));value.value=String(p.default??true);}
    else if(['enum','choice','function','colormap'].includes(p.kind)){
      value=make('input');value.type='text';const list=make('datalist');list.id='rvt-values-'+p.name;
      let choices=p.choices||[];if(p.kind==='function')choices=this.state.catalog.operations.filter(o=>o.module==='vis'&&o.kind==='function').map(o=>o.id);
      if(p.kind==='colormap')choices=['gray','viridis','terrain','OrRd','Reds_r','RdBu','Spectral','gist_earth','inferno','plasma'];
      for(const c of choices)list.appendChild(option(c,c));wrapper.appendChild(list);value.setAttribute('list',list.id);value.value=p.default??choices[0]??'';
    }
    else if(['mapping','sequence','array','object'].includes(p.kind)){value=make('textarea');value.rows=3;value.value=p.default==null?(p.kind==='mapping'?'{}':p.kind==='sequence'?'[]':''):JSON.stringify(p.default);value.placeholder=p.kind==='array'?'Choose an input array, or enter structured values':p.kind==='object'?'Choose an object from the input list':'Structured values';}
    else {value=make('input');value.type=p.kind==='number'?'number':'text';if(value.type==='number')value.step=p.integer?'1':'any';value.value=p.default??'';}
    value.className='rvt-param-value';value.setAttribute('aria-label',p.label+' value');value.hidden=true;wrapper.appendChild(value);
    let slider=null;
    const limits={sun_azimuth:[0,360,1],shadow_az:[0,360,1],asvf_dir:[0,360,1],a_main_direction:[0,360,1],sun_elevation:[1,90,1],shadow_el:[1,90,1],ve_factor:[.1,5,.1],radius_cell:[1,100,1],svf_r_max:[1,100,1]};
    if(limits[p.name]&&typeof p.default==='number'){
      binding.value='value';value.hidden=false;slider=make('input','rvt-slider');slider.type='range';[slider.min,slider.max,slider.step]=limits[p.name];slider.value=value.value;slider.setAttribute('aria-label',p.label+' slider');wrapper.appendChild(slider);
      slider.oninput=()=>{value.value=slider.value;this.queuePreview();};value.addEventListener('input',()=>slider.value=value.value);
    }

    const member=make('input','rvt-member');member.type='text';member.placeholder='Optional member key or band index';member.setAttribute('aria-label',p.label+' member');member.hidden=true;wrapper.appendChild(member);
    if(p.help)wrapper.appendChild(make('p','rvt-param-help',p.help));
    binding.onchange=()=>{value.hidden=binding.value!=='value';member.hidden=!binding.value.startsWith('artifact:');if(slider)slider.hidden=binding.value!=='value';this.queuePreview();};
    value.addEventListener('input',()=>this.queuePreview());value.addEventListener('change',()=>this.queuePreview());member.addEventListener('input',()=>this.queuePreview());
    this.$('.rvt-parameters').appendChild(wrapper);this.fields.set(p.name,{binding,value,member,p});
  }
  values(){const result={};for(const [name,f] of this.fields){const mode=f.binding.value;if(mode.startsWith('artifact:')){result[name]={binding:'artifact',id:mode.slice(9)};if(f.member.value!=='')result[name].member=f.member.value;}else if(mode==='value')result[name]={binding:'value',value:parse(f.value.value)};else result[name]={binding:mode};}return result;}
  run(){this.pendingPreview=false;clearTimeout(this.previewTimer);if(this.operation)this.send({action:'rvt_run',operation:this.operation.id,parameters:this.values(),instance:this.$('.rvt-instance').value||null,show:this.$('.rvt-auto-show').checked});}
  settingsFields(){
    this.dirtyFields.clear();const area=this.$('.rvt-settings-fields');area.replaceChildren();const item=this.state?.artifacts.find(a=>a.id===this.$('.rvt-settings-object').value);if(!item)return;
    for(const field of item.fields){const row=make('label','rvt-setting-field');row.dataset.name=field.name;row.appendChild(make('span','',field.name.replaceAll('_',' ')));let input;
      if(typeof field.value==='boolean'){input=make('select');input.append(option('true','True'),option('false','False'));input.value=String(field.value);}
      else {input=make('input');input.type=typeof field.value==='number'?'number':'text';if(input.type==='number')input.step='any';input.value=typeof field.value==='string'?field.value:JSON.stringify(field.value);}
      input.onchange=()=>this.dirtyFields.set(field.name,parse(input.value));row.appendChild(input);area.appendChild(row);
    }this.filterSettings();
  }
  filterSettings(){const q=this.$('.rvt-settings-search').value.toLowerCase();for(const row of this.root.querySelectorAll('.rvt-setting-field'))row.hidden=!row.dataset.name.toLowerCase().includes(q);}
  resultCard(item){
    const card=make('div','rvt-result');card.appendChild(make('h4','',item.label));card.appendChild(make('p','',summary(item)));
    const actions=make('div','rvt-result-actions');
    const button=(label,fn)=>{const b=make('button','',label);b.type='button';b.onclick=fn;actions.appendChild(b);};
    if(item.mapable){
      let band=null;const shape=item.summary.shape||[];if(shape.length===3){band=make('input');band.type='number';band.value='1';band.min='1';band.step='1';band.setAttribute('aria-label','Result band');actions.appendChild(band);}
      button('Show on map',()=>this.send({action:'rvt_show',artifact:item.id,band:band?Number(band.value)-1:0}));
      if(shape.length===3)button('Show RGB',()=>this.send({action:'rvt_show',artifact:item.id,rgb:true}));
      button('GeoTIFF',()=>this.send({action:'rvt_download',artifact:item.id,format:'geotiff'}));
    }
    if(item.summary?.type!=='file'||item.summary.exists)button('Download',()=>this.send({action:'rvt_download',artifact:item.id}));
    if(item.summary?.type==='file')card.appendChild(make('p','rvt-result-location',item.summary.location));
    if(item.summary?.type==='array')button('CSV',()=>this.send({action:'rvt_download',artifact:item.id,format:'csv'}));
    if(item.fields.length)button('Edit',()=>{this.$('.rvt-settings-object').value=item.id;this.settingsFields();this.tab('settings');});
    card.appendChild(actions);
    if(item.summary?.type==='mapping'||item.summary?.type==='sequence'||(!item.summary?.type)){const details=make('details');details.appendChild(make('summary','','Inspect result'));details.appendChild(make('pre','',JSON.stringify(item.summary,null,2)));card.appendChild(details);}
    return card;
  }
  results(){
    this.$('.rvt-results').replaceChildren();this.$('.rvt-all-results').replaceChildren();const latest=new Set(this.state.latest);
    for(const item of this.state.artifacts){if(latest.has(item.id))this.$('.rvt-results').appendChild(this.resultCard(item));this.$('.rvt-all-results').appendChild(this.resultCard(item));}
    if(!this.state.latest.length)this.$('.rvt-results').appendChild(make('p','rvt-empty','Run an operation to create results. Outputs can be reused as inputs.'));
  }
  batchFiles(){const area=this.$('.rvt-batch-files');const previous=new Set([...area.querySelectorAll('input:checked')].map(i=>i.value));area.replaceChildren();for(const item of this.state.artifacts.filter(a=>a.summary?.type==='file'&&/\.(tif|tiff|asc)$/i.test(a.summary.name))){const label=make('label');const c=make('input');c.type='checkbox';c.value=item.id;c.checked=previous.has(item.id);label.append(c,document.createTextNode(item.label));area.appendChild(label);}}
  uploadNext(){if(this.busy||!this.uploadQueue?.length)return;const file=this.uploadQueue.shift();const reader=new FileReader();reader.onload=()=>this.send({action:'rvt_upload',filename:file.name,b64:String(reader.result).split(',')[1]});reader.readAsDataURL(file);}
}
window.RVTWorkspace=Workspace;
})();
