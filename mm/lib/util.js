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


  /* end card: SUBSCRIBE button + LIKE + FOLLOW, drawn as svg (no emoji fonts needed). Lands on the last ~3 s, above the Shorts UI strip. */
  function endCta(M, parent, o) {
    const fps = o.fps || 30, a = Math.max(0, o.total - Math.round((o.secs || 3.2) * fps)), b = o.total;
    const wrap = document.createElement('div'); wrap.id = 'endcta';
    wrap.style.cssText = 'position:absolute;left:-75px;top:' + (o.y || 1260) + 'px;width:1080px;height:260px';
    wrap.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 260" width="1080" height="260" style="overflow:visible;display:block">'
      + '<defs><filter id="ctaSh" x="-20%" y="-30%" width="140%" height="180%"><feDropShadow dx="0" dy="8" stdDeviation="8" flood-opacity=".35"/></filter></defs>'
      + '<g id="ctaSub" filter="url(#ctaSh)"><rect x="150" y="40" width="540" height="130" rx="65" fill="#ff1f3d"/><rect x="150" y="40" width="540" height="62" rx="31" fill="#fff" opacity=".18"/>'
      + '<path d="M240 140 q-30 0-30-30 q0-6 4-12 l4 0 q-2 8 2 14 q6 10 20 10 q14 0 20-10 q4-6 2-14 l4 0 q4 6 4 12 q0 30-30 30z" fill="#fff" opacity="0"/>'
      + '<g transform="translate(212 105) scale(.8)"><path d="M0-34 c-18 0-30 14-30 32 v22 l-10 14 h80 l-10-14 v-22 c0-18-12-32-30-32z" fill="#fff"/><circle cx="0" cy="44" r="10" fill="#fff"/></g>'
      + '<text x="450" y="125" text-anchor="middle" font-family="Nunito, Inter, sans-serif" font-weight="900" font-size="58" fill="#fff" letter-spacing="2">SUBSCRIBE</text></g>'
      + '<g id="ctaLike" filter="url(#ctaSh)"><circle cx="790" cy="105" r="65" fill="#fff"/>'
      + '<path d="M762 120 h20 v-34 h-20z M790 120 h30 q8 0 10-8 l6-24 q2-10-8-10 h-24 l4-20 q0-8-8-8 l-10 30 v40z" fill="#1d6dff" transform="translate(-6 0)"/></g>'
      + '<g id="ctaFol" filter="url(#ctaSh)"><rect x="880" y="62" width="170" height="86" rx="43" fill="#fff"/>'
      + '<text x="965" y="120" text-anchor="middle" font-family="Nunito, Inter, sans-serif" font-weight="900" font-size="40" fill="#1b1b22">FOLLOW</text></g></svg>';
    const sw = document.createElement('div'); sw.id = 'endsweep';
    sw.style.cssText = 'position:absolute;left:0;top:0;width:1080px;height:520px;background:linear-gradient(180deg,rgba(255,255,255,0),rgba(255,255,255,.22),rgba(255,255,255,0));pointer-events:none';
    parent.appendChild(sw);
    M.show('#endsweep', a, b);
    M.kf('#endsweep', 'y', [[a, -520], [b, 1920]], { ease: 'linear' });
    parent.appendChild(wrap);
    M.show('#endcta', a, b);
    [['#ctaSub', 0], ['#ctaLike', 8], ['#ctaFol', 14]].forEach(k => {
      M.kf(k[0], 'scale', [[a + k[1], .3], [a + k[1] + 14, 1, 'popOver']]);
      M.kf(k[0], 'opacity', [[a + k[1], 0], [a + k[1] + 6, 1]]);
    });
    M.kf('#endcta', 'y', [[a, 0], [b, -40]], { ease: 'linear' });
    M.kf('#endcta', 'scale', [[a, 1], [b, 1.07]], { ease: 'linear' });
    M.kf('#endcta', 'rotation', [[a, -2], [b, 2]], { ease: 'linear' });
    return wrap;
  }

  root.MMU = { endCta, clamp, lerp, prog, eOut, eIn, eIO, eBack, rnd, hex2rgb, rgb2hex, mix, shade, Driver, put, layer };
})(typeof window !== 'undefined' ? window : globalThis);
