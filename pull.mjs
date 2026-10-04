/* Pull one hour's worth of prep week data and write data.json.
 *
 * Two bulk endpoints, two requests, whatever the size of the zone:
 *   /api/kvk/scores    every KvK pair in the game, with the per-day scores
 *   /api/kingdoms      every kingdom, with active players, roster size and age
 *
 * The old version fetched one kingdom at a time, which was about 300 requests
 * an hour for a 151 kingdom zone and would have been a thousand for a 499
 * kingdom one. These two calls replace all of it, so widening the zone now
 * costs nothing. Neither host sends CORS headers, so this still has to run
 * server side, which is what the workflow does.
 *
 * Active player counts barely move week to week, so if the kingdom feed refuses
 * the runner we fall back to the committed meta.json rather than dropping the
 * per-active-player view. Scores have no fallback: no scores, no build.
 *
 *   node pull.mjs            defaults to kingdom 826, zone 588-1086
 *   HOME_KID=826 LO=588 HI=1086 node pull.mjs
 */
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';

const MP = 'https://mightpulse.com';
/* Scores used to come only from kvk.kingshotsimulator.com. Mightpulse now
   proxies the same payload, so try it first: it is the host we already depend
   on for the kingdom feed, and it stayed up through the September outage that
   took the other one off the air for over a day. */
const SCORE_HOSTS = [MP, 'https://kvk.kingshotsimulator.com'];
let SCORES = SCORE_HOSTS[0];
const HOME = Number(process.env.HOME_KID || 826);
const LO = Number(process.env.LO || 588);
const HI = Number(process.env.HI || 1086);

// a plain script fetch gets turned away by some front ends, so look ordinary
const HEAD = {
  'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
                '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
  accept: 'application/json,text/plain,*/*',
  'accept-language': 'en-AU,en;q=0.9',
  referer: MP + '/',
};

let LAST_ERR = '';
const ATTEMPT_MS = 25000;        // the bulk payloads are megabytes, give them room
const sleep = ms => new Promise(r => setTimeout(r, ms));

function skip(why) {
  console.log('SKIPPING: ' + why);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, 'skip=1\n');
  process.exit(0);
}

/* Retries are for a host warming up or buckling, not for a 404. A refusal, a
   rate limit and a timeout all look identical in the log otherwise, which cost
   us a day of guessing once, so each one is recorded. */
async function getJson(url, tries = 4) {
  let wait = 2000;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: HEAD, signal: AbortSignal.timeout(ATTEMPT_MS) });
      if (r.ok) return await r.json();
      LAST_ERR = `HTTP ${r.status}`;
      if (r.status >= 400 && r.status < 500 && r.status !== 429) return null;
    } catch (e) {
      LAST_ERR = e.name === 'TimeoutError' ? `no answer in ${ATTEMPT_MS / 1000}s` : String(e.message || e);
    }
    if (i < tries - 1) { await sleep(wait + Math.random() * 1000); wait = Math.min(wait * 1.8, 20000); }
  }
  return null;
}

/* ---------------------------------------------------------------- scores */
let bulk = null;
for (const host of SCORE_HOSTS) {
  bulk = await getJson(`${host}/api/kvk/scores`);
  if (bulk && Array.isArray(bulk.pairs) && bulk.pairs.length) { SCORES = host; break; }
  console.log(`${host} gave us nothing usable: ${LAST_ERR}`);
  bulk = null;
}
if (!bulk) skip(`no score source is answering (last: ${LAST_ERR})`);

/* Flatten the pair list into one record per kingdom. Each pair carries both
   sides, so which column is "us" depends on which half of kids we are. */
const rec = {};
for (const p of bulk.pairs) {
  const ds = p.days || [];
  const [a, b] = p.kids;
  rec[a] = { opp: b, days: ds.map(d => [d.home_score || 0, d.away_score || 0]) };
  rec[b] = { opp: a, days: ds.map(d => [d.away_score || 0, d.home_score || 0]) };
}
const mine = rec[HOME];
if (!mine) skip(`kingdom ${HOME} has no score record in this season yet`);

const day = bulk.current_day;
if (!day || !mine.days[day - 1]) skip(`no day ${day} scores published yet`);

/* ---------------------------------------------------------------- kingdoms */
const cached = JSON.parse(readFileSync(new URL('./meta.json', import.meta.url), 'utf8'));
const meta = {};
const feed = await getJson(`${MP}/api/kingdoms`, 3);
const list = feed ? (feed.kingdoms || feed.results || (Array.isArray(feed) ? feed : [])) : [];
for (const k of list) {
  const kid = k.kid ?? k.id;
  if (!kid) continue;
  meta[kid] = { a7: k.active_7d || 0, players: k.player_count || 0,
                age: Math.round(k.age_days || 0), tg8: 0 };
}
const fresh = Object.keys(meta).length;
if (!fresh) console.log(`kingdom feed refused us (${LAST_ERR}), falling back to the snapshot`);

/* ---------------------------------------------------------------- rows */
const rows = [];
for (let kid = LO; kid <= HI; kid++) {
  const s = rec[kid];
  if (!s) continue;
  const mt = meta[kid] || cached[kid];
  if (!mt) continue;                       // no active count, cannot place it fairly
  const [home, away] = s.days[day - 1] || [0, 0];
  // a zero on the live day means that kingdom has not reported yet, and
  // counting it as a real zero drags the median down
  if (!home) continue;
  rows.push({ kid, opp: s.opp, s: home, o: away,
              a7: mt.a7, tg8: mt.tg8 || 0, players: mt.players, age: mt.age, days: s.days });
}
rows.sort((a, b) => a.kid - b.kid);

/* The opponent can sit outside the zone we compare against. It still has to
   appear in the versus bar and be pinned on the charts, so it is handed over
   as `extra`, which the builder keeps out of the distribution and the boards. */
const extra = [];
const oppId = mine.opp;
if (oppId && !rows.some(r => r.kid === oppId)) {
  const s = rec[oppId];
  const mt = meta[oppId] || cached[oppId];
  if (s) {
    const [home, away] = s.days[day - 1] || [0, 0];
    extra.push({ kid: oppId, opp: s.opp, s: home, o: away,
                 a7: mt ? mt.a7 : 0, tg8: 0, players: mt ? mt.players : 0,
                 age: mt ? mt.age : 0, days: s.days });
    console.log(`opponent ${oppId} sits outside the zone, carried separately`
                + (mt ? '' : ' (no active player count available)'));
  } else {
    console.log(`opponent ${oppId} sits outside the zone and has no record we can read`);
  }
}

// early in a new day, or between prep weeks, too few kingdoms have reported for
// a percentile to mean anything. Scaled to the zone so widening it is safe.
const zoneSize = HI - LO + 1;
const floor = Math.max(80, Math.round(zoneSize * 0.4));
if (rows.length < floor) {
  skip(`only ${rows.length} of ${zoneSize} kingdoms have a live score so far, need ${floor}`);
}
if (!rows.some(r => r.kid === HOME)) skip(`kingdom ${HOME} has not reported a day ${day} score yet`);

writeFileSync(new URL('./data.json', import.meta.url), JSON.stringify({
  season: bulk.season, day, home: HOME, away: oppId,
  updated: bulk.updated_at, source: SCORES.replace(/^https:\/\//, ''),
  zone: [LO, HI], rows, extra,
}));

// keep the snapshot warm for the next run that gets turned away
if (fresh > 1000) {
  const keep = {};
  for (let kid = LO; kid <= HI; kid++) if (meta[kid]) keep[kid] = meta[kid];
  if (oppId && meta[oppId]) keep[oppId] = meta[oppId];
  writeFileSync(new URL('./meta.json', import.meta.url), JSON.stringify(keep, null, 0));
}

const me = rows.find(r => r.kid === HOME);
console.log(`season ${bulk.season} day ${day}: ${rows.length} of ${zoneSize} kingdoms scoring`);
console.log(`${HOME} ${me.s.toLocaleString()} vs ${me.opp} ${me.o.toLocaleString()}`);
