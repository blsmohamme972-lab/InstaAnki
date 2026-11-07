/* Deterministic teaching cues. Every visual is derived from the media clock. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.VisualGuidance = api;
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const limit = (value, low, high) => Math.max(low, Math.min(high, value));
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const unit = value => finite(value) && value >= 0 && value <= 1;
  const neutral = () => ({ x: .5, y: .5, scale: 1 });
  const smooth = p => p * p * p * (p * (p * 6 - 15) + 10);

  function validTarget(target, image) {
    return !!target && target.image === image && unit(target.x) && unit(target.y) &&
      finite(target.rx) && target.rx > 0 && target.rx <= 1 &&
      finite(target.ry) && target.ry > 0 && target.ry <= 1 &&
      (target.spotX == null || unit(target.spotX)) && (target.spotY == null || unit(target.spotY));
  }

  function resolve(guidance, seconds, image, outro) {
    if (guidance?.schemaVersion !== 1 || !Array.isArray(guidance.cues) || !finite(seconds)) return null;
    const index = guidance.cues.findIndex(cue => finite(cue.start) && finite(cue.end) && seconds >= cue.start && seconds < cue.end);
    if (index < 0) {
      const target = guidance.targets?.[guidance.outroTargetId];
      if (outro && finite(outro.start) && finite(outro.end) && seconds >= outro.start && seconds < outro.end && validTarget(target, image)) {
        return { index: -1, target, cue: { id: 'real-image-outro', sceneId: 'real-image-outro',
          start: outro.start, end: outro.end, text: '', targetId: guidance.outroTargetId }, outro: true };
      }
      return null;
    }
    const cue = guidance.cues[index];
    const target = guidance.targets?.[cue.targetId];
    return { cue, index, target: validTarget(target, image) ? target : null };
  }

  function pose(target) {
    return target ? { x: target.spotX ?? target.x, y: target.spotY ?? target.y,
      scale: limit(finite(target.zoom) ? target.zoom : 1.12, 1, 1.3) } : neutral();
  }

  function cameraAt(guidance, active, seconds, image, still = false) {
    if (still || !active) return neutral();
    const to = pose(active.target);
    const previous = guidance.cues[active.index - 1];
    const previousTarget = previous && guidance.targets?.[previous.targetId];
    // Never pan from another photograph or retain a target through an unannotated phrase.
    const from = previous && Math.abs(previous.end - active.cue.start) < .001 && validTarget(previousTarget, image)
      ? pose(previousTarget) : neutral();
    const transition = Math.min(.48, (active.cue.end - active.cue.start) / 3);
    const p = smooth(limit((seconds - active.cue.start) / Math.max(.001, transition), 0, 1));
    return { x: from.x + (to.x - from.x) * p, y: from.y + (to.y - from.y) * p,
      scale: from.scale + (to.scale - from.scale) * p };
  }

  function geometry(box, naturalWidth, naturalHeight, camera = neutral()) {
    if (![box.x, box.y, box.width, box.height, naturalWidth, naturalHeight].every(finite) ||
        box.width <= 0 || box.height <= 0 || naturalWidth <= 0 || naturalHeight <= 0) return null;
    const fit = Math.min(box.width / naturalWidth, box.height / naturalHeight);
    const width = naturalWidth * fit, height = naturalHeight * fit;
    const scale = limit(camera.scale, 1, 1.3);
    // If an image fits, pan within its letterboxing. If zoomed, constrain its cropped edge.
    const roomX = Math.abs(width * scale - box.width) / 2;
    const roomY = Math.abs(height * scale - box.height) / 2;
    const panX = limit((.5 - camera.x) * width * scale, -roomX, roomX);
    const panY = limit((.5 - camera.y) * height * scale, -roomY, roomY);
    const centerX = box.x + box.width / 2 + panX, centerY = box.y + box.height / 2 + panY;
    return { width, height, scale, panX, panY, centerX, centerY,
      project: (x, y) => ({ x: centerX + (x - .5) * width * scale, y: centerY + (y - .5) * height * scale }) };
  }

  function pointer(point, box) {
    // Keep the hand on the roomy side of the feature. The arrow tip never moves off it.
    const dx = point.x < box.x + box.width / 2 ? 1 : -1;
    const dy = point.y < box.y + box.height / 2 ? 1 : -1;
    const length = limit(box.width * .17, 40, 62);
    const tail = {
      x: limit(point.x + dx * length, box.x + 26, box.x + box.width - 26),
      y: limit(point.y + dy * length * .55, box.y + 32, box.y + box.height - 32)
    };
    const angle = Math.atan2(point.y - tail.y, point.x - tail.x);
    const ux = Math.cos(angle), uy = Math.sin(angle);
    const head = `M ${point.x} ${point.y} L ${point.x - 10 * ux + 4.5 * uy} ${point.y - 10 * uy - 4.5 * ux} L ${point.x - 10 * ux - 4.5 * uy} ${point.y - 10 * uy + 4.5 * ux} Z`;
    return { tail, shaft: `M ${tail.x} ${tail.y} L ${point.x} ${point.y}`, head,
      hand: `translate(${tail.x} ${tail.y}) rotate(${angle * 180 / Math.PI + 90}) scale(.8)` };
  }
  return { resolve, cameraAt, geometry, pointer, validTarget };
});
