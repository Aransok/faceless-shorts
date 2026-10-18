/* Chef scene builder: JSON step list -> film. Stage is 1080x1920. Everything is a pure function of the frame (see util.js Driver).
   spec = { fps, duration, accent, voiced, steps:[{action,ingredient,into,color,label,prop?}] }
   actions: pour | sprinkle | stir | drizzle | whisk | plate */
(function (root) {
  const U = root.MMU, A = root.ChefArt;
  const { clamp, lerp, prog, eOut, eIO, rnd, mix, shade, put, layer } = U;
  const W = 1080, H = 1920, BASE = [540, 1560], CHEF = { x: 176, y: 560, s: 1.4 };
  const REST_R = [700, 1420], REST_L = [380, 1420], SHELF = [980, 1290];
  const WALLS = ['#f7dcb4', '#f5d3a8', '#f8dfc0', '#f1cb9e', '#f6d6b2', '#f3d0a6'];
  const INK = '#2b2118';
  const LEAD = 10, TAIL = 34, MIN_SLOT = 45;

  const LIQ = /oil|vinegar|sauce|soy|wine|syrup|honey|cream|butter|lemon|juice/i;
  const WATERY = /water|milk|stock|broth|tea|coffee/i;
  function propFor(st) {
    if (st.prop) return st.prop;
    switch (st.action) {
      case 'sprinkle': return 'jar';
      case 'stir': return 'spoon';
      case 'whisk': return 'whisk';
      case 'drizzle': return 'bottle';
      default: return WATERY.test(st.ingredient || '') ? 'cup' : (LIQ.test(st.ingredient || '') ? 'bottle' : 'cup');
    }
  }

  function wrap(text, max) {
    const words = String(text || '').split(/\s+/).filter(Boolean), lines = []; let cur = '';
    words.forEach(w => { if (cur && (cur + ' ' + w).length > max) { lines.push(cur); cur = w; } else cur = cur ? cur + ' ' + w : w; });
    if (cur) lines.push(cur);
    return lines.slice(0, 3).join('\n');
  }

  /* piecewise path: keys [[u,x,y,r,flow],...] with smooth easing between */
  function path(u, keys) {
    if (u <= keys[0][0]) return keys[0].slice(1);
    for (let i = 1; i < keys.length; i++) {
      if (u <= keys[i][0]) {
        const a = keys[i - 1], b = keys[i], t = eIO(prog(u, a[0], b[0]));
        return [lerp(a[1], b[1], t), lerp(a[2], b[2], t), lerp(a[3] || 0, b[3] || 0, t), lerp(a[4] || 0, b[4] || 0, t)];
      }
    }
    return keys[keys.length - 1].slice(1);
  }
  const rot = (p, deg) => { const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a); return [p[0] * c - p[1] * s, p[0] * s + p[1] * c]; };

  function build(M, spec) {
    const fps = spec.fps || 30, total = Math.round(spec.duration * fps), ACC = spec.accent || '#e8542e';
    const main = document.getElementById('main');
    const D = U.Driver(M, fps, spec.duration);

    /* ---------- timeline ---------- */
    let steps = (spec.steps || []).slice();
    const usable = total - LEAD - TAIL;
    const maxN = Math.max(1, Math.floor(usable / MIN_SLOT));
    if (steps.length > maxN) { const last = steps[steps.length - 1]; steps = steps.slice(0, maxN - 1).concat([last]); }
    const slot = Math.max(MIN_SLOT, Math.floor(usable / steps.length));
    const timed = steps.length > 0 && steps.every(s => typeof s.t0 === 'number' && typeof s.t1 === 'number');
    steps.forEach((s, i) => { s.i = i; s.a = timed ? Math.max(LEAD, Math.round(s.t0 * fps)) : LEAD + i * slot; s.b = timed ? Math.min(total - TAIL, Math.max(s.a + MIN_SLOT, Math.round(s.t1 * fps))) : (i === steps.length - 1 ? total - TAIL : s.a + slot); s.n = s.b - s.a; s.prop = propFor(s); s.into = s.into || (s.action === 'plate' ? 'plate' : 'bowl'); s.color = s.color || '#c9a227'; });

    /* ---------- backdrop ---------- */
    const wall = document.createElement('div'); wall.id = 'wall';
    wall.style.cssText = 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;background:' + WALLS[0];
    main.appendChild(wall);
    layer(main, { w: W, h: H, svg: `
      <g opacity=".5" stroke="#000" stroke-opacity=".07" stroke-width="3">${Array.from({ length: 10 }, (_, i) => `<path d="M0 ${i * 90 + 440} H${W}"/>`).join('')}${Array.from({ length: 13 }, (_, i) => `<path d="M${i * 90} 440 V1200"/>`).join('')}</g>
      <defs>
        <radialGradient id="kGlow" cx="895" cy="590" r="520" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff3c8" stop-opacity=".95"/><stop offset=".35" stop-color="#ffd48a" stop-opacity=".45"/><stop offset="1" stop-color="#ffb060" stop-opacity="0"/></radialGradient>
        <radialGradient id="kVig" cx="540" cy="900" r="1150" gradientUnits="userSpaceOnUse"><stop offset=".55" stop-color="#3a1c08" stop-opacity="0"/><stop offset="1" stop-color="#3a1c08" stop-opacity=".5"/></radialGradient>
        <linearGradient id="kWin" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff8dc"/><stop offset="1" stop-color="#ffd890"/></linearGradient>
        <filter id="kBlur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="16"/></filter>
        <filter id="kBlur2" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="40"/></filter>
      </defs>
      <rect x="0" y="0" width="${W}" height="1500" fill="url(#kGlow)"/>
      <rect x="790" y="470" width="210" height="240" rx="26" fill="url(#kWin)"/>
      <rect x="808" y="488" width="174" height="204" rx="18" fill="none" stroke="#fff" stroke-width="10" opacity=".9"/>
      <path d="M895 488 V692 M808 590 H982" stroke="#fff" stroke-width="8" opacity=".9"/>
      <g filter="url(#kBlur)">${[[120, 760, 46, '#ffd27a'], [250, 880, 34, '#ffb35c'], [60, 1010, 40, '#ffc98a'], [610, 700, 30, '#ffe7a8'], [700, 960, 52, '#ffb86b'], [420, 780, 26, '#fff0b8'], [960, 920, 44, '#ffcf86'], [820, 1130, 36, '#ffbd70']].map(b => `<circle cx="${b[0]}" cy="${b[1]}" r="${b[2]}" fill="${b[3]}" opacity=".55"/>`).join('')}</g>
      <rect x="0" y="1380" width="${W}" height="130" fill="#7a4a22" opacity=".25" filter="url(#kBlur2)"/>
      <rect x="0" y="0" width="${W}" height="${H}" fill="url(#kVig)"/>` });
    const stage = document.createElement('div'); stage.style.cssText = 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px'; main.appendChild(stage);

    /* ---------- chef (body+head), counter, vessels, props, arms ---------- */
    const rig = A.buildChef(stage, { x: CHEF.x, y: CHEF.y, scale: CHEF.s });
    layer(stage, { w: W, h: 460, left: 0, top: 1490, svg: `
      <defs><linearGradient id="cWood" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c8935f"/><stop offset="1" stop-color="#8f5f36"/></linearGradient><linearGradient id="cTop" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f0c590"/><stop offset="1" stop-color="#cf9a64"/></linearGradient><filter id="cB"><feGaussianBlur stdDeviation="8"/></filter></defs>
      <rect x="0" y="0" width="${W}" height="460" fill="url(#cWood)"/><rect x="0" y="0" width="${W}" height="34" fill="url(#cTop)"/>
      <rect x="0" y="4" width="${W}" height="6" fill="#fff" opacity=".4"/>
      <rect x="0" y="34" width="${W}" height="26" fill="#000" opacity=".22" filter="url(#cB)"/>
      ${Array.from({ length: 6 }, (_, i) => `<rect x="${i * 190 + 12}" y="90" width="166" height="330" rx="16" fill="#a8744a" stroke="#8f5f3a" stroke-width="5"/>`).join('')}` });

    const vessels = {};
    steps.forEach(s => {
      if (vessels[s.into]) return;
      const V = A.VESSELS[s.into] || A.VESSELS.bowl;
      const el = document.createElement('div');
      el.style.cssText = 'position:absolute;left:' + BASE[0] + 'px;top:' + BASE[1] + 'px;width:0;height:0';
      const body = layer(el, { w: 1, h: 1, svg: V.mk(), vb: '0 0 1 1' });
      const surf = layer(el, { w: 1, h: 1, svg: '<ellipse cx="0" cy="0" rx="' + V.sx + '" ry="' + V.sy + '" fill="#ccc"/>', vb: '0 0 1 1' });
      stage.appendChild(el);
      vessels[s.into] = { V, el, surf, ell: surf.querySelector('ellipse'), adds: [], name: s.into, first: s.a };
    });
    /* steam puffs */
    const puffs = Array.from({ length: 7 }, (_, i) => { const d = document.createElement('div'); d.style.cssText = 'position:absolute;left:0;top:0;width:60px;height:60px;margin:-30px 0 0 -30px;border-radius:50%;background:#fff'; stage.appendChild(d); return d; });

    /* contents model: each non-stir action adds an ingredient during its work phase */
    steps.forEach(s => {
      const v = vessels[s.into];
      if (s.action === 'pour' || s.action === 'sprinkle' || s.action === 'drizzle') v.adds.push({ a: s.a + s.n * .42, b: s.a + s.n * .78, w: s.action === 'sprinkle' ? .12 : (s.action === 'drizzle' ? .2 : .32), c: s.color });
    });
    const contents0 = (v, f) => {
      let tot = 0, r = 0, g = 0, b = 0;
      v.adds.forEach(ad => { const k = ad.w * prog(f, ad.a, ad.b); if (k > 0) { const c = U.hex2rgb(ad.c); tot += k; r += c[0] * k; g += c[1] * k; b += c[2] * k; } });
      return { amt: clamp(tot, 0, 1), col: tot > 0 ? U.rgb2hex([r / tot, g / tot, b / tot]) : '#d8d0c0' };
    };

    const contents = (v, f) => {
      const c = contents0(v, f);
      return c;
    };
    steps.forEach(s => {
      if (s.action !== 'plate') return;
      const src = Object.keys(vessels).filter(k => k !== s.into).map(k => vessels[k]).pop();
      const c = src ? contents0(src, s.a) : { col: '#d8b36a' };
      vessels[s.into].adds.push({ a: s.a + s.n * .38, b: s.a + s.n * .58, w: 1, c: c.col });
    });

    const propEls = steps.map(s => {
      const P = A.PROPS[s.prop](s.color), el = layer(stage, { w: P.w, h: P.h, svg: P.svg, left: -P.o[0], top: -P.o[1], origin: P.o });
      el.style.visibility = 'hidden';
      return { P, el, s };
    });
    const streamEl = document.createElement('div'); streamEl.style.cssText = 'position:absolute;left:0;top:0;width:16px;height:10px;border-radius:8px;transform-origin:50% 0'; stage.appendChild(streamEl);
    const grains = Array.from({ length: 16 }, () => { const d = document.createElement('div'); d.style.cssText = 'position:absolute;left:0;top:0;width:12px;height:12px;margin:-6px;border-radius:50%'; stage.appendChild(d); return d; });
    A.buildArms(stage, rig);

    /* ---------- labels ---------- */
    const labs = steps.map(s => {
      const w = document.createElement('div'); w.id = 'lab' + s.i;
      w.style.cssText = 'position:absolute;left:70px;top:150px;width:940px;height:330px;display:flex;align-items:center;justify-content:center;visibility:hidden';
      const t = document.createElement('div'); t.id = 'labt' + s.i;
      t.style.cssText = 'position:absolute;left:0;top:0;width:940px;height:330px;text-align:center;font:800 100px/116px Nunito,Inter,sans-serif;color:' + INK + ';white-space:pre';
      t.textContent = wrap(s.label || s.ingredient || s.action, 15);
      w.appendChild(t); main.appendChild(w); s.lab = w;
      return w;
    });
    steps.forEach(s => {
      M.words('#labt' + s.i, { at: s.a + 2, mech: 'rise', dist: 70, frames: 12, gaps: [3], accent: { color: ACC, frames: 18 } });
    });

    /* ---------- per-frame pose ---------- */
    const cur = f => steps.find(s => f < s.b) || steps[steps.length - 1];
    let lastSt = null;
    D.add(f => {
      const st = cur(f), v = vessels[st.into], u = clamp((f - st.a) / st.n, 0, 1);
      /* wall tint */
      wall.style.background = WALLS[st.i % WALLS.length];
      /* labels */
      steps.forEach(s => { const o = f >= s.a && f < s.b ? 1 - prog(f, s.b - 8, s.b) : 0; s.lab.style.visibility = o > 0.01 ? '' : 'hidden'; s.lab.style.opacity = o.toFixed(3); });
      /* chef idle: breathing, lagged head (follow-through), smooth blink, eye darts, talk nods */
      const speaking = f > 4 && f < total - TAIL + 10, open = speaking && rnd(Math.floor(f / 3) + 11) > .42;
      const breath = Math.sin(f * 0.09), bob = Math.sin(f * 0.14) * 3.2, tilt = Math.sin(f * 0.07 - .5) * 1.8;
      const work = prog(u, .3, .5) * (1 - prog(u, .8, .95)), nod = speaking ? Math.sin(f * .42) * 1.1 + (open ? 1.2 : 0) : 0;
      put(rig.body, { y: bob * .5, sy: 1 + breath * .012, sx: 1 - breath * .006 });
      put(rig.head, { y: bob * .6 + breath * -2.2 + nod + work * 4, r: tilt + work * -3.2, sy: 1 + (open ? .012 : 0) });
      const bp = (f + Math.floor(rnd(7) * 30)) % 96, bl = bp < 7 ? Math.sin(bp / 7 * Math.PI) : 0;
      const dk = Math.floor(f / 38), dn = prog(f % 38, 0, 5), ex = lerp((rnd(dk + 3) - .5) * 14, (rnd(dk + 4) - .5) * 14, eIO(dn)), ey = lerp((rnd(dk + 9) - .5) * 6, (rnd(dk + 10) - .5) * 6, eIO(dn));
      put(rig.mouthClosed, { o: open ? 0 : 1 }); put(rig.mouthOpen, { o: open ? 1 : 0 });

      /* vessels: slide between steps */
      Object.keys(vessels).forEach(k => {
        const vv = vessels[k], first = vv.first, active = vv === v;
        const vs = steps.filter(s => s.into === k), lastEnd = vs[vs.length - 1].b;
        let slideIn = prog(f, first - 12, first + 2), slideOut = active || f < lastEnd ? 0 : prog(f, lastEnd, lastEnd + 14);
        if (!active && f >= first && f < lastEnd) { slideOut = 0; }
        const vis = f >= first - 12 && (f < lastEnd || active || slideOut < 1);
        const x = (1 - eOut(slideIn)) * 700 - eIO(slideOut) * 700;
        put(vv.el, { x, o: vis ? 1 : 0 });
        const c = contents(vv, f);
        vv.ell.setAttribute('fill', c.col);
        vv.ell.setAttribute('opacity', c.amt > 0.001 ? '1' : '0');
        const sc = 0.35 + 0.65 * c.amt;
        vv.ell.setAttribute('transform', 'translate(0,' + (vv.V.rim[1] + (1 - c.amt) * 20) + ') scale(' + sc.toFixed(3) + ')');
      });

      /* steam */
      const hot = st.into === 'pan' || st.into === 'pot';
      puffs.forEach((p, i) => {
        const ph = ((f * 0.012 + i / puffs.length) % 1), ox = (i - 3) * 22 + Math.sin(ph * 6 + i) * 18;
        const o = hot ? Math.sin(ph * Math.PI) * 0.34 : 0, y = BASE[1] + v.V.rim[1] - 20 - ph * 240;
        put(p, { x: BASE[0] + ox + (hot ? 0 : 9999), y, s: 0.5 + ph * 1.4, o });
      });

      /* hands */
      const rimY = BASE[1] + v.V.rim[1], rx = BASE[0];
      let gR = REST_R.slice(), rR = 0, flow = 0, hold = false, tip = null;
      const P = propEls[st.i];
      propEls.forEach(pe => { pe.el.style.visibility = 'hidden'; });
      streamEl.style.visibility = 'hidden'; grains.forEach(g => { g.style.visibility = 'hidden'; });
      let gL = [rx - v.V.rx - 40, rimY + 40];
      if (st.action === 'plate') {
        gR = path(u, [[0, REST_R[0], REST_R[1]], [.3, 820, 1110], [.6, 840, 1050], [1, REST_R[0], REST_R[1]]]);
        gL = path(u, [[0, gL[0], gL[1]], [.3, 240, 1110], [.6, 220, 1050], [1, REST_L[0], REST_L[1]]]);
      } else if (st.action === 'pour' || st.action === 'drizzle' || st.action === 'sprinkle') {
        const sp = P.P.spout;
        const tiltR = st.action === 'pour' ? -102 : (st.action === 'drizzle' ? -78 : -128);
        const sweep = st.action === 'drizzle' ? Math.sin(u * 14) * 70 : 0;
        const shake = st.action === 'sprinkle' ? Math.sin(f * .9) * 9 : 0;
        const r = tiltR + shake;
        const tgt = [rx + 24 + sweep, rimY - 58];
        const so = rot(sp, tiltR);
        const gw = [tgt[0] - so[0], tgt[1] - so[1]];
        const over = [rx + 230, rimY - 250 - Math.abs(sp[1]) * .1];
        const k = path(u, [[0, REST_R[0], REST_R[1], 0], [.14, SHELF[0], SHELF[1], 0], [.34, over[0], over[1], 0], [.5, gw[0], gw[1], tiltR], [.76, gw[0], gw[1], tiltR], [.84, over[0], over[1], 0], [.93, SHELF[0], SHELF[1], 0], [1, REST_R[0], REST_R[1], 0]]);
        gR = [k[0] + (u > .5 && u < .76 ? sweep * .0 : 0), k[1]]; rR = k[2] + (u > .5 && u < .76 ? shake : 0);
        hold = u > .14 && u < .93;
        const so2 = rot(sp, rR), spoutAt = [gR[0] + so2[0], gR[1] + so2[1]];
        const on = prog(u, .5, .56) * (1 - prog(u, .72, .78));
        if (on > 0.02) {
          if (st.action === 'sprinkle') {
            grains.forEach((g, i) => {
              const ph = (f * .045 + rnd(i * 3 + st.i)) % 1, y = spoutAt[1] + ph * (rimY - spoutAt[1]);
              g.style.visibility = ''; g.style.background = i % 3 ? st.color : shade(st.color, .25);
              put(g, { x: spoutAt[0] + (rnd(i + 20) - .5) * 44 * ph, y, o: on });
            });
          } else {
            const wdt = st.action === 'drizzle' ? 9 : 17, len = Math.max(10, rimY - spoutAt[1]);
            streamEl.style.visibility = ''; streamEl.style.background = st.color; streamEl.style.width = (wdt + Math.sin(f * .5) * 2).toFixed(1) + 'px'; streamEl.style.height = (len * on).toFixed(1) + 'px';
            streamEl.style.transform = 'translate(' + (spoutAt[0] - wdt / 2).toFixed(1) + 'px,' + spoutAt[1].toFixed(1) + 'px)';
            streamEl.style.opacity = '1';
          }
        }
      } else { /* stir / whisk */
        const sp = P.P.spout, fast = st.action === 'whisk';
        const ang = (f - st.a) * (fast ? .55 : .27), rad = fast ? 34 : 62;
        const tipP = [rx + Math.cos(ang) * rad, rimY + 4 + Math.sin(ang) * rad * .28];
        const lean = Math.cos(ang) * (fast ? 4 : 9);
        const so = rot(sp, lean), gw = [tipP[0] - so[0], tipP[1] - so[1] - (fast ? Math.abs(Math.sin(ang * 2)) * 26 : 0)];
        const over = [rx + 150, rimY - 300];
        const k = path(u, [[0, REST_R[0], REST_R[1], 0], [.14, SHELF[0], SHELF[1], 0], [.34, over[0], over[1], 0], [.46, gw[0], gw[1], lean], [.78, gw[0], gw[1], lean], [.86, over[0], over[1], 0], [.93, SHELF[0], SHELF[1], 0], [1, REST_R[0], REST_R[1], 0]]);
        const working = u >= .46 && u <= .78;
        gR = working ? gw : [k[0], k[1]]; rR = working ? lean : k[2];
        hold = u > .14 && u < .93;
        gL = [rx - v.V.rx - 40 + (working ? Math.sin(ang) * 6 : 0), rimY + 40];
      }
      /* settle: damped overshoot after each arrival so hand moves feel weighted */
      const arr = st.action === 'plate' ? [.3, .6] : [.14, .34, .5, .93];
      let sett = 0; arr.forEach(t0 => { const d = (u - t0) * st.n; if (d > 0 && d < 30) sett += Math.exp(-d / 6) * Math.sin(d * .8) * 9; });
      gR = [gR[0], gR[1] + sett];
      const lk = clamp((gR[0] - 540) / 540, -1, 1) * 8 * work;
      put(rig.eyes, { x: ex + lk, y: ey + work * 2, sy: 1 - bl * .93 });
      A.poseArm(rig, 'R', gR);
      A.poseArm(rig, 'L', gL);
      if (hold && P) { P.el.style.visibility = ''; put(P.el, { x: gR[0], y: gR[1], r: rR }); }
    });

    /* plate moment: vessel contents become the mound shown by the plate vessel (surf), so no extra work needed here */
    return { steps, slot, total };
  }

  root.ChefScene = { build, propFor, wrap, path };
})(typeof window !== 'undefined' ? window : globalThis);
