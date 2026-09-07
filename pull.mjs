/* Pull one hour's worth of prep week data and write data.json.
 *
 * Two sources, two hosts:
 *   kvk.kingshotsimulator.com/api/kvk/scores/{kid}   the daily KvK scores
 *   mightpulse.com/api/kingdoms/{kid}                active players and troop grades
 *
 * Neither sends CORS headers, so this cannot run in a browser on another
 * origin. It has to run server side, which is what the workflow does.
 *
 * Active player counts barely move week to week, so if mightpulse refuses the
 * runner we fall back to the committed meta.json rather than dropping the
 * per-active-player view. Scores have no fallback: no scores, no build.
 *
 *   node pull.mjs            defaults to kingdom 826, zone 750-900
 *   HOME=826 LO=750 HI=900 node pull.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';

const SCORES = 'https://kvk.kingshotsimulator.com';
const MP = 'https://mightpulse.com';
const HOME = Number(process.env.HOME_KID || 826);
const LO = Number(process.env.LO || 750);
const HI = Number(process.env.HI || 900);
const CONC = 6;

// a plain script fetch gets turned away by some front ends, so look ordinary
const HEAD = {
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
                '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
  accept: 'application/json,text/plain,*/*',
  'accept-language': 'en-AU,en;q=0.9',
  referer: MP + '/',
};

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* 4xx means that kingdom has no record, so give up on it quietly. 5xx and
   network errors are the host struggling, so back off and try again. */
async function getJson(url, tries = 5) {
  let wait = 1200;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: HEAD });
      if (r.ok) return await r.json();
      if (r.status >= 400 && r.status < 500) return null;
    } catch { /* network, retry */ }
    await sleep(wait + Math.random() * 800);
    wait = Math.min(wait * 1.8, 12000);
  }
  return null;
}

async function pool(items, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: CONC }, async () => {
    while (i < items.length) await fn(items[i++]);
  }));
}

const zone = Array.from({ length: HI - LO + 1 }, (_, i) => LO + i);

const scores = {};
await pool(zone, async kid => {
  const d = await getJson(`${SCORES}/api/kvk/scores/${kid}`);
  if (d && d.days) scores[kid] = d;
});
const ids = Object.keys(scores).map(Number);
console.log(`scores: ${ids.length} of ${zone.length} kingdoms have a KvK record`);

if (!scores[HOME]) {
  console.error(`kingdom ${HOME} has no scores, refusing to build a page without us on it`);
  process.exit(1);
}

const cached = JSON.parse(readFileSync(new URL('./meta.json', import.meta.url), 'utf8'));
const meta = {};
let fresh = 0;
await pool(ids, async kid => {
  const k = await getJson(`${MP}/api/kingdoms/${kid}`, 3);
  if (!k) return;
  const tg = Object.fromEntries((k.pyramid?.tg || []).map(t => [t.label, t.count]));
  meta[kid] = { a7: k.active_7d, players: k.player_count,
                age: Math.round(k.age_days || 0), tg8: tg.TG8 || 0 };
  fresh++;
});
const stale = ids.filter(k => !meta[k] && cached[k]).length;
for (const kid of ids) if (!meta[kid] && cached[kid]) meta[kid] = cached[kid];
console.log(`meta: ${fresh} fresh, ${stale} from the cached snapshot`);

const any = scores[HOME];
const day = any.current_day;
const rows = [];
for (const kid of ids) {
  const s = scores[kid], mt = meta[kid];
  if (!mt) continue;                       // no active count, cannot place it fairly
  const days = s.days.map(x => [x.home_score, x.away_score]);
  const [home, away] = days[day - 1];
  // a zero on the live day means that kingdom has not reported yet, and
  // counting it as a real zero drags the median down
  if (!home) continue;
  rows.push({ kid, opp: s.opponent, s: home, o: away,
              a7: mt.a7, tg8: mt.tg8, players: mt.players, age: mt.age, days });
}
rows.sort((a, b) => a.kid - b.kid);

if (rows.length < 100) {
  console.error(`only ${rows.length} kingdoms have a live score, refusing to publish a thin page`);
  process.exit(1);
}

writeFileSync(new URL('./data.json', import.meta.url), JSON.stringify({
  season: any.season, day, home: HOME, away: any.opponent,
  updated: any.updated_at, zone: [LO, HI], rows,
}));

// keep the snapshot warm for the next run that gets turned away
if (fresh > ids.length * 0.9) {
  writeFileSync(new URL('./meta.json', import.meta.url), JSON.stringify(meta, null, 0));
}

const me = rows.find(r => r.kid === HOME);
console.log(`season ${any.season} day ${day}: ${rows.length} kingdoms with a live score`);
console.log(`${HOME} ${me.s.toLocaleString()} vs ${me.opp} ${me.o.toLocaleString()}`);
