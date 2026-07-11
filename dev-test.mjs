import { chromium } from 'playwright-core';

const EXE = '/home/sebastian/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome';
const URL = 'http://localhost:8080/Beatbox%20to%20MIDI.dc.html';

const browser = await chromium.launch({
  executablePath: EXE,
  args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox', '--mute-audio'],
});
const page = await browser.newPage();
const errors = [];
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

await page.goto(URL, { waitUntil: 'load' });

// Wait for React to mount: the master "Record" button text appears.
await page.waitForFunction(() => /Record master|Recording master/.test(document.body.innerText), { timeout: 8000 });

const title = await page.title();

// Zoom pill: fixed, bottom-right.
const zoom = await page.evaluate(() => {
  const btns = [...document.querySelectorAll('button')].filter(b => b.title === 'Zoom in' || b.title === 'Zoom out');
  if (!btns.length) return null;
  let el = btns[0]; while (el && getComputedStyle(el).position !== 'fixed') el = el.parentElement;
  if (!el) return { fixed: false };
  const r = el.getBoundingClientRect();
  return { fixed: true, rightGap: Math.round(window.innerWidth - r.right), bottomGap: Math.round(window.innerHeight - r.bottom) };
});

// Find the React component instance via fiber, then drive the loop.
const loop = await page.evaluate(async () => {
  function findInst() {
    for (const el of document.querySelectorAll('*')) {
      const k = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
      if (!k) continue;
      let f = el[k];
      while (f) { const sn = f.stateNode; const lg = sn && sn.logic; if (lg && typeof lg.onPlay !== 'undefined' && lg.state && 'lanes' in lg.state) return lg; f = f.return; }
    }
    return null;
  }
  const inst = findInst();
  if (!inst) return { ok: false, why: 'no instance' };
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const setState = patch => new Promise(res => inst.setState(patch, res));

  // Known groove: one drum lane, one beat at 0, a 2-beat loop.
  const laneId = 'L1';
  await setState({ lanes: [{ id: laneId, type: 'drum', sound: 'kick', muted: false, solo: false, eq: { low: 0, mid: 0, high: 0 } }],
    events: [{ id: 'e0', laneId, beat: 0, vel: 0.8 }], evCount: 1,
    bpm: 90, quantize: false, loopOn: true, loopStart: 0, loopEnd: 2, startAt: 0, audio: {} });

  // Spy on _playLane to record what the scheduler fires.
  const calls = [];
  const orig = inst._playLane.bind(inst);
  inst._playLane = (l, when, ...rest) => { calls.push({ lane: l.id, when }); return orig(l, when, ...rest); };

  inst.onPlay();                 // starts the loop; fire(true) runs after ensureAC resolves
  await wait(400);
  const afterStart = calls.length;   // expect 1 (the single beat at 0)

  // Mid-loop edit: add a second beat at 1. With the fix, the next loop pass schedules BOTH.
  await setState(s => ({ events: s.events.concat([{ id: 'e1', laneId, beat: 1, vel: 0.8 }]), evCount: 2 }));
  calls.length = 0;
  await wait(1700);              // one loop period (~1333ms) + margin
  const perPassBeats = new Set(calls.map(c => Math.round((c.when % (2 * 60 / 90)) * 1000)));
  const scheduledAfterEdit = calls.length;

  inst.onStop && inst.onStop();

  // Instrument-swap must keep the beats. Switch the kick lane to a synth wave.
  const beatsBefore = inst.state.events.length;
  inst._setSound(laneId)({ target: { value: 'bass' } });   // 'bass' is a synth wave
  await wait(60);
  const lane = inst.state.lanes.find(l => l.id === laneId);
  const swap = { beatsBefore, beatsAfter: inst.state.events.length, newSound: lane && lane.sound, newType: lane && lane.type };

  return { ok: true, afterStart, scheduledAfterEdit, distinctSlots: perPassBeats.size, swap };
});

console.log('title          :', title);
console.log('zoom pill      :', JSON.stringify(zoom));
console.log('loop test      :', JSON.stringify(loop));
console.log('console errors :', errors.length ? errors.slice(0, 6) : 'none');

const pass = title.includes('v0.4.2')
  && zoom && zoom.fixed && zoom.rightGap >= 0 && zoom.rightGap < 60 && zoom.bottomGap >= 0 && zoom.bottomGap < 60
  && loop.ok && loop.afterStart >= 1 && loop.scheduledAfterEdit >= 2 && loop.distinctSlots >= 2
  && loop.swap && loop.swap.beatsAfter === loop.swap.beatsBefore && loop.swap.beatsBefore === 2
  && loop.swap.newSound === 'bass' && loop.swap.newType === 'synth';
console.log('\nRESULT:', pass ? 'PASS ✅' : 'FAIL ❌');
await browser.close();
process.exit(pass ? 0 : 1);
