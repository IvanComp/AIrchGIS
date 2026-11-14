const assert = require('node:assert/strict');
require('../RVT/scripts/anomaly_labels.js');

const layout = new globalThis.AnomalyLabelLayout();
const cluster = Array.from({length: 5}, (_, i) => ({id: i + 1, x: 400 + i * 2, y: 250 + i * 2, width: 80, height: 29}));
const first = layout.place(cluster, 800, 600).map(box => ({...box}));
for (let frame = 0; frame < 240; frame++) {
  const jitter = cluster.map((item, i) => ({...item, x: item.x + Math.sin(frame + i) * .2, y: item.y + Math.cos(frame + i) * .2}));
  const current = layout.place(jitter, 800, 600);
  for (let i = 0; i < first.length; i++) {
    assert.equal(current[i].left, first[i].left);
    assert.equal(current[i].top, first[i].top);
  }
}
for (let i = 0; i < first.length; i++) for (let j = i + 1; j < first.length; j++) {
  const a = first[i], b = first[j];
  assert.ok(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
}

layout.pinned = 3;
const pinned = layout.place(cluster, 800, 600)[2];
const moved = cluster.map(item => ({...item, x: item.x + 3, y: item.y + 2}));
const hovering = layout.place(moved, 800, 600)[2];
assert.equal(hovering.left, pinned.left);
assert.equal(hovering.top, pinned.top);

layout.pinned = null;
const resized = layout.place(cluster, 250, 180);
for (const box of resized) {
  assert.ok(box.left >= 4 && box.top >= 4 && box.right <= 246 && box.bottom <= 176);
}
assert.deepEqual(layout.place([], 800, 600), []);
const restored = layout.place(cluster, 800, 600);
assert.equal(restored.length, 5);
console.log('Dense labels: stable over 240 jitter frames; no overlap; hover and resize checks passed.');
