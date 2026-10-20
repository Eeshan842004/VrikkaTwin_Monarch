// Straight, aligned arrows for the hand-laid diagrams. Coordinates are read from the laid-out elements.
const CV = () => document.getElementById('canvas').getBoundingClientRect();
function rect(id) {
  const r = document.getElementById(id).getBoundingClientRect(), c = CV();
  return {l: r.left - c.left, t: r.top - c.top, r: r.right - c.left, b: r.bottom - c.top,
          cx: r.left - c.left + r.width / 2, cy: r.top - c.top + r.height / 2};
}
const markers = {};
function marker(color) {
  if (markers[color]) return markers[color];
  const id = 'm' + Object.keys(markers).length;
  document.querySelector('#wires defs').insertAdjacentHTML('beforeend',
    `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto">
       <path d="M0,0 L10,5 L0,10 z" fill="${color}"/></marker>`);
  return markers[color] = id;
}
function path(d, color, o) {
  o = o || {};
  document.getElementById('wires').insertAdjacentHTML('beforeend',
    `<path d="${d}" fill="none" stroke="${color}" stroke-width="${o.w || 3}" stroke-linejoin="round"
       ${o.dash ? 'stroke-dasharray="8 6"' : ''} stroke-linecap="round" marker-end="url(#${marker(color)})"/>`);
}
function label(x, y, text, color) {
  const d = document.createElement('div');
  d.className = 'wire-label';
  d.style.left = x + 'px'; d.style.top = y + 'px'; d.style.color = color; d.style.borderColor = color;
  d.innerHTML = text;
  document.getElementById('canvas').appendChild(d);
}
// horizontal arrow from the right edge of a to the left edge of b at height y (default: centre of a)
function H(a, b, color, o) {
  o = o || {};
  const A = rect(a), B = rect(b), y = o.y !== undefined ? o.y : A.cy;
  path(`M${A.r + 2},${y} L${B.l - 3},${y}`, color, o);
  if (o.label) label((A.r + B.l) / 2, y - (o.lift || 0), o.label, color);
}
// vertical arrow from the bottom of a to the top of b at x (default: centre of a)
function V(a, b, color, o) {
  o = o || {};
  const A = rect(a), B = rect(b), x = o.x !== undefined ? o.x : A.cx;
  path(`M${x},${A.b + 2} L${x},${B.t - 3}`, color, o);
  if (o.label) label(x, (A.b + B.t) / 2, o.label, color);
}
// elbow arrow: right from a, down/up, then right into b
function E(a, b, color, o) {
  o = o || {};
  const A = rect(a), B = rect(b);
  const y1 = o.y1 !== undefined ? o.y1 : A.cy, y2 = o.y2 !== undefined ? o.y2 : B.cy;
  const mx = o.mx !== undefined ? o.mx : (A.r + B.l) / 2;
  path(`M${A.r + 2},${y1} L${mx},${y1} L${mx},${y2} L${B.l - 3},${y2}`, color, o);
  if (o.label) label(o.lx !== undefined ? o.lx : mx, o.ly !== undefined ? o.ly : (y1 + y2) / 2, o.label, color);
}
// free polyline through points [[x,y], ...]
function P(points, color, o) {
  path('M' + points.map(p => p.join(',')).join(' L'), color, o || {});
}
