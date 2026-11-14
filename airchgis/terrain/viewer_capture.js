const viewerDisplay = {background: 'black', quality: 8192, contrast: 50, brightness: 40};
const contrastUniform = {value: viewerDisplay.contrast / 50};
const brightnessUniform = {value: viewerDisplay.brightness / 100};
let viewerDirty = true;
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
  viewerDisplay.background = options.background === 'none' ? 'none' : 'black';

  const contrast = Number(options.contrast), brightness = Number(options.brightness);
  viewerDisplay.contrast = Number.isFinite(contrast) ? Math.min(100, Math.max(0, contrast)) : 50;
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
      render_mode: RENDER_MODE, vertical_exaggeration: Z_EXAGGERATION,
      background: viewerDisplay.background, contrast: viewerDisplay.contrast,
      brightness: viewerDisplay.brightness, display_quality: viewerDisplay.quality,
      crs: typeof VIEW_CRS === 'undefined' ? null : VIEW_CRS,
      cell_size_m: typeof CELL_SIZE_M === 'undefined' ? null : CELL_SIZE_M,
      relief_scale_m: typeof RELIEF_SCALE_M === 'undefined' ? null : RELIEF_SCALE_M
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
window.parent.postMessage({type: 'airchgis:3d-ready'}, '*');
