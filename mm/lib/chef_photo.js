/* Chef scene built on one AI-generated Pixar-style still (lib/chef_photo.jpg). Same spec as chef.js; everything is a pure function of the frame.
   Motion: slow punch-in per step, breathing, parallax drift, warm light pulse, floating dust/steam, ingredient chip, label card. */
(function (root) {
  const U = root.MMU;
  const { clamp, lerp, prog, eOut, eIO, rnd, put } = U;
  const W = 1080, H = 1920, INK = '#2b2118';
  const LEAD = 10, TAIL = 34, MIN_SLOT = 45;

  function wrap(text, max) {
    const words = String(text || '').split(/\s+/).filter(Boolean), lines = []; let cur = '';
    words.forEach(w => { if (cur && (cur + ' ' + w).length > max) { lines.push(cur); cur = w; } else cur = cur ? cur + ' ' + w : w; });
    if (cur) lines.push(cur);
    return lines.slice(0, 3).join('\n');
  }
  const el = (parent, css, html) => { const d = document.createElement('div'); d.style.cssText = css; if (html != null) d.innerHTML = html; parent.appendChild(d); return d; };

  function build(M, spec) {
    const fps = spec.fps || 30, total = Math.round(spec.duration * fps), ACC = spec.accent || '#e8542e';
    const main = document.getElementById('main'), D = U.Driver(M, fps, spec.duration);
    let steps = (spec.steps || []).slice();
    const usable = total - LEAD - TAIL, maxN = Math.max(1, Math.floor(usable / MIN_SLOT));
    if (steps.length > maxN) { const last = steps[steps.length - 1]; steps = steps.slice(0, maxN - 1).concat([last]); }
    const slot = Math.max(MIN_SLOT, Math.floor(usable / steps.length));
    const timed = steps.length > 0 && steps.every(s => typeof s.t0 === 'number' && typeof s.t1 === 'number');
    steps.forEach((s, i) => { s.i = i; s.a = timed ? Math.max(LEAD, Math.round(s.t0 * fps)) : LEAD + i * slot; s.b = timed ? Math.min(total - TAIL, Math.max(s.a + MIN_SLOT, Math.round(s.t1 * fps))) : (i === steps.length - 1 ? total - TAIL : s.a + slot); s.n = s.b - s.a; s.color = s.color || '#e8a33d'; });

    /* photo is 1664x2432 (2x of 832x1216); cover 1080x1920 -> 1314x1920, centred */
    const ph = el(main, 'position:absolute;left:0;top:0;width:' + W + 'px;height:' + H + 'px;transform-origin:50% 62%');
    /* 65-frame image-to-video clip (24 fps), played ping-pong so it loops seamlessly; every frame is a stacked <img> toggled by visibility */
    const CLIP_N = 65, CLIP_FPS = 24, CW = Math.round(H * 2 / 3);
    const still = el(ph, 'position:absolute;left:' + (-(1314 - W) / 2) + 'px;top:0;width:1314px;height:' + H + 'px;background:url(./lib/chef_photo.jpg) center/cover no-repeat');
    const clip = [], loads = [];
    for (let k = 0; k < CLIP_N; k++) {
      const im = document.createElement('img');
      im.style.cssText = 'position:absolute;left:' + (-(CW - W) / 2) + 'px;top:0;width:' + CW + 'px;height:' + H + 'px;visibility:hidden';
      loads.push(new Promise(r => { im.onload = im.onerror = r; }));
      im.src = './lib/chef_clip/s' + String(k).padStart(2, '0') + '.jpg';
      ph.appendChild(im); clip.push(im);
    }
    let shown = -1;
    ChefPhoto.ready = Promise.all(loads);
    const glow = el(main, 'position:absolute;inset:0;background:radial-gradient(ellipse at 30% 35%,rgba(255,210,140,.55),rgba(255,170,90,0) 60%);mix-blend-mode:soft-light');
    const vig = el(main, 'position:absolute;inset:0;background:radial-gradient(ellipse at 50% 55%,rgba(0,0,0,0) 55%,rgba(40,18,6,.55) 100%)');

    /* dust motes / steam drifting up */
    const motes = Array.from({ length: 14 }, (_, i) => el(main, 'position:absolute;left:0;top:0;width:' + (10 + rnd(i) * 22) + 'px;height:' + (10 + rnd(i) * 22) + 'px;border-radius:50%;background:radial-gradient(#fff6dc,rgba(255,240,200,0));'));

    /* label card + ingredient chip per step */
    steps.forEach(s => {
      const w = el(main, 'position:absolute;left:70px;top:1390px;width:940px;display:flex;justify-content:center;visibility:hidden');
      const card = el(w, 'padding:34px 48px;border-radius:44px;background:rgba(255,246,230,.92);box-shadow:0 18px 50px rgba(40,18,6,.35);max-width:940px');
      const t = el(card, 'text-align:center;font:800 92px/108px Nunito,Inter,sans-serif;color:' + INK + ';white-space:pre'); t.id = 'labt' + s.i;
      t.textContent = wrap(s.label || s.ingredient || s.action, 16);
      s.lab = w; s.card = card;
      M.words('#labt' + s.i, { at: s.a + 2, mech: 'rise', dist: 70, frames: 12, gaps: [3], accent: { color: ACC, frames: 18 } });
      const name = (s.ingredient || '').trim();
      s.chip = name ? el(main, 'position:absolute;left:0;top:90px;width:' + W + 'px;padding-left:50px;display:flex;justify-content:flex-start;visibility:hidden', '') : null;
      if (s.chip) {
        const c = el(s.chip, 'display:flex;align-items:center;gap:22px;padding:20px 40px;border-radius:60px;background:rgba(255,246,230,.94);box-shadow:0 14px 40px rgba(40,18,6,.4);font:800 56px/62px Nunito,Inter,sans-serif;color:' + INK + ';max-width:640px;white-space:nowrap');
        el(c, 'width:56px;height:56px;border-radius:50%;background:' + s.color + ';box-shadow:inset -8px -8px 14px rgba(0,0,0,.18),inset 6px 6px 10px rgba(255,255,255,.5)');
        el(c, '', '').textContent = name; s.chipBody = c;
      }
    });

    const cur = f => steps.find(s => f < s.b) || steps[steps.length - 1];
    D.add(f => {
      const st = cur(f), u = clamp((f - st.a) / st.n, 0, 1), alt = st.i % 2 ? -1 : 1;
      const breath = Math.sin(f * 0.09), sway = Math.sin(f * 0.035);
      /* punch-in resets a little each step, then creeps in; whole film also slowly dollies */
      const sc = 1.03 + eIO(u) * 0.075 + breath * 0.004 + (f / total) * 0.03 + eOut(prog(f, st.a, st.a + 10)) * -0.0;
      put(ph, { x: sway * 14 + alt * (u - .5) * 40, y: breath * -5 + (u - .5) * -24, s: sc, r: sway * 0.35 });
      const cp = Math.floor(f * CLIP_FPS / fps) % (2 * (CLIP_N - 1)), ci = cp < CLIP_N ? cp : 2 * (CLIP_N - 1) - cp;
      if (ci !== shown) { if (shown >= 0) clip[shown].style.visibility = 'hidden'; clip[ci].style.visibility = ''; shown = ci; }
      glow.style.opacity = (0.55 + Math.sin(f * 0.07) * 0.25).toFixed(3);
      steps.forEach(s => {
        const on = f >= s.a && f < s.b, o = on ? 1 - prog(f, s.b - 8, s.b) : 0;
        s.lab.style.visibility = o > 0.01 ? '' : 'hidden'; s.lab.style.opacity = o.toFixed(3);
        if (s.chip) {
          const co = on ? eOut(prog(f, s.a + 14, s.a + 24)) * (1 - prog(f, s.b - 8, s.b)) : 0;
          s.chip.style.visibility = co > 0.01 ? '' : 'hidden'; s.chip.style.opacity = co.toFixed(3);
          s.chipBody.style.transform = 'scale(' + (0.7 + 0.3 * eOut(prog(f, s.a + 14, s.a + 26))).toFixed(3) + ') translateY(' + ((1 - co) * 30).toFixed(1) + 'px)';
        }
      });
      motes.forEach((m, i) => {
        const ph0 = ((f * (0.004 + rnd(i + 3) * 0.004)) + rnd(i + 40)) % 1;
        put(m, { x: 60 + rnd(i + 8) * 960 + Math.sin(ph0 * 7 + i) * 40, y: 1700 - ph0 * 1500, s: 0.6 + ph0 * 0.8, o: Math.sin(ph0 * Math.PI) * 0.55 });
      });
    });
    return { steps, slot, total };
  }
  root.ChefPhoto = { build, wrap };
})(typeof window !== 'undefined' ? window : globalThis);
