const viewerDisplay = {background: 'none', quality: 8192, contrast: 65, brightness: 40, verticalExaggeration: 1, reliefOpacity: 100};
const reliefObjects = scene.children.filter(object => object.isMesh || object.isPoints || object.isLine);
const reliefMaterials = reliefObjects.map(object => ({object, opacity: object.material.opacity, visible: object.visible}));
let satelliteMesh = null;
if (BASEMAP_COLOR_B64) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Uint8BufferAttribute(base64ToUint8Array(BASEMAP_COLOR_B64), 3, true));
  const indices = [];
  for (let r = 0; r < GRID_ROWS - 1; r++) {
    for (let c = 0; c < GRID_COLS - 1; c++) {
      const a = r * GRID_COLS + c, b = a + 1, d = a + GRID_COLS, e = d + 1;
      if (validBytes[a] && validBytes[d] && validBytes[b]) indices.push(a, d, b);
      if (validBytes[b] && validBytes[d] && validBytes[e]) indices.push(b, d, e);
    }
  }
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  satelliteMesh = new THREE.Mesh(geometry, new THREE.MeshPhongMaterial({vertexColors: true, side: THREE.DoubleSide,
    shininess: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1}));
  satelliteMesh.visible = false;
  scene.add(satelliteMesh);
}
const imageryCredit = document.createElement('div');
imageryCredit.textContent = BASEMAP_ATTRIBUTION;
imageryCredit.style.cssText = 'position:fixed;left:8px;bottom:6px;z-index:24;font:10px system-ui;color:#d9c7a8;background:rgba(33,21,14,.7);padding:3px 6px;border-radius:4px;pointer-events:none';
imageryCredit.hidden = true;
document.body.appendChild(imageryCredit);
const terrainObjects = scene.children.filter(object => object.isMesh || object.isPoints || object.isLine || object.isGroup);
for (const object of terrainObjects) object.scale.z = 1 / Z_EXAGGERATION;
const contrastUniform = {value: viewerDisplay.contrast / 50};
const brightnessUniform = {value: viewerDisplay.brightness / 100};
let viewerDirty = true;
scene.background = null;
renderer.setClearColor(0x000000, 0);
for (const element of [document.documentElement, document.body, root]) element.style.background = 'transparent';
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = viewerDisplay.brightness / 100;
scene.traverse(object => {
  const materials = object.material ? (Array.isArray(object.material) ? object.material : [object.material]) : [];
  for (const material of materials) {
    material.onBeforeCompile = shader => {
      shader.uniforms.airchgisContrast = contrastUniform;
      shader.uniforms.airchgisBrightness = brightnessUniform;
      shader.fragmentShader = 'uniform float airchgisContrast;\nuniform float airchgisBrightness;\n' + shader.fragmentShader.replace(
        '#include <encodings_fragment>',
        '#include <encodings_fragment>\ngl_FragColor.rgb = airchgisBrightness <= 0.0 ? vec3(0.0) : clamp((gl_FragColor.rgb - 0.5) * airchgisContrast + 0.5, 0.0, 1.0);'
      );
    };
    material.needsUpdate = true;
  }
});
function viewerSize(edge) {
  const width = window.innerWidth, height = window.innerHeight;
  const gl = renderer.getContext();
  const limit = Math.min(edge, renderer.capabilities.maxTextureSize, gl.getParameter(gl.MAX_RENDERBUFFER_SIZE));
  const ratio = Math.min(limit / width, limit / height, Math.sqrt(32000000 / (width * height)));
  if (Math.abs(renderer.getPixelRatio() - ratio) > .001 || renderer.getSize(new THREE.Vector2()).x !== width || renderer.getSize(new THREE.Vector2()).y !== height) {
    renderer.setPixelRatio(ratio);
    renderer.setSize(width, height);
    viewerDirty = true;
  }
}
function renderInteractive() {
  viewerSize(8192);
  if (viewerDirty) {
    renderer.render(scene, camera);
    viewerDirty = false;
  }
}
controls.addEventListener('start', () => {viewerDirty = true;});
controls.addEventListener('end', () => {viewerDirty = true;});
controls.addEventListener('change', () => {viewerDirty = true;});
window.removeEventListener('resize', onResize);
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  viewerDirty = true;
});
window.addEventListener('message', event => {
  if (event.source !== window.parent || event.data?.type !== 'airchgis:3d-options') return;
  const options = event.data;
  const infoPanel = document.getElementById('ai-hover-info');
  if (infoPanel) {
    const controlWidth = Math.max(0, Number(options.controlPanelWidth) || 0);
    infoPanel.style.right = (controlWidth ? controlWidth + 32 : 14) + 'px';
    infoPanel.style.width = Math.min(290, Math.max(180, window.innerWidth - controlWidth - 150)) + 'px';
  }
  const opacity = Number(options.reliefOpacity);
  viewerDisplay.reliefOpacity = satelliteMesh && Number.isFinite(opacity) ? Math.min(100, Math.max(0, opacity)) : 100;
  const reliefMix = viewerDisplay.reliefOpacity / 100;
  if (satelliteMesh) satelliteMesh.visible = reliefMix < 1;
  imageryCredit.hidden = !satelliteMesh || reliefMix === 1;
  for (const item of reliefMaterials) {
    item.object.visible = item.visible && reliefMix > 0;
    item.object.material.transparent = reliefMix < 1 || item.opacity < 1;
    item.object.material.opacity = item.opacity * reliefMix;
    item.object.material.depthWrite = reliefMix === 1 && item.opacity === 1;
    item.object.renderOrder = 1;
  }
  const exaggeration = Number(options.verticalExaggeration);
  if (Number.isFinite(exaggeration) && exaggeration > 0) {
    const previous = viewerDisplay.verticalExaggeration;
    viewerDisplay.verticalExaggeration = Math.min(100, Math.max(.1, exaggeration));
    for (const object of terrainObjects) object.scale.z = viewerDisplay.verticalExaggeration / Z_EXAGGERATION;
    const delta = controls.target.z * (viewerDisplay.verticalExaggeration / previous - 1);
    controls.target.z += delta;
    camera.position.z += delta;
    controls.update();
  }
  viewerDisplay.background = 'none';

  const contrast = Number(options.contrast), brightness = Number(options.brightness);
  viewerDisplay.contrast = Number.isFinite(contrast) ? Math.min(100, Math.max(0, contrast)) : 65;
  viewerDisplay.brightness = Number.isFinite(brightness) ? Math.min(100, Math.max(0, brightness)) : 40;
  const transparent = viewerDisplay.background === 'none';
  scene.background = transparent ? null : new THREE.Color(0x000000);
  renderer.setClearColor(0x000000, transparent ? 0 : 1);
  for (const element of [document.documentElement, document.body, root]) element.style.background = transparent ? 'transparent' : '#000';
  contrastUniform.value = viewerDisplay.contrast / 50;
  brightnessUniform.value = viewerDisplay.brightness / 100;
  renderer.toneMappingExposure = viewerDisplay.brightness / 100;
  viewerDirty = true;
});
window.addEventListener('message', event => {
  if (event.source !== window.parent || event.data?.type !== 'airchgis:capture3d') return;
  const id = event.data.id;
  const originalSize = renderer.getSize(new THREE.Vector2());
  const originalRatio = renderer.getPixelRatio();
  try {
    const gl = renderer.getContext();
    const limit = Math.min(8192, renderer.capabilities.maxTextureSize, gl.getParameter(gl.MAX_RENDERBUFFER_SIZE));
    const scale = Math.min(limit / originalSize.x, limit / originalSize.y, Math.sqrt(32000000 / (originalSize.x * originalSize.y)));
    const width = Math.max(1, Math.floor(originalSize.x * scale));
    const height = Math.max(1, Math.floor(originalSize.y * scale));
    const exportCamera = camera.clone();
    const view = {
      position: camera.position.toArray(), quaternion: camera.quaternion.toArray(),
      target: controls.target.toArray(), projection: camera.projectionMatrix.toArray(),
      fov: camera.fov, aspect: camera.aspect, near: camera.near, far: camera.far,
      viewport: [originalSize.x, originalSize.y], pixels: [width, height],
      render_mode: RENDER_MODE, vertical_exaggeration: viewerDisplay.verticalExaggeration,
      background: viewerDisplay.background, contrast: viewerDisplay.contrast,
      relief_opacity: viewerDisplay.reliefOpacity,
      imagery_attribution: viewerDisplay.reliefOpacity < 100 ? BASEMAP_ATTRIBUTION : null,
      brightness: viewerDisplay.brightness, display_quality: viewerDisplay.quality,
      crs: typeof VIEW_CRS === 'undefined' ? null : VIEW_CRS,
      cell_size_m: typeof CELL_SIZE_M === 'undefined' ? null : CELL_SIZE_M,
      relief_scale_m: typeof RELIEF_SCALE_M === 'undefined' ? null : RELIEF_SCALE_M,
      mode_label: typeof MODE_LABEL === 'undefined' ? null : MODE_LABEL,
      ai_shown: typeof AI_SHOWN === 'undefined' ? false : AI_SHOWN,
      ai_width_m: typeof AI_WIDTH_M === 'undefined' ? null : AI_WIDTH_M,
      ai_view: window.AI_CURRENT || null,
      ve_source: viewerDisplay.verticalExaggeration !== Z_EXAGGERATION ? 'manual' : (typeof VE_SOURCE === 'undefined' ? null : VE_SOURCE)
    };
    renderer.setPixelRatio(1);
    renderer.setSize(width, height, false);
    renderer.render(scene, exportCamera);
    if (gl.isContextLost()) throw new Error('The graphics device could not render this image.');
    const png = renderer.domElement.toDataURL('image/png');
    if (!png.startsWith('data:image/png;base64,')) throw new Error('The image could not be captured.');
    window.parent.postMessage({type: 'airchgis:3d-capture', id, png, view}, '*');
  } catch (error) {
    window.parent.postMessage({type: 'airchgis:3d-capture', id, error: String(error.message || error)}, '*');
  } finally {
    renderer.setPixelRatio(originalRatio);
    renderer.setSize(originalSize.x, originalSize.y, false);
    viewerDirty = true;
    renderer.render(scene, camera);
  }
});
window.parent.postMessage({type: 'airchgis:3d-ready', verticalExaggeration: Z_EXAGGERATION, basemapAvailable: Boolean(satelliteMesh)}, '*');
