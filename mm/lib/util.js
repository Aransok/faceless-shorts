/* Shared helpers for the motionmaxxing templates (plain browser JS, no modules).
   Everything here is deterministic: no Math.random, no Date. A pose is a pure function of the frame. */
(function (root) {
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const prog = (f, a, b) => clamp((f - a) / Math.max(1e-6, b - a), 0, 1);
  const eOut = t => 1 - Math.pow(1 - t, 3);
  const eIn = t => t * t * t;
  const eIO = t => t * t * (3 - 2 * t);
  const eBack = t => { const c = 1.9; const x = t - 1; return 1 + (c + 1) * x * x * x + c * x * x; };
  const rnd = i => { const s = Math.sin(i * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };

  function hex2rgb(h) {
    h = String(h || '#888888').replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb2hex = c => '#' + c.map(v => clamp(Math.round(v), 0, 255).toString(16).padStart(2, '0')).join('');
  const mix = (a, b, t) => { const A = hex2rgb(a), B = hex2rgb(b); return rgb2hex(A.map((v, i) => lerp(v, B[i], t))); };
  const shade = (c, t) => (t >= 0 ? mix(c, '#ffffff', t) : mix(c, '#000000', -t));

  /* Pose driver: one setter tweened across the whole film (same trick the runtime uses for its own renderer),
     so every actor is re-posed as a pure function of the frame on every seek. */
  function Driver(M, fps, duration) {
    const fns = [];
    const drv = {};
    Object.defineProperty(drv, 't', { get: () => 0, set: t => { const f = Math.floor(t * fps + 1e-6); for (let i = 0; i < fns.length; i++) fns[i](f); } });
    M.tl.fromTo(drv, { t: 0 }, { t: duration, duration, ease: 'none', immediateRender: false, lazy: false }, 0);
    return { add: fn => { fns.push(fn); return fn; } };
  }

  /* write a pose to an element. Transform order: translate, rotate, scale about the element's own transform-origin. */
  function put(el, p) {
    const x = p.x || 0, y = p.y || 0, r = p.r || 0, sx = p.sx != null ? p.sx : (p.s != null ? p.s : 1), sy = p.sy != null ? p.sy : (p.s != null ? p.s : 1);
    el.style.transform = 'translate(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px) rotate(' + r.toFixed(2) + 'deg) scale(' + sx.toFixed(4) + ',' + sy.toFixed(4) + ')';
    const o = p.o != null ? p.o : 1;
    el.style.opacity = o >= 0.999 ? '' : o.toFixed(3);
    el.style.visibility = o <= 0.001 ? 'hidden' : '';
  }

  /* absolutely-positioned layer holding one inline svg; origin = [x,y] css transform-origin in the layer's own px */
  function layer(parent, o) {
    const d = document.createElement('div');
    d.className = 'ly' + (o.cls ? ' ' + o.cls : '');
    d.style.cssText = 'position:absolute;left:' + (o.left || 0) + 'px;top:' + (o.top || 0) + 'px;width:' + o.w + 'px;height:' + o.h + 'px;transform-origin:' + (o.origin ? o.origin[0] + 'px ' + o.origin[1] + 'px' : '0 0') + ';' + (o.style || '');
    if (o.id) d.id = o.id;
    d.innerHTML = o.svg != null ? '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + (o.vb || ('0 0 ' + o.w + ' ' + o.h)) + '" width="' + o.w + '" height="' + o.h + '" style="overflow:visible;display:block">' + o.svg + '</svg>' : (o.html || '');
    parent.appendChild(d);
    return d;
  }

  root.MMU = { clamp, lerp, prog, eOut, eIn, eIO, eBack, rnd, hex2rgb, rgb2hex, mix, shade, Driver, put, layer };
})(typeof window !== 'undefined' ? window : globalThis);
