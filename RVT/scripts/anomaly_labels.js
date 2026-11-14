globalThis.AnomalyLabelLayout = class {
  constructor() {
    this.states = new Map();
    this.snapshot = null;
    this.result = [];
    this.pinned = null;
  }

  place(items, width, height) {
    const previous = this.snapshot;
    if (previous && previous.width === width && previous.height === height && previous.pinned === this.pinned &&
        previous.items.length === items.length && items.every((item, i) => {
          const last = previous.items[i];
          return item.id === last.id && item.width === last.width && item.height === last.height &&
            Math.abs(item.x - last.x) < .75 && Math.abs(item.y - last.y) < .75;
        })) return this.result;

    const placed = [];
    const output = [];
    const clamp = (value, lower, upper) => Math.max(lower, Math.min(upper, value));
    for (const item of items) {
      const w = item.width, h = item.height;
      const maxX = Math.max(4, width - w - 4), maxY = Math.max(4, height - h - 4);
      const old = this.states.get(item.id);
      const candidates = [];
      for (const gap of [14, 36, 60, 84]) {
        for (const offset of [[gap, -h - gap], [gap, gap], [-w - gap, -h - gap], [-w - gap, gap],
          [gap, -h / 2], [-w - gap, -h / 2], [-w / 2, -h - gap], [-w / 2, gap]]) {
          candidates.push({left: clamp(item.x + offset[0], 4, maxX), top: clamp(item.y + offset[1], 4, maxY)});
        }
      }
      const score = box => {
        let value = Math.hypot(box.left + w / 2 - item.x, box.top + h / 2 - item.y);
        for (const other of placed) {
          value += Math.max(0, Math.min(box.left + w + 5, other.right) - Math.max(box.left - 5, other.left)) *
            Math.max(0, Math.min(box.top + h + 5, other.bottom) - Math.max(box.top - 5, other.top)) * 4;
        }
        return value;
      };
      let slot = 0;
      for (let i = 1; i < candidates.length; i++) if (score(candidates[i]) < score(candidates[slot]) - .01) slot = i;
      if (old && candidates[old.slot] && score(candidates[old.slot]) <= score(candidates[slot]) + 120) slot = old.slot;
      let box = candidates[slot];
      if (old && this.pinned === item.id) box = {left: clamp(old.left, 4, maxX), top: clamp(old.top, 4, maxY)};
      const state = {id: item.id, slot, left: box.left, top: box.top, right: box.left + w, bottom: box.top + h};
      this.states.set(item.id, state);
      placed.push(state);
      output.push(state);
    }
    this.snapshot = {width, height, pinned: this.pinned, items: items.map(item => ({...item}))};
    this.result = output;
    return output;
  }
};
