/* ORIGINAL chef character + kitchen props as layered SVG. Not based on any existing character or mascot.
   Chef: cute, chubby, round glasses, blond swoop hair, teal shirt, cream apron. Local art box is 520x760.
   Every animated part is its own layer so the rig can move it: body, head, eyes, mouth, and per arm: upper, fore, hand. */
(function (root) {
  const { layer, mix, shade } = root.MMU;

  const C = { skin: '#ffd7b6', skinD: '#f0b48f', hair: '#f3c13d', hairD: '#d9a021', shirt: '#3f9d98', shirtD: '#2f7f7b', apron: '#fff6e8', apronD: '#eadcc6', ink: '#3a2a1f', blush: '#ff9d94', tie: '#ff6a3d' };
  const BOX = { w: 520, h: 760 };
  const SH = { L: [105, 430], R: [415, 430] };   // shoulder pivots (local)
  const L1 = 150, L2 = 150;                       // upper arm / forearm length (local)

  const bodySvg = () => `
    <ellipse cx="260" cy="735" rx="150" ry="22" fill="#000" opacity=".12"/>
    <ellipse cx="260" cy="520" rx="205" ry="220" fill="${C.shirt}"/>
    <ellipse cx="260" cy="520" rx="205" ry="220" fill="none" stroke="${C.shirtD}" stroke-width="6"/>
    <path d="M150 395 Q260 372 370 395 L405 640 Q260 705 115 640 Z" fill="${C.apron}" stroke="${C.apronD}" stroke-width="6" stroke-linejoin="round"/>
    <rect x="205" y="560" width="110" height="70" rx="18" fill="${C.apronD}" opacity=".55"/>
    <path d="M205 560 H315" stroke="${C.apronD}" stroke-width="5" opacity=".9"/>
    <path d="M175 392 L260 452 L345 392 Q260 372 175 392Z" fill="${C.tie}"/>
    <circle cx="260" cy="418" r="9" fill="${shade(C.tie, -.18)}"/>`;

  const headSvg = () => `
    <ellipse cx="92" cy="268" rx="30" ry="34" fill="${C.skin}"/><ellipse cx="428" cy="268" rx="30" ry="34" fill="${C.skin}"/>
    <ellipse cx="92" cy="270" rx="15" ry="19" fill="${C.skinD}" opacity=".6"/><ellipse cx="428" cy="270" rx="15" ry="19" fill="${C.skinD}" opacity=".6"/>
    <ellipse cx="260" cy="258" rx="172" ry="152" fill="${C.skin}"/>
    <ellipse cx="260" cy="396" rx="95" ry="26" fill="${C.skinD}" opacity=".35"/>
    <ellipse cx="148" cy="322" rx="34" ry="22" fill="${C.blush}" opacity=".55"/><ellipse cx="372" cy="322" rx="34" ry="22" fill="${C.blush}" opacity=".55"/>
    <ellipse cx="260" cy="304" rx="11" ry="8" fill="${C.skinD}"/>
    <path d="M86 250 C70 150 170 78 262 90 C360 78 452 150 434 250 C420 205 372 176 322 172 C290 196 236 180 206 168 C150 176 104 205 86 250Z" fill="${C.hair}"/>
    <path d="M206 168 C240 120 300 112 340 150 C300 138 250 140 206 168Z" fill="${C.hairD}" opacity=".7"/>
    <path d="M250 92 C236 52 270 28 304 44 C282 54 284 74 296 94Z" fill="${C.hair}"/>
    <path d="M134 124 C118 96 140 70 168 76 C152 90 154 108 164 122Z" fill="${C.hair}"/>
    <path d="M150 160 C168 148 188 146 204 152" stroke="${C.hairD}" stroke-width="7" fill="none" stroke-linecap="round" opacity=".8"/>
    <path d="M168 200 Q200 184 232 198" stroke="#c8941c" stroke-width="9" fill="none" stroke-linecap="round"/>
    <path d="M288 198 Q320 184 352 200" stroke="#c8941c" stroke-width="9" fill="none" stroke-linecap="round"/>
    <circle cx="200" cy="262" r="56" fill="#ffffff" opacity=".28"/><circle cx="320" cy="262" r="56" fill="#ffffff" opacity=".28"/>
    <circle cx="200" cy="262" r="56" fill="none" stroke="${C.ink}" stroke-width="10"/><circle cx="320" cy="262" r="56" fill="none" stroke="${C.ink}" stroke-width="10"/>
    <path d="M255 256 Q260 244 265 256" stroke="${C.ink}" stroke-width="9" fill="none" stroke-linecap="round"/>
    <path d="M144 252 L100 244 M376 252 L420 244" stroke="${C.ink}" stroke-width="8" stroke-linecap="round"/>
    <path d="M168 232 Q190 218 214 226" stroke="#fff" stroke-width="6" fill="none" stroke-linecap="round" opacity=".7"/>`;

  const eyesSvg = () => `
    <ellipse cx="204" cy="268" rx="13" ry="18" fill="${C.ink}"/><circle cx="209" cy="260" r="5.5" fill="#fff"/>
    <ellipse cx="316" cy="268" rx="13" ry="18" fill="${C.ink}"/><circle cx="321" cy="260" r="5.5" fill="#fff"/>`;
  const mouthClosedSvg = () => `<path d="M214 338 Q260 372 306 338" stroke="${C.ink}" stroke-width="8" fill="none" stroke-linecap="round"/>`;
  const mouthOpenSvg = () => `<path d="M212 332 Q260 346 308 332 Q300 392 260 394 Q220 392 212 332Z" fill="#6e2430"/><path d="M232 372 Q260 358 288 372 Q276 392 260 392 Q244 392 232 372Z" fill="#ff8f8f"/><path d="M222 334 Q260 346 298 334" stroke="#fff" stroke-width="9" fill="none" stroke-linecap="round" opacity=".9"/>`;

  const upperSvg = x => `<rect x="${x - 38}" y="${SH.L[1] - 12}" width="76" height="${L1 + 38}" rx="38" fill="${C.shirt}"/><rect x="${x - 38}" y="${SH.L[1] - 12}" width="76" height="${L1 + 38}" rx="38" fill="none" stroke="${C.shirtD}" stroke-width="5"/>`;
  const foreSvg = x => `<rect x="${x - 33}" y="${SH.L[1] + L1 - 26}" width="66" height="${L2 + 30}" rx="33" fill="${C.shirt}" stroke="${C.shirtD}" stroke-width="5"/><rect x="${x - 36}" y="${SH.L[1] + L1 + L2 - 22}" width="72" height="26" rx="13" fill="${C.apron}" stroke="${C.apronD}" stroke-width="4"/>`;
  const handSvg = (x, side) => `<circle cx="${x}" cy="${SH.L[1] + L1 + L2 + 14}" r="40" fill="${C.skin}" stroke="${C.skinD}" stroke-width="4"/><ellipse cx="${x + (side === 'L' ? 34 : -34)}" cy="${SH.L[1] + L1 + L2 + 4}" rx="15" ry="22" fill="${C.skin}" stroke="${C.skinD}" stroke-width="4" transform="rotate(${side === 'L' ? -25 : 25} ${x + (side === 'L' ? 34 : -34)} ${SH.L[1] + L1 + L2 + 4})"/>`;

  function buildChef(host, o) {
    o = o || {};
    const wrap = document.createElement('div');
    wrap.className = 'chef';
    wrap.style.cssText = 'position:absolute;left:0;top:0;width:' + BOX.w + 'px;height:' + BOX.h + 'px;transform-origin:0 0;transform:translate(' + (o.x || 0) + 'px,' + (o.y || 0) + 'px) scale(' + (o.scale || 1) + ')';
    host.appendChild(wrap);
    const mk = (svg, origin, id) => layer(wrap, { w: BOX.w, h: BOX.h, svg, origin, id });
    const rig = { wrap, S: o.scale || 1, ox: o.x || 0, oy: o.y || 0 };
    rig.body = mk(bodySvg(), [260, 700]);
    rig.head = mk(headSvg(), [260, 390]);
    rig.eyes = layer(rig.head, { w: BOX.w, h: BOX.h, svg: eyesSvg(), origin: [260, 268] });
    rig.mouthClosed = layer(rig.head, { w: BOX.w, h: BOX.h, svg: mouthClosedSvg(), origin: [260, 340] });
    rig.mouthOpen = layer(rig.head, { w: BOX.w, h: BOX.h, svg: mouthOpenSvg(), origin: [260, 335] });
    rig.arms = {};
    rig.armLayerHost = null;
    return rig;
  }

  /* arms are built separately so the scene can put the counter and props between body and arms */
  function buildArms(host, rig) {
    const wrap = document.createElement('div');
    wrap.className = 'chef-arms';
    wrap.style.cssText = rig.wrap.style.cssText;
    host.appendChild(wrap);
    ['L', 'R'].forEach(side => {
      const S = SH[side];
      const up = layer(wrap, { w: BOX.w, h: BOX.h, svg: upperSvg(S[0]), origin: [S[0], S[1]] });
      const fore = layer(up, { w: BOX.w, h: BOX.h, svg: foreSvg(S[0]), origin: [S[0], S[1] + L1] });
      const hand = layer(fore, { w: BOX.w, h: BOX.h, svg: handSvg(S[0], side), origin: [S[0], S[1] + L1 + L2] });
      rig.arms[side] = { up, fore, hand, S };
    });
    return wrap;
  }

  /* two-bone IK in local coords. target = [x,y] local. returns degrees for upper and fore (relative). prev keeps the angles continuous. */
  function ik(side, T, prev) {
    const S = SH[side];
    let dx = T[0] - S[0], dy = T[1] - S[1];
    let d = Math.hypot(dx, dy);
    const dMax = L1 + L2 - 1, dMin = Math.abs(L1 - L2) + 4;
    if (d > dMax) { dx *= dMax / d; dy *= dMax / d; d = dMax; }
    if (d < dMin) { d = dMin; }
    const base = Math.atan2(-dx, dy);                       // angle of S->T where 0 = pointing straight down, clockwise positive
    const A = Math.acos(Math.max(-1, Math.min(1, (L1 * L1 + d * d - L2 * L2) / (2 * L1 * d))));
    const cand = [base + A, base - A].map(a => ({ a, ex: S[0] + L1 * -Math.sin(a) }));
    const out = side === 'L' ? -1 : 1;                      // elbow bends away from the body
    const pick = cand[0].ex * out >= cand[1].ex * out ? cand[0] : cand[1];
    const th1 = pick.a;
    const E = [S[0] + L1 * -Math.sin(th1), S[1] + L1 * Math.cos(th1)];
    const th2 = Math.atan2(-(T[0] - E[0]), T[1] - E[1]);
    let u = th1 * 180 / Math.PI, f = (th2 - th1) * 180 / Math.PI;
    f = ((f + 540) % 360) - 180;
    return { up: u, fore: f };
  }

  function poseArm(rig, side, targetStage) {
    const T = [(targetStage[0] - rig.ox) / rig.S, (targetStage[1] - rig.oy) / rig.S];
    // wrist target is the hand centre, which sits 14 local px beyond the wrist
    const a = ik(side, [T[0], T[1] - 14], null);
    rig.arms[side].up.style.transform = 'rotate(' + a.up.toFixed(2) + 'deg)';
    rig.arms[side].fore.style.transform = 'rotate(' + a.fore.toFixed(2) + 'deg)';
  }

  /* ---------------- props (origin of each svg = its grip point) ---------------- */
  const PROPS = {
    bottle: c => ({ w: 140, h: 360, o: [70, 230], spout: [0, -205], grip: [0, 0], svg: `
      <rect x="20" y="30" width="100" height="270" rx="30" fill="#e8f2ee" stroke="#9fb9b1" stroke-width="5"/>
      <rect x="28" y="130" width="84" height="162" rx="24" fill="${c}"/>
      <rect x="28" y="140" width="22" height="140" rx="10" fill="#fff" opacity=".28"/>
      <rect x="40" y="-0" width="60" height="50" rx="14" fill="#e8f2ee" stroke="#9fb9b1" stroke-width="5"/>
      <rect x="46" y="-40" width="48" height="46" rx="10" fill="#c98f5b" stroke="#a46f3f" stroke-width="5"/>
      <rect x="32" y="190" width="76" height="60" rx="10" fill="#fff6e8" opacity=".92"/>` }),
    jar: c => ({ w: 200, h: 290, o: [100, 150], spout: [-68, -128], grip: [0, 0], svg: `
      <rect x="22" y="22" width="156" height="226" rx="34" fill="#e8f2ee" stroke="#9fb9b1" stroke-width="5"/>
      <rect x="30" y="64" width="140" height="176" rx="28" fill="${c}"/>
      <rect x="40" y="76" width="22" height="130" rx="10" fill="#fff" opacity=".28"/>
      <rect x="14" y="2" width="172" height="32" rx="14" fill="#e8f2ee" stroke="#9fb9b1" stroke-width="5"/>
      <rect x="40" y="130" width="120" height="64" rx="10" fill="#fff6e8" opacity=".92"/>` }),
    cup: c => ({ w: 230, h: 230, o: [95, 115], spout: [-72, -96], grip: [0, 0], svg: `
      <path d="M22 18 H168 L152 208 Q95 224 38 208Z" fill="#fff6e8" stroke="#d6c4a6" stroke-width="5" stroke-linejoin="round"/>
      <path d="M30 56 H160 L150 200 Q95 214 40 200Z" fill="${c}"/>
      <ellipse cx="95" cy="26" rx="73" ry="14" fill="${shade(c, .15)}" stroke="#d6c4a6" stroke-width="5"/>
      <path d="M166 62 Q222 66 214 114 Q206 156 156 152" fill="none" stroke="#d6c4a6" stroke-width="16" stroke-linecap="round"/>` }),
    spoon: c => ({ w: 120, h: 420, o: [60, 250], spout: [0, 130], grip: [0, 0], svg: `
      <rect x="48" y="120" width="24" height="200" rx="12" fill="#c98f5b" stroke="#a46f3f" stroke-width="4"/>
      <ellipse cx="60" cy="350" rx="40" ry="60" fill="#c98f5b" stroke="#a46f3f" stroke-width="4"/>
      <ellipse cx="60" cy="356" rx="28" ry="46" fill="${c}" opacity=".9"/>` }),
    whisk: c => ({ w: 140, h: 400, o: [70, 130], spout: [0, 150], grip: [0, 0], svg: `
      <rect x="56" y="0" width="28" height="170" rx="14" fill="#c98f5b" stroke="#a46f3f" stroke-width="4"/>
      <rect x="48" y="160" width="44" height="18" rx="8" fill="#9aa4ae"/>
      <path d="M70 176 C10 220 12 330 70 372 C128 330 130 220 70 176Z" fill="none" stroke="#9aa4ae" stroke-width="6"/>
      <path d="M70 176 C40 230 42 330 70 372 C98 330 100 230 70 176Z" fill="none" stroke="#9aa4ae" stroke-width="6"/>
      <path d="M70 176 V372" stroke="#9aa4ae" stroke-width="6"/>` })
  };

  /* ---------------- vessels (origin = base centre on the counter; y negative is up) ---------------- */
  const VESSELS = {
    pan: { rim: [0, -64], rx: 178, ry: 44, sx: 150, sy: 32, handle: [-330, -70], mk: () => `
      <path d="M-170 -64 L-146 0 Q0 24 146 0 L170 -64Z" fill="#3a3f47"/>
      <ellipse cx="0" cy="-64" rx="178" ry="44" fill="#4b525c"/>
      <ellipse cx="0" cy="-62" rx="160" ry="36" fill="#23272d"/>
      <path d="M-176 -66 L-340 -84 L-340 -56 L-170 -44Z" fill="#2b2f36"/>
      <rect x="-346" y="-88" width="50" height="34" rx="14" fill="#c98f5b"/>` },
    pot: { rim: [0, -176], rx: 134, ry: 36, sx: 118, sy: 28, handle: [-190, -150], mk: () => `
      <path d="M-134 -176 L-124 -6 Q0 22 124 -6 L134 -176Z" fill="#aeb7c2"/>
      <path d="M-134 -176 L-124 -6 Q-70 8 -40 12 L-48 -176Z" fill="#fff" opacity=".18"/>
      <ellipse cx="0" cy="-176" rx="134" ry="36" fill="#c9d1da"/>
      <ellipse cx="0" cy="-174" rx="120" ry="29" fill="#4b525c"/>
      <rect x="-190" y="-166" width="62" height="26" rx="13" fill="#2b2f36"/><rect x="128" y="-166" width="62" height="26" rx="13" fill="#2b2f36"/>` },
    bowl: { rim: [0, -118], rx: 156, ry: 40, sx: 138, sy: 30, handle: [-170, -112], mk: () => `
      <path d="M-156 -118 Q-150 6 0 8 Q150 6 156 -118Z" fill="#f4ede0" stroke="#cdbf9f" stroke-width="5"/>
      <path d="M-120 -80 Q-110 -8 -60 4 Q-120 -10 -140 -100Z" fill="#fff" opacity=".35"/>
      <rect x="-40" y="2" width="80" height="14" rx="7" fill="#cdbf9f"/>
      <ellipse cx="0" cy="-118" rx="156" ry="40" fill="#fffaf0" stroke="#cdbf9f" stroke-width="5"/>
      <ellipse cx="0" cy="-116" rx="140" ry="32" fill="#e8dcc3"/>
      <path d="M-156 -96 Q0 -64 156 -96" stroke="#5f8fb3" stroke-width="10" fill="none" opacity=".8"/>` },
    plate: { rim: [0, -22], rx: 200, ry: 46, sx: 120, sy: 26, handle: [0, 0], mk: () => `
      <ellipse cx="0" cy="-8" rx="196" ry="42" fill="#cdbf9f"/>
      <ellipse cx="0" cy="-22" rx="200" ry="46" fill="#fffaf0" stroke="#e2d6bd" stroke-width="5"/>
      <ellipse cx="0" cy="-20" rx="140" ry="28" fill="none" stroke="#e2d6bd" stroke-width="5"/>` }
  };

  root.ChefArt = { C, BOX, SH, L1, L2, buildChef, buildArms, poseArm, ik, PROPS, VESSELS };
})(typeof window !== 'undefined' ? window : globalThis);
