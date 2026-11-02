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
 * Being a polite guest. This now runs every ten minutes off an external
 * scheduler, so the traffic it puts on a free community API matters. Three
 * things keep it light, measured on the wire on 2 Nov 2026:
 *
 *   - The scores payload is 62KB gzipped and is the only thing that must be
 *     fresh, because that is what changes every few minutes.
 *   - The kingdom feed is 381KB and only carries active player counts, which
 *     move on a scale of days. So it is fetched a few times a day and the
 *     committed meta.json is used in between. Where it is fetched, it goes out
 *     with If-Modified-Since, and an unchanged feed answers 304 for 0.3KB.
 *   - If the scores have not moved since the published page was built, this
 *     stops right there and nothing else is requested or rebuilt.
 *
 * That is about 10MB a day during prep week and close to nothing between
 * seasons, down from roughly 73MB a day before.
 *
 *   node pull.mjs            defaults to kingdom 826, zone 588-1086
 *   HOME_KID=826 LO=588 HI=1086 node pull.mjs
 *   PAGE_URL=... the published page, read to see if there is anything new
 *   META_MAX_AGE_H=6 how stale the cached active player counts may get
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
const PAGE_URL = process.env.PAGE_URL || '';
const META_MAX_AGE_H = Number(process.env.META_MAX_AGE_H || 6);

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

/* Is there anything new to publish at all?
   The published page prints the source's own snapshot time and build.py takes it
   straight from updated_at, so the two are directly comparable. If they match,
   the last build already captured this data and there is nothing to do, so stop
   before touching the 381KB kingdom feed or spending a Pages deploy. This used
   to be a separate gate job that fetched the scores all over again; doing it
   here costs nothing because the data is already in hand. */
const srcStamp = String(bulk.updated_at || '').slice(0, 16);   // YYYY-MM-DDTHH:MM
if (PAGE_URL && srcStamp) {
  let live = null;
  try {
    const r = await fetch(`${PAGE_URL}${PAGE_URL.includes('?') ? '&' : '?'}k=${Date.now()}`,
                          { headers: HEAD, signal: AbortSignal.timeout(20000) });
    if (r.ok) {
      const m = (await r.text()).match(/pulled\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+UTC/);
      if (m) live = `${m[1]}T${m[2]}`;
    }
  } catch (e) { /* unreachable page is not a reason to stand down */ }
  if (live === srcStamp) skip(`nothing new, the published page already shows ${live}`);
  if (live) console.log(`source moved to ${srcStamp}, page has ${live}`);
}

/* ---------------------------------------------------------------- kingdoms */
/* The 381KB kingdom feed only carries active player counts, roster size and
   age. Those move on a scale of days, so there is no reason to pull it every
   ten minutes. It is refreshed when the committed snapshot is older than
   META_MAX_AGE_H, and even then it goes out with If-Modified-Since so an
   unchanged feed answers 304 for 0.3KB instead of 381KB. */
const cached = JSON.parse(readFileSync(new URL('./meta.json', import.meta.url), 'utf8'));
const cacheAgeH = cached._fetched
  ? (Date.now() - Date.parse(cached._fetched)) / 3.6e6 : Infinity;
const wantFeed = cacheAgeH > META_MAX_AGE_H;

let list = [], feedState = 'cached';
if (!wantFeed) {
  console.log(`active player counts are ${cacheAgeH.toFixed(1)}h old, reusing the snapshot`);
} else {
  const hdr = { ...HEAD };
  if (cached._lastmod) hdr['if-modified-since'] = cached._lastmod;
  let res = null;
  for (let i = 0; i < 3 && !res; i++) {
    try {
      res = await fetch(`${MP}/api/kingdoms`, { headers: hdr, signal: AbortSignal.timeout(ATTEMPT_MS) });
    } catch (e) {
      LAST_ERR = e.name === 'TimeoutError' ? `no answer in ${ATTEMPT_MS / 1000}s` : String(e.message || e);
      if (i < 2) await sleep(2000 * (i + 1));
    }
  }
  if (res && res.status === 304) {
    feedState = 'unchanged';
    console.log('kingdom feed unchanged since last time (304), reusing the snapshot');
  } else if (res && res.ok) {
    try {
      const feed = await res.json();
      list = feed.kingdoms || feed.results || (Array.isArray(feed) ? feed : []);
      cached._lastmod = res.headers.get('last-modified') || cached._lastmod || '';
      feedState = 'refreshed';
    } catch (e) { console.log('kingdom feed did not parse, reusing the snapshot'); }
  } else {
    console.log(`kingdom feed refused us (${res ? 'HTTP ' + res.status : LAST_ERR}), reusing the snapshot`);
  }
}
const meta = {};
/* `act` is the denominator for the points-per-player view and it is deliberately
   active_players, not active_7d.
   Measured across the 498 kingdoms in the zone on 2 Nov 2026, active_7d has a
   correlation with day score of -0.002. That is not a weak signal, it is none,
   so dividing by it manufactured differences that were not there: kingdom 919
   came out as the third hardest working kingdom in the zone purely because
   mightpulse credited them 141 active players. active_players correlates at
   0.65 and has the tightest spread of every candidate, so it is the honest one.
   active_7d is still carried for reference, it is just not divided by. */
for (const k of list) {
  const kid = k.kid ?? k.id;
  if (!kid) continue;
  meta[kid] = { act: k.active_players || 0, a7: k.active_7d || 0,
                players: k.player_count || 0,
                age: Math.round(k.age_days || 0), tg8: 0 };
}
const fresh = Object.keys(meta).length;

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
              act: mt.act || 0, a7: mt.a7 || 0, tg8: mt.tg8 || 0,
              players: mt.players, age: mt.age, days: s.days });
}
rows.sort((a, b) => a.kid - b.kid);

/* Opponents can sit outside the zone we compare against. They still have to
   appear in the versus bar and be pinned on the charts, so they are handed over
   as `extra`, which the builder keeps out of the distribution and the boards.
   This used to carry only the home kingdom's opponent. Now that any kingdom in
   the zone can be selected on the page, every one of them needs its own
   opponent available: 94 of the 499 are drawn against someone outside. */
const oppId = mine.opp;          // the home kingdom's opponent, named on the payload
const inZone = new Set(rows.map(r => r.kid));
const extra = [];
const seen = new Set();
let missing = 0;
for (const r of rows) {
  const other = r.opp;
  if (!other || inZone.has(other) || seen.has(other)) continue;
  seen.add(other);
  const s = rec[other];
  if (!s) { missing++; continue; }
  const mt = meta[other] || cached[other];
  const [home, away] = s.days[day - 1] || [0, 0];
  extra.push({ kid: other, opp: s.opp, s: home, o: away,
               act: mt ? (mt.act || 0) : 0, a7: mt ? (mt.a7 || 0) : 0, tg8: 0,
               players: mt ? mt.players : 0, age: mt ? mt.age : 0, days: s.days });
}
console.log(`${extra.length} opponents sit outside the zone and are carried separately`
            + (missing ? `, ${missing} had no readable record` : ''));

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

/* Keep the snapshot warm, and stamp it so the next run knows how old it is.
   Opponents outside the zone are kept too, otherwise a selected kingdom drawn
   against one of them would lose its per-player figure on a cached run. */
if (feedState === 'refreshed' && fresh > 1000) {
  const keep = { _fetched: new Date().toISOString(), _lastmod: cached._lastmod || '' };
  for (let kid = LO; kid <= HI; kid++) if (meta[kid]) keep[kid] = meta[kid];
  for (const r of extra) if (meta[r.kid]) keep[r.kid] = meta[r.kid];
  writeFileSync(new URL('./meta.json', import.meta.url), JSON.stringify(keep, null, 0));
  console.log(`snapshot refreshed, ${Object.keys(keep).length - 2} kingdoms`);
} else if (feedState === 'unchanged') {
  // the feed had nothing new, so just move the clock on and avoid re-asking soon
  cached._fetched = new Date().toISOString();
  writeFileSync(new URL('./meta.json', import.meta.url), JSON.stringify(cached, null, 0));
}

const me = rows.find(r => r.kid === HOME);
console.log(`${rows.filter(r => !r.act).length} of ${rows.length} have no active player count`);
console.log(`season ${bulk.season} day ${day}: ${rows.length} of ${zoneSize} kingdoms scoring`);
console.log(`${HOME} ${me.s.toLocaleString()} vs ${me.opp} ${me.o.toLocaleString()}`);
