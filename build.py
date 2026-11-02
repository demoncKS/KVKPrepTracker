#!/usr/bin/env python3
"""Build the prep week zone tracker from data.json. Re-run daily after a fresh pull."""
import json, os, datetime, html

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.environ.get('DATA', os.path.join(HERE, 'data.json'))))
ROWS, HOME, AWAY = D['rows'], D['home'], D['away']
# DAY can be pinned to re-create how the page looked at the end of an earlier day
DAY = int(os.environ.get('DAY', D['day']))
LIVE = DAY == D['day']          # a pinned earlier day is finished, not running
LO, HI = D['zone']
ROMAN = ['I', 'II', 'III', 'IV', 'V']

# the opponent can sit outside the zone we compare against, in which case it is
# still pinned on the charts but never counted in the distribution or the boards
by = {r['kid']: r for r in ROWS}
by.update({r['kid']: r for r in D.get('extra', [])})
me, them = by[HOME], by[AWAY]
AWAY_IN_ZONE = AWAY in {r['kid'] for r in ROWS}

def q(a, p):
    s = sorted(a)
    return s[max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))]

def pctile(a, v):
    return sum(1 for x in a if x < v) / len(a) * 100

for r in list(by.values()):
    r['s'], r['o'] = r['days'][DAY - 1]
ROWS = [r for r in ROWS if r['s'] > 0]
by = {r['kid']: r for r in ROWS}
by.update({r['kid']: r for r in D.get('extra', [])})
me, them = by[HOME], by[AWAY]

scores = [r['s'] for r in ROWS]
per = [r['s'] / r['act'] for r in ROWS if r['act']]
me_per = me['s'] / me['act']
them_per = them['s'] / them['act'] if them.get('act') else 0

# margin between the two sides of every distinct pairing we can see
seen, gaps = set(), []
for r in ROWS:
    k = tuple(sorted((r['kid'], r['opp'])))
    if k in seen or min(r['s'], r['o']) <= 0:
        continue
    seen.add(k)
    gaps.append(max(r['s'], r['o']) / min(r['s'], r['o']))
    if gaps[-1] >= max(gaps):
        worst = (r['kid'], r['opp']) if r['s'] > r['o'] else (r['opp'], r['kid'])
our_gap = max(me['s'], me['o']) / min(me['s'], me['o'])
# the gap is a size, not a direction, so who is actually in front is separate
AHEAD = me['s'] >= me['o']

def ordn(v):
    i = int(round(v))
    suf = 'th' if 10 <= i % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(i % 10, 'th')
    return f'{i}{suf}'

def m(v):  return f'{v/1e6:,.1f}M'
def k(v):  return f'{v/1e3:,.0f}k'
def n(v):  return f'{v:,.0f}'

SCALES = {}

def hist(vals, width, lo=0.0):
    """Equal-width bins spanning the data, returned as (lo, hi, count)."""
    top = max(vals)
    nb = int(top // width) + 1
    counts = [0] * nb
    for v in vals:
        counts[min(nb - 1, int(v // width))] += 1
    return [(i * width, (i + 1) * width, c) for i, c in enumerate(counts)]

def dist_svg(vals, width, mark_us, mark_them, fmt, unit, cid):
    """Bars and axis are the same for every kingdom; only the two pins move,
    so they carry ids and the browser repositions them on selection."""
    """Histogram with the two kingdoms pinned on the same scale."""
    bins = hist(vals, width)
    W, H = 980, 300
    padL, padR, padT, padB = 46, 18, 54, 46
    pw, ph = W - padL - padR, H - padT - padB
    top = bins[-1][1]
    mx = max(c for _, _, c in bins) or 1
    x = lambda v: padL + pw * v / top
    bw = pw / len(bins)
    out = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
           f'aria-label="Distribution of {unit} across {len(vals)} kingdoms">']
    # recessive gridlines at each count step
    for i in range(1, 5):
        gy = padT + ph - ph * i / 4
        out.append(f'<line x1="{padL}" y1="{gy:.1f}" x2="{W-padR}" y2="{gy:.1f}" class="grid"/>')
        out.append(f'<text x="{padL-8}" y="{gy+4:.1f}" class="axl" text-anchor="end">{round(mx*i/4)}</text>')
    for lo_, hi_, c in bins:
        if not c:
            continue
        bh = ph * c / mx
        bx, byy = x(lo_) + 1, padT + ph - bh
        out.append(
            f'<rect x="{bx:.1f}" y="{byy:.1f}" width="{max(1,bw-2):.1f}" height="{bh:.1f}" '
            f'rx="3" class="bar"><title>{c} kingdom{"s" if c!=1 else ""} between '
            f'{fmt(lo_)} and {fmt(hi_)}</title></rect>')
    # pins. A wider zone pushes the scale out and brings the two markers close
    # together, so when they are within a label's width of each other the left
    # one is lifted and turned to read leftward, away from its neighbour.
    pins = [(mark_them, 'them', f'K{AWAY}'), (mark_us, 'us', f'K{HOME}')]
    close = abs(x(mark_them) - x(mark_us)) < 200
    left_val = min(mark_them, mark_us)
    for val, cls, label in pins:
        px = x(val)
        is_left = close and val == left_val
        lift = 20 if is_left else 0
        out.append(f'<line id="{cid}Pin{cls}" x1="{px:.1f}" y1="{padT-14-lift}" '
                   f'x2="{px:.1f}" y2="{padT+ph}" class="pin {cls}"/>')
        if is_left and px > 150:
            anchor, dx = 'end', -7
        else:
            anchor = 'end' if px > W - 150 else 'start'
            dx = -7 if anchor == 'end' else 7
        out.append(f'<text id="{cid}Lab{cls}" x="{px+dx:.1f}" y="{padT-20-lift}" '
                   f'class="pinlab {cls}" text-anchor="{anchor}">{label}  {fmt(val)}</text>')
    # value axis
    for i in range(6):
        v = top * i / 5
        ta = 'start' if i == 0 else ('end' if i == 5 else 'middle')
        out.append(f'<text x="{x(v):.1f}" y="{H-padB+22}" class="axl" text-anchor="{ta}">{fmt(v)}</text>')
    out.append(f'<line x1="{padL}" y1="{padT+ph}" x2="{W-padR}" y2="{padT+ph}" class="axis"/>')
    out.append(f'<text x="{padL}" y="{H-8}" class="axt">{unit}</text>')
    out.append('</svg>')
    SCALES[cid] = {'padL': padL, 'pw': pw, 'top': top, 'padT': padT, 'ph': ph, 'W': W}
    return '\n'.join(out)

def scale_row(vals, fmt, mark, label, cid):
    """p10 to p90 spread with our position marked."""
    pts = [(.1, 'p10'), (.25, 'lower quartile'), (.5, 'median'), (.75, 'upper quartile'), (.9, 'p90')]
    lo_, hi_ = q(vals, .1), q(vals, .9)
    span = (hi_ - lo_) or 1
    pos = lambda v: max(0, min(100, (v - lo_) / span * 100))
    cells = ''.join(
        f'<div class="qc"><span class="ql">{nm}</span><span class="qv">{fmt(q(vals,p))}</span></div>'
        for p, nm in pts)
    SCALES['q' + cid] = {'lo': lo_, 'span': span}
    return (f'<div class="qrow">{cells}</div>'
            f'<div class="qtrack"><span class="qfill"></span>'
            f'<i id="q{cid}" class="qpin" style="left:{pos(mark):.1f}%"><b>{label}</b></i></div>')

# ---------------------------------------------------------------- targets
# "what score would we need to be X" — raw score first, because that is the number
# people actually see in game. The per active player figure rides along as context.
def target(name, need):
    return (name, f'{k(need/me["act"])} from each of {n(me["act"])} active players',
            need, need / me['s'] - 1)

srt = sorted(scores, reverse=True)
targets = [
    target('Reach the middle of the zone', q(scores, .5)),
    target('Reach the top quarter of the zone', q(scores, .75)),
    target('Reach the top ten in the zone', srt[9]),
    target(f'Hold our lead over kingdom {AWAY}' if AHEAD
           else f'Match kingdom {AWAY} today', them['s']),
]

rank_per = sorted(ROWS, key=lambda r: -(r['s'] / r['act'] if r['act'] else 0))
pos_per = [r['kid'] for r in rank_per].index(HOME) + 1
rank_abs = sorted(ROWS, key=lambda r: -r['s'])
pos_abs = [r['kid'] for r in rank_abs].index(HOME) + 1

DASH = '—'

# ---------------------------------------------------------------- view table
# Everything on the page that changes when you pick a different kingdom, for
# every kingdom in the cohort. The page is still rendered server side for the
# home kingdom, so it works with no JavaScript at all; this table is what lets
# the browser re-render it for anyone else.
per_by_kid = {r['kid']: (r['s'] / r['act'] if r['act'] else 0) for r in ROWS}
order_abs = [r['kid'] for r in sorted(ROWS, key=lambda r: -r['s'])]
order_per = [r['kid'] for r in sorted(ROWS, key=lambda r: -per_by_kid[r['kid']])]
pos_of_abs = {kid: i + 1 for i, kid in enumerate(order_abs)}
pos_of_per = {kid: i + 1 for i, kid in enumerate(order_per)}
IN_ZONE = {r['kid'] for r in ROWS}

VIEWS = {}
for r in ROWS:
    kid = r['kid']
    opp = by.get(r['opp'])
    if not opp or not opp.get('s'):
        # a kingdom with no pairing this season. It still belongs in the
        # distribution, it just has no head to head to show.
        # 'a7' is the key the browser reads; it now holds the active player count
        VIEWS[kid] = {'kid': kid, 'bye': 1, 's': r['s'], 'a7': r['act'],
                      'per': per_by_kid[kid], 'pa': pos_of_abs[kid], 'pp': pos_of_per[kid],
                      'ca': pctile(scores, r['s']), 'cp': pctile(per, per_by_kid[kid]),
                      'days': r['days']}
        continue
    oper = opp['s'] / opp['act'] if opp.get('act') else 0
    gap = max(r['s'], opp['s']) / min(r['s'], opp['s']) if min(r['s'], opp['s']) else 1
    VIEWS[kid] = {
        'kid': kid, 'opp': r['opp'], 'bye': 0,
        's': r['s'], 'o': opp['s'], 'a7': r['act'],
        'per': per_by_kid[kid], 'oper': oper,
        'pa': pos_of_abs[kid], 'pp': pos_of_per[kid],
        'ca': pctile(scores, r['s']), 'cp': pctile(per, per_by_kid[kid]),
        'oca': pctile(scores, opp['s']), 'ocp': pctile(per, oper),
        'opa': pos_of_abs.get(r['opp']), 'oiz': 1 if r['opp'] in IN_ZONE else 0,
        'gap': gap, 'gpc': pctile(gaps, gap), 'ahead': 1 if r['s'] >= opp['s'] else 0,
        'days': r['days'],
    }


def board(rows_, title, note, badges=False, start=1):
    ME_CLS = ' class="me"'
    cells = []
    for p, r in enumerate(rows_, start):
        if badges and p <= 3:
            art = ('rank_gold', 'rank_silver', 'rank_bronze')[p - 1]
            pos = f'<span class="badge"><img src="{A[art]}" alt=""><b>{p}</b></span>'
        else:
            pos = f'<span class="pn">{p}</span>'
        cells.append(
            f'<tr data-kid="{r["kid"]}"{ME_CLS if r["kid"]==HOME else ""}>'
            f'<td class="pos">{pos}</td>'
            f'<td class="kd">K{r["kid"]}</td><td class="num">{m(r["s"])}</td>'
            f'<td class="num">{n(r["act"])}</td>'
            f'<td class="num">{k(r["s"]/r["act"]) if r["act"] else DASH}</td>'
            f'<td class="num vs">{m(r["o"])}</td><td class="kd dim">K{r["opp"]}</td></tr>')
    return (f'<div class="board"><h3>{title}</h3><p class="note">{note}</p>'
            f'<div class="tw"><table><thead><tr><th></th><th>Kingdom</th>'
            f'<th class="num">Day {ROMAN[DAY-1]}</th>'
            f'<th class="num">Active</th><th class="num">Per active</th>'
            f'<th class="num">Opponent</th><th></th></tr></thead>'
            f'<tbody>{"".join(cells)}</tbody></table></div></div>')

A = json.load(open(os.path.join(HERE, 'artpack.json')))['assets']

# day I to V, named for what each one actually scores
DAYS = [('Construction', 'day1_construction'), ('Research', 'day2_research'),
        ('Pets', 'day3_pets'), ('Troops', 'day4_troops'), ('Everything', 'day5_all')]

day_cells = ''
for i in range(5):
    dh, da = me['days'][i]
    name, art = DAYS[i]
    if i + 1 < DAY or (i + 1 == DAY and dh):
        state = 'live' if (i + 1 == DAY and LIVE) else 'done'
        mid = (f'<span class="dnum us">{m(dh)}</span>'
               f'<span class="dbar"><i style="width:{dh/(dh+da)*100 if dh+da else 50:.1f}%"></i></span>'
               f'<span class="dnum them">{m(da)}</span>')
    else:
        state = 'soon'
        mid = '<span class="dsoon">no scores published yet</span>'
    day_cells += (
        f'<div class="day {state}">'
        f'<img class="med" src="{A[art]}" alt="">'
        f'<span class="dlab"><b>{ROMAN[i]}</b>{name}</span>{mid}'
        f'<span class="dst">{ {"done":"Ended","live":"In progress","soon":"Locked"}[state] }</span></div>')

# the site's own snapshot time, not ours, so a stale pull is visible on the page
built = (D.get('updated') or '')[:16].replace('T', ' ') + ' UTC' if D.get('updated') \
    else datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

SOURCE = D.get('source', 'mightpulse.com')

RULE = f'<img class="rule" src="{A["divider"]}" alt="">'
CORNERS = ''.join(f'<img class="cnr c{i}" src="{A["corner"]}" alt="">' for i in range(4))


# only worth saying when they are the ones setting the pace
PACE_NOTE = '' if AHEAD else (
    '<p class="note" style="margin-top:14px">The last row is on the list for '
    'completeness, not as a goal. Only %d of %d kingdoms in the zone are scoring at '
    "%d's rate per player.</p>"
    % (sum(1 for v in per if v >= them_per), len(per), AWAY))


def head(icon, title):
    return f'<h2><img class="hicon" src="{A[icon]}" alt="">{title}</h2>'


# the <title> names the page in a gallery, so snapshots get their own
PAGE_TITLE = os.environ.get('TITLE', 'KvK Prep Week Tracker')

HTML = f'''<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{PAGE_TITLE}</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fredoka:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Lilita+One&display=swap">
<style>
:root{{
  --bg:#0B0E15; --surf:#171E2B; --surf2:#1E2636; --inset:#10151F;
  --edge:#2B3550; --edge2:#3E4B69;
  --ink:#EDF0F7; --muted:#939DB4; --dim:#66718A;
  --us:#5AA9F5; --them:#F07A52; --field:#3E4A63; --good:#63D08A;
  --gold:#DDB883; --gold-hi:#F6E8B8; --gold-mid:#CD9B59; --gold-lo:#977128;
  --disp:"Lilita One","Trebuchet MS",system-ui,sans-serif;
  --ui:"Fredoka",system-ui,-apple-system,Segoe UI,sans-serif;
  --body:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
*{{box-sizing:border-box}}
body{{background:var(--bg) url({A['texture']}) repeat;background-size:420px;
  color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.55;
  margin:0;padding:0 20px 70px}}
.wrap{{max-width:1040px;margin:0 auto}}
img{{max-width:100%}}

/* ---------------------------------------------------------------- masthead */
header{{padding:26px 0 6px}}
.eyebrow{{font-family:var(--ui);font-size:.74rem;font-weight:600;letter-spacing:.16em;
  text-transform:uppercase;color:var(--gold);margin:0 0 6px;text-align:center}}
.mast{{position:relative;max-width:760px;margin:0 auto}}
.mast img{{display:block;width:100%}}
h1{{position:absolute;inset:17% 12% auto;margin:0;text-align:center;
  font-family:var(--disp);font-weight:400;font-size:clamp(1.5rem,4.6vw,2.6rem);
  letter-spacing:.01em;color:var(--gold-hi);
  text-shadow:0 2px 0 #16307A,0 -2px 0 #16307A,2px 0 0 #16307A,-2px 0 0 #16307A,0 6px 12px rgba(0,0,0,.45)}}
.lede{{color:var(--muted);max-width:62ch;margin:14px auto 0;text-align:center}}
.stamp{{font-family:var(--mono);font-size:.73rem;color:var(--dim);margin:10px 0 0;text-align:center}}

/* ------------------------------------------------------------------ versus */
.versus{{position:relative;background:var(--surf);border:1px solid var(--edge2);
  border-radius:16px;padding:26px 30px 22px;margin:26px 0 0}}
.cnr{{position:absolute;width:66px;height:auto;opacity:.72;pointer-events:none}}
.c0{{top:6px;left:6px}} .c1{{top:6px;right:6px;transform:scaleX(-1)}}
.c2{{bottom:6px;left:6px;transform:scaleY(-1)}} .c3{{bottom:6px;right:6px;transform:scale(-1)}}
.vhead{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:18px}}
.side{{display:flex;align-items:center;gap:14px}}
.side.r{{flex-direction:row-reverse}}
.crest{{position:relative;flex:0 0 auto;width:88px}}
.crest img{{display:block;width:100%}}
.crest b{{position:absolute;inset:26% 0 auto;text-align:center;font-family:var(--ui);
  font-weight:600;font-size:1.02rem;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.55)}}
.sc{{display:flex;flex-direction:column;gap:1px;min-width:0}}
.side.r .sc{{align-items:flex-end}}
.sc span{{font-family:var(--ui);font-size:.72rem;font-weight:500;letter-spacing:.1em;
  text-transform:uppercase;color:var(--dim)}}
.sc b{{font-family:var(--mono);font-size:clamp(1.05rem,2.6vw,1.75rem);font-weight:600;
  font-variant-numeric:tabular-nums;line-height:1.15}}
.side.us .sc b{{color:var(--us)}} .side.them .sc b{{color:var(--them)}}
.vsimg{{width:104px;height:auto;flex:0 0 auto}}
.vbar{{position:relative;height:13px;border-radius:8px;background:var(--them);
  overflow:hidden;margin-top:18px;border:1px solid var(--edge2)}}
.vbar i{{position:absolute;inset:0 auto 0 0;background:var(--us);display:block}}

.days{{display:grid;gap:8px;margin-top:18px}}
.day{{display:grid;grid-template-columns:44px 118px auto 1fr auto 88px;align-items:center;
  gap:12px;padding:8px 14px 8px 8px;border-radius:11px;background:var(--inset);
  border:1px solid var(--edge)}}
.day.soon{{opacity:.5}}
.day.soon .med{{filter:grayscale(.7)}}
.day.live{{border-color:var(--gold-mid);box-shadow:inset 0 0 0 1px rgba(221,184,131,.18)}}
.med{{width:44px;height:44px;display:block}}
.dlab{{font-family:var(--ui);font-size:.84rem;font-weight:500;color:var(--muted);
  display:flex;align-items:baseline;gap:7px}}
.dlab b{{font-family:var(--disp);font-weight:400;font-size:.95rem;color:var(--gold);
  min-width:22px}}
.dnum{{font-family:var(--mono);font-size:.86rem;font-variant-numeric:tabular-nums}}
.dnum.us{{color:var(--us)}} .dnum.them{{color:var(--them);text-align:right}}
.dbar{{position:relative;height:8px;border-radius:5px;background:var(--them);overflow:hidden}}
.dbar i{{position:absolute;inset:0 auto 0 0;background:var(--us);display:block}}
.dsoon{{grid-column:3/6;font-family:var(--ui);font-size:.8rem;color:var(--dim)}}
.dst{{font-family:var(--ui);font-size:.74rem;color:var(--dim);text-align:right}}

/* ------------------------------------------------------------------ picker */
.picker{{display:flex;align-items:center;justify-content:center;gap:10px;
  flex-wrap:wrap;margin:18px auto 0;max-width:62ch}}
.picker label{{font-family:var(--ui);font-size:.74rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim)}}
.picker input{{font-family:var(--mono);font-size:1rem;font-variant-numeric:tabular-nums;
  width:11ch;padding:8px 12px;border-radius:10px;border:1px solid var(--edge2);
  background:var(--inset);color:var(--ink)}}
.picker input:focus{{outline:2px solid var(--us);outline-offset:2px;border-color:var(--us)}}
.phint{{font-family:var(--ui);font-size:.8rem;color:var(--dim);min-height:1.2em}}
.phint.warn{{color:var(--them)}}
.byline{{margin-top:10px;font-size:.92rem;color:var(--muted)}}

/* ---------------------------------------------------------------- sections */
section{{padding:8px 0 26px}}
.rule{{display:block;width:100%;max-width:620px;margin:6px auto 22px;opacity:.9}}
h2{{font-family:var(--ui);font-size:1.22rem;font-weight:600;margin:0 0 5px;
  display:flex;align-items:center;gap:10px}}
.hicon{{width:26px;height:26px;flex:0 0 auto}}
h3{{font-family:var(--ui);font-size:1rem;font-weight:600;margin:0 0 2px}}
p{{margin:0 0 10px}}
.note{{color:var(--muted);font-size:.88rem;margin:0 0 14px;max-width:76ch}}

.chart{{width:100%;height:auto;display:block;margin:6px 0 2px}}
.bar{{fill:var(--field)}}
.grid{{stroke:#212B40;stroke-width:1}}
.axis{{stroke:var(--edge2);stroke-width:1}}
.axl{{fill:var(--dim);font-family:var(--mono);font-size:11px}}
.axt{{fill:var(--dim);font-family:var(--body);font-size:11.5px}}
.pin{{stroke-width:2}}
.pin.us{{stroke:var(--us)}} .pin.them{{stroke:var(--them)}}
.pinlab{{font-family:var(--ui);font-size:12.5px;font-weight:600}}
.pinlab.us{{fill:var(--us)}} .pinlab.them{{fill:var(--them)}}

.qrow{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:18px}}
.qc{{display:flex;flex-direction:column;gap:1px}}
.ql{{font-family:var(--ui);font-size:.7rem;font-weight:500;color:var(--dim);
  text-transform:uppercase;letter-spacing:.07em}}
.qv{{font-family:var(--mono);font-size:1.02rem;font-variant-numeric:tabular-nums}}
.qtrack{{position:relative;height:7px;border-radius:4px;background:var(--inset);
  border:1px solid var(--edge);margin:14px 0 30px}}
.qfill{{position:absolute;inset:0;border-radius:4px;
  background:linear-gradient(90deg,#232C40,#4A5875)}}
.qpin{{position:absolute;top:-7px;width:2px;height:21px;background:var(--us)}}
.qpin b{{position:absolute;top:-20px;left:50%;transform:translateX(-50%);white-space:nowrap;
  font-family:var(--ui);font-size:.74rem;font-weight:600;color:var(--us)}}

.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-top:18px}}
.tile{{background:var(--surf);border:1px solid var(--edge);border-radius:12px;padding:15px 16px}}
.tile.hi{{border-color:var(--gold-lo)}}
.tile .lab{{font-family:var(--ui);font-size:.72rem;font-weight:500;text-transform:uppercase;
  letter-spacing:.08em;color:var(--dim)}}
.tile .big{{font-family:var(--mono);font-size:1.62rem;font-weight:600;
  font-variant-numeric:tabular-nums;margin-top:3px}}
.tile .sub{{font-size:.85rem;color:var(--muted);margin-top:3px}}

table{{width:100%;border-collapse:collapse;font-size:.88rem}}
.tw{{overflow-x:auto}}
th{{text-align:left;font-family:var(--ui);font-weight:600;font-size:.72rem;
  text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
  padding:0 10px 7px;border-bottom:1px solid var(--edge);white-space:nowrap}}
td{{padding:6px 10px;border-bottom:1px solid #1C2536;white-space:nowrap}}
.num{{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}}
.kd{{font-family:var(--ui);font-weight:600}}
td.dim,.vs{{color:var(--dim)}}
tr.me td{{background:#16243A}}
tr.me .kd{{color:var(--us)}}
.board{{margin-top:26px}}
.pos{{width:52px;text-align:center;padding:2px 6px}}
.badge{{position:relative;display:inline-block;width:40px;vertical-align:middle}}
.badge img{{display:block;width:100%;filter:drop-shadow(0 0 1px rgba(255,255,255,.25))}}
.badge b{{position:absolute;inset:20% 0 auto;text-align:center;font-family:var(--ui);
  font-weight:700;font-size:.82rem;color:#26200F}}
.pn{{font-family:var(--mono);font-size:.8rem;color:var(--dim)}}

.targets{{display:grid;gap:10px;margin-top:16px}}
.tgt{{display:grid;grid-template-columns:1fr auto auto;gap:16px;align-items:center;
  padding:13px 16px;background:var(--surf);border:1px solid var(--edge);border-radius:11px}}
.tgt .what b{{display:block;font-family:var(--ui);font-weight:600}}
.tgt .what span{{font-size:.83rem;color:var(--dim)}}
.tgt .need{{font-family:var(--mono);font-size:1.15rem;font-variant-numeric:tabular-nums}}
.tgt .delta{{font-family:var(--mono);font-size:.9rem;color:var(--them);min-width:74px;text-align:right}}
.tgt .delta.met{{color:var(--good)}}

footer{{padding-top:26px;color:var(--dim);font-size:.8rem}}
.disc{{display:flex;gap:20px;align-items:flex-end;
  background:var(--surf);border:1px solid var(--edge);border-radius:14px;
  padding:18px 22px 0;margin-bottom:20px}}
.disc img{{width:120px;flex:0 0 auto;align-self:flex-end;margin-bottom:-1px}}
.disc div{{padding-bottom:18px}}
.disc p{{color:var(--muted);font-size:.92rem;max-width:66ch;margin:0}}
.disc h3{{color:var(--gold);margin-bottom:6px}}
.src{{max-width:80ch}}
@media (max-width:760px){{
  .qrow{{grid-template-columns:repeat(2,1fr)}}
  .tgt{{grid-template-columns:1fr;gap:6px}}
  .tgt .delta{{text-align:left}}
  .day{{grid-template-columns:32px 1fr auto;row-gap:6px}}
  .day .dbar{{display:none}}
  .dst{{display:none}}
  .vhead{{gap:8px}} .crest{{width:62px}} .vsimg{{width:66px}}
  .disc{{flex-direction:column;align-items:center}} .disc img{{width:96px;order:2}}
  .disc div{{order:1;padding-bottom:0}}
}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important;animation:none!important}}}}
</style>

<div class="wrap">
<header>
  <p class="eyebrow">Season {D['season']} &middot; Kingdoms {LO} to {HI}</p>
  <div class="mast"><img src="{A['banner']}" alt=""><h1>KvK Prep Week Tracker</h1></div>
  <p class="lede">Prep week is five days long and while we all track our performance against
  our opponent, it&rsquo;s sometimes nice to know how your kingdom fits in among the ones around us.</p>
  <p class="lede">A score on its own tells you nothing, so this page puts your kingdom&rsquo;s score
  next to other kingdoms around us and shows whether it is a good day or a quiet one.
  {'The data refreshes periodically throughout the day.' if LIVE else 'This is a snapshot of day ' + ROMAN[DAY-1] + ', taken after it closed.'}</p>
  <p class="lede">We source our data from {SOURCE}, a brilliant resource. The analytics on this
  page are built and run by Kingdom {HOME}.</p>
  <div class="picker">
    <label for="kidInput">Your kingdom</label>
    <input id="kidInput" type="search" inputmode="numeric" autocomplete="off"
           list="kidList" placeholder="type a number, e.g. {HOME}" value="{HOME}">
    <datalist id="kidList"></datalist>
    <span class="phint" id="kidHint"></span>
  </div>
  <p class="stamp">Day {ROMAN[DAY-1]} of V &middot; {'scores as at' if LIVE else 'final scores, captured'} {built} &middot; source {SOURCE}</p>

  <div class="versus">
    {CORNERS}
    <div class="vhead">
      <div class="side us">
        <div class="crest"><img src="{A['crest_us']}" alt=""><b id="vUsKid">{HOME}</b></div>
        <div class="sc"><span>You</span><b id="vUsScore">{n(me['s'])}</b></div>
      </div>
      <img class="vsimg" src="{A['vs_emblem']}" alt="versus">
      <div class="side them r">
        <div class="crest"><img src="{A['crest_them']}" alt=""><b id="vThemKid">{AWAY}</b></div>
        <div class="sc"><span>Them</span><b id="vThemScore">{n(them['s'])}</b></div>
      </div>
    </div>
    <div class="vbar" id="vBarWrap"><i id="vBar" style="width:{me['s']/(me['s']+them['s'])*100:.2f}%"></i></div>
    <div class="days" id="vDays">{day_cells}</div>
  </div>
</header>

<section>
  {RULE}
  {head('icon_target', 'Day ' + ROMAN[DAY-1] + ' across the zone')}
  <p class="note">Each bar counts kingdoms whose day {ROMAN[DAY-1]} score fell in that range.
  Hover a bar for the count.</p>
  {dist_svg(scores, 50e6, me['s'], them['s'], m, 'Day '+ROMAN[DAY-1]+' points', 'abs')}
  {scale_row(scores, m, me['s'], 'K'+str(HOME), 'abs')}

  <div class="grid2">
    <div class="tile"><div class="lab">Zone median</div>
      <div class="big">{m(q(scores,.5))}</div><div class="sub">the middle of {len(ROWS)} kingdoms</div></div>
    <div class="tile hi"><div class="lab" id="aYouLab">Kingdom {HOME}</div>
      <div class="big" id="aYouBig" style="color:var(--us)">{m(me['s'])}</div>
      <div class="sub" id="aYouSub">{ordn(pctile(scores,me['s']))} percentile, {pos_abs} of {len(ROWS)}</div></div>
    <div class="tile" id="aOppTile"><div class="lab" id="aOppLab">Kingdom {AWAY}</div>
      <div class="big" id="aOppBig" style="color:var(--them)">{m(them['s'])}</div>
      <div class="sub" id="aOppSub">{ordn(pctile(scores,them['s']))} percentile{f", {[r['kid'] for r in rank_abs].index(AWAY)+1} of {len(ROWS)}" if AWAY_IN_ZONE else ", outside the zone"}</div></div>
    <div class="tile"><div class="lab">Highest in zone</div>
      <div class="big">{m(max(scores))}</div>
      <div class="sub">K{max(ROWS,key=lambda r:r['s'])['kid']}</div></div>
  </div>
</section>

<section>
  {RULE}
  {head('icon_coins', 'Adjusted for size')}
  <p class="note">Points divided by the kingdom&rsquo;s active player count. Big kingdoms score more simply by
  having more people, so this is the measure that shows how hard a kingdom is actually working.</p>
  {dist_svg(per, 100e3, me_per, them_per, k, 'Points per active player', 'per')}
  {scale_row(per, k, me_per, 'K'+str(HOME), 'per')}

  <div class="grid2">
    <div class="tile"><div class="lab">Zone median</div>
      <div class="big">{k(q(per,.5))}</div><div class="sub">points per active player</div></div>
    <div class="tile hi"><div class="lab" id="pYouLab">Kingdom {HOME}</div>
      <div class="big" id="pYouBig" style="color:var(--us)">{k(me_per)}</div>
      <div class="sub" id="pYouSub">{ordn(pctile(per,me_per))} percentile, {pos_per} of {len(ROWS)}</div></div>
    <div class="tile" id="pOppTile"><div class="lab" id="pOppLab">Kingdom {AWAY}</div>
      <div class="big" id="pOppBig" style="color:var(--them)">{k(them_per)}</div>
      <div class="sub" id="pOppSub">{ordn(pctile(per,them_per))} percentile</div></div>
    <div class="tile"><div class="lab">Best in zone</div>
      <div class="big">{k(max(per))}</div>
      <div class="sub">K{max((r for r in ROWS if r['act']),key=lambda r:r['s']/r['act'])['kid']}</div></div>
  </div>
</section>

<section>
  {RULE}
  {head('icon_scroll', 'What score would it take?')}
  <p class="note" id="tgtNote">Kingdom {HOME} scored {m(me['s'])} today. This is what it would have
  taken to finish somewhere higher, and how much more that is.</p>
  <div class="targets" id="tgtList">
    {''.join(f"""<div class="tgt"><div class="what"><b>{t[0]}</b><span>{t[1]}</span></div>
      <div class="need">{m(t[2])}</div>
      <div class="delta{' met' if t[3]<=0 else ''}">{'on pace' if t[3]<=0 else f'+{t[3]*100:.0f}%'}</div></div>"""
      for t in targets)}
  </div>
  <div id="paceNote">{PACE_NOTE}</div>
</section>

<section>
  {RULE}
  {head('icon_scales', 'Is it a fair matchup?')}
  <p class="note">In almost every matchup one kingdom is ahead of the other. This takes the size
  of that lead and compares it against all {len(gaps)} matchups in the zone.
  Read 2x as "twice as many points as the other side".</p>
  <div class="grid2">
    <div class="tile"><div class="lab">A normal matchup</div><div class="big">{q(gaps,.5):.1f}x</div>
      <div class="sub">half the matchups in the zone are closer than this, half are wider</div></div>
    <div class="tile hi" id="gapTile"><div class="lab">This one</div>
      <div class="big" id="gapBig" style="color:var(--{'us' if AHEAD else 'them'})">{our_gap:.1f}x</div>
      <div class="sub" id="gapSub">{f'K{HOME} is {our_gap:.1f} times ahead of K{AWAY} today' if AHEAD
        else f'K{AWAY} is {our_gap:.1f} times ahead of K{HOME} today'}, a wider gap than
      {pctile(gaps,our_gap):.0f} out of every 100 matchups</div></div>
    <div class="tile"><div class="lab">A rough draw</div><div class="big">{q(gaps,.75):.1f}x</div>
      <div class="sub">only a quarter of matchups are wider than this</div></div>
    <div class="tile"><div class="lab">The worst one out there</div><div class="big">{max(gaps):.1f}x</div>
      <div class="sub">K{worst[0]} against K{worst[1]}, the most one sided in the zone</div></div>
  </div>
</section>

<section>
  {RULE}
  {board(rank_abs[:10], 'Top ten in the zone', 'The pace-setters for day '+ROMAN[DAY-1]+'.', True)}
  {board(rank_abs[-5:], 'Bottom five', 'For the full range of what a day can look like.', False,
         len(ROWS)-4)}
</section>

<footer>
  <div class="disc">
    <img src="{A['herald']}" alt="">
    <div>
      <h3>Worth remembering</h3>
      <p>A quiet day is not a bad kingdom. This is one day of five, and places move around a
      lot as the later days open.</p>
      <p class="byline">Brought to you by Kingdom {HOME}. Questions, or thinking about a
      transfer? Feel free to speak to Meshaal or demonc.</p>
    </div>
  </div>
  <p class="src">Kingdoms {LO} to {HI}, {len(ROWS)} with published scores. Day scores from
  {SOURCE}, active player counts from mightpulse.com, both pulled {built}. Checked for new scores several times an hour.</p>
</footer>
'''

# ---------------------------------------------------------------- the script
# Built after the template so SCALES is populated: dist_svg and scale_row record
# their value-to-pixel mapping as they render, and the browser needs those to
# move the pins without re-deriving the geometry.
JS_SRC = r'''
<script>
(function () {
  "use strict";
  const B = __BOOT__;
  const V = B.views, S = B.scales, C = B.consts;
  const $ = id => document.getElementById(id);

  // the same formatters build.py uses, so a rendered kingdom reads identically
  // to the one baked into the page
  const m  = v => (v / 1e6).toLocaleString('en-AU', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + 'M';
  const kf = v => Math.round(v / 1e3).toLocaleString('en-AU') + 'k';
  const nf = v => Math.round(v).toLocaleString('en-AU');
  const ord = v => {
    const i = Math.round(v);
    const suf = (i % 100 >= 10 && i % 100 <= 20) ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[i % 10] || 'th');
    return i + suf + ' percentile';
  };

  /* ---------------------------------------------------------------- pins */
  // mirrors dist_svg: x = padL + pw * value / top, then the same nudge when the
  // two labels would otherwise collide
  function pins(cid, us, them, fmt, labUs, labThem) {
    const sc = S[cid]; if (!sc) return;
    const x = v => sc.padL + sc.pw * v / sc.top;
    const close = Math.abs(x(them) - x(us)) < 200;
    const leftVal = Math.min(them, us);
    [[them, 'them', labThem], [us, 'us', labUs]].forEach(([val, cls, label]) => {
      const line = $(cid + 'Pin' + cls), text = $(cid + 'Lab' + cls);
      if (!line || !text) return;
      const show = val > 0;
      line.style.display = show ? '' : 'none';
      text.style.display = show ? '' : 'none';
      if (!show) return;
      const px = x(val);
      const isLeft = close && val === leftVal;
      const lift = isLeft ? 20 : 0;
      line.setAttribute('x1', px.toFixed(1));
      line.setAttribute('x2', px.toFixed(1));
      line.setAttribute('y1', sc.padT - 14 - lift);
      let anchor, dx;
      if (isLeft && px > 150) { anchor = 'end'; dx = -7; }
      else { anchor = px > sc.W - 150 ? 'end' : 'start'; dx = anchor === 'end' ? -7 : 7; }
      text.setAttribute('x', (px + dx).toFixed(1));
      text.setAttribute('y', sc.padT - 20 - lift);
      text.setAttribute('text-anchor', anchor);
      text.textContent = label + '  ' + fmt(val);
    });
  }

  function qpin(cid, val, label) {
    const sc = S['q' + cid], el = $('q' + cid);
    if (!sc || !el) return;
    const pos = Math.max(0, Math.min(100, (val - sc.lo) / sc.span * 100));
    el.style.left = pos.toFixed(1) + '%';
    el.querySelector('b').textContent = label;
  }

  /* ---------------------------------------------------------------- days */
  function dayCells(days, bye) {
    let out = '';
    for (let i = 0; i < 5; i++) {
      const d = days[i] || [0, 0], dh = d[0], da = bye ? 0 : d[1];
      const played = (i + 1 < C.day) || (i + 1 === C.day && dh);
      const state = played ? ((i + 1 === C.day && C.live) ? 'live' : 'done') : 'soon';
      let mid;
      if (played) {
        const w = (dh + da) ? dh / (dh + da) * 100 : 50;
        mid = '<span class="dnum us">' + m(dh) + '</span>'
            + '<span class="dbar"><i style="width:' + w.toFixed(1) + '%"></i></span>'
            + '<span class="dnum them">' + (bye ? '&mdash;' : m(da)) + '</span>';
      } else {
        mid = '<span class="dsoon">no scores published yet</span>';
      }
      out += '<div class="day ' + state + '">'
           + '<img class="med" src="' + C.dayart[i] + '" alt="">'
           + '<span class="dlab"><b>' + C.roman[i] + '</b>' + C.daynames[i] + '</span>' + mid
           + '<span class="dst">' + ({done: 'Ended', live: 'In progress', soon: 'Locked'})[state]
           + '</span></div>';
    }
    return out;
  }

  /* ------------------------------------------------------------- targets */
  function targets(v) {
    const rows = [
      ['Reach the middle of the zone', C.median],
      ['Reach the top quarter of the zone', C.p75],
      ['Reach the top ten in the zone', C.tenth],
    ];
    if (!v.bye) {
      rows.push([v.ahead ? 'Hold the lead over kingdom ' + v.opp
                         : 'Match kingdom ' + v.opp + ' today', v.o]);
    }
    return rows.map(([name, need]) => {
      const delta = need / v.s - 1;
      const sub = v.a7 ? kf(need / v.a7) + ' from each of ' + nf(v.a7) + ' active players'
                       : 'no active player count published';
      return '<div class="tgt"><div class="what"><b>' + name + '</b><span>' + sub + '</span></div>'
           + '<div class="need">' + m(need) + '</div>'
           + '<div class="delta' + (delta <= 0 ? ' met' : '') + '">'
           + (delta <= 0 ? 'on pace' : '+' + Math.round(delta * 100) + '%') + '</div></div>';
    }).join('');
  }

  /* -------------------------------------------------------------- render */
  function render(kid) {
    const v = V[kid];
    if (!v) return false;
    const K = 'K' + kid, O = v.bye ? null : 'K' + v.opp;

    $('vUsKid').textContent = kid;
    $('vUsScore').textContent = nf(v.s);
    $('vThemKid').textContent = v.bye ? '—' : v.opp;
    $('vThemScore').textContent = v.bye ? '—' : nf(v.o);
    $('vBar').style.width = v.bye ? '100%' : (v.s / (v.s + v.o) * 100).toFixed(2) + '%';
    $('vBarWrap').style.opacity = v.bye ? '.45' : '';
    $('vDays').innerHTML = dayCells(v.days, v.bye);

    pins('abs', v.s, v.bye ? 0 : v.o, m, K, O);
    qpin('abs', v.s, K);
    $('aYouLab').textContent = 'Kingdom ' + kid;
    $('aYouBig').textContent = m(v.s);
    $('aYouSub').textContent = ord(v.ca) + ', ' + v.pa + ' of ' + C.n;
    $('aOppTile').style.display = v.bye ? 'none' : '';
    if (!v.bye) {
      $('aOppLab').textContent = 'Kingdom ' + v.opp;
      $('aOppBig').textContent = m(v.o);
      $('aOppSub').textContent = ord(v.oca) + (v.oiz ? ', ' + v.opa + ' of ' + C.n : ', outside the zone');
    }

    pins('per', v.per, v.bye ? 0 : v.oper, kf, K, O);
    qpin('per', v.per, K);
    $('pYouLab').textContent = 'Kingdom ' + kid;
    $('pYouBig').textContent = kf(v.per);
    $('pYouSub').textContent = ord(v.cp) + ', ' + v.pp + ' of ' + C.n;
    $('pOppTile').style.display = v.bye ? 'none' : '';
    if (!v.bye) {
      $('pOppLab').textContent = 'Kingdom ' + v.opp;
      $('pOppBig').textContent = kf(v.oper);
      $('pOppSub').textContent = ord(v.ocp);
    }

    $('tgtNote').textContent = 'Kingdom ' + kid + ' scored ' + m(v.s)
      + ' today. This is what it would have taken to finish somewhere higher, and how much more that is.';
    $('tgtList').innerHTML = targets(v);
    // the pace note only makes sense against an opponent who is setting the pace
    $('paceNote').innerHTML = (!v.bye && !v.ahead)
      ? '<p class="note" style="margin-top:14px">The last row is on the list for completeness, '
        + 'not as a goal. Only ' + C.perAbove(v.oper) + ' of ' + C.n
        + ' kingdoms in the zone are scoring at ' + v.opp + "'s rate per player.</p>"
      : '';

    const gt = $('gapTile');
    gt.style.display = v.bye ? 'none' : '';
    if (!v.bye) {
      $('gapBig').textContent = v.gap.toFixed(1) + 'x';
      $('gapBig').style.color = 'var(--' + (v.ahead ? 'us' : 'them') + ')';
      $('gapSub').textContent = (v.ahead ? K + ' is ' + v.gap.toFixed(1) + ' times ahead of ' + O
                                         : O + ' is ' + v.gap.toFixed(1) + ' times ahead of ' + K)
        + ' today, a wider gap than ' + Math.round(v.gpc) + ' out of every 100 matchups';
    }

    document.querySelectorAll('tr[data-kid]').forEach(tr => {
      tr.classList.toggle('me', +tr.dataset.kid === kid);
    });

    $('kidHint').textContent = v.bye
      ? 'Kingdom ' + kid + ' has no matchup this season, so only the zone comparison is shown.'
      : '';
    $('kidHint').className = 'phint' + (v.bye ? ' warn' : '');
    document.title = 'K' + kid + ' · ' + C.title;
    return true;
  }

  // how many kingdoms are scoring at or above a given per-player rate
  C.perAbove = rate => { let c = 0; for (const p of C.perList) if (p >= rate) c++; return c; };

  /* ---------------------------------------------------------------- wire */
  const input = $('kidInput'), hint = $('kidHint');
  const kids = Object.keys(V).map(Number).sort((a, b) => a - b);
  $('kidList').innerHTML = kids.map(k => '<option value="' + k + '">').join('');

  function choose(raw, push) {
    const kid = parseInt(String(raw).replace(/\D/g, ''), 10);
    if (!kid) return;
    if (!V[kid]) {
      hint.textContent = 'Kingdom ' + kid + ' is not in the ' + C.lo + ' to ' + C.hi + ' zone this page covers.';
      hint.className = 'phint warn';
      return;
    }
    if (!render(kid)) return;
    try { localStorage.setItem('kvkKid', kid); } catch (e) {}
    if (push) {
      const u = new URL(location.href);
      u.searchParams.set('kid', kid);
      history.replaceState(null, '', u);
    }
  }

  input.addEventListener('change', () => choose(input.value, true));
  input.addEventListener('input', () => { if (/^\d{3,4}$/.test(input.value.trim())) choose(input.value, true); });

  let start = new URLSearchParams(location.search).get('kid');
  if (!start) { try { start = localStorage.getItem('kvkKid'); } catch (e) {} }
  if (start && V[+start] && +start !== C.home) { input.value = +start; choose(start, false); }
})();
</script>
'''

BOOT = {
    'views': VIEWS,
    'scales': SCALES,
    'consts': {
        'home': HOME, 'lo': LO, 'hi': HI, 'n': len(ROWS), 'day': DAY, 'live': LIVE,
        'roman': ROMAN, 'daynames': [d[0] for d in DAYS], 'dayart': [A[d[1]] for d in DAYS],
        'median': q(scores, .5), 'p75': q(scores, .75), 'tenth': srt[9],
        'perList': sorted(per, reverse=True), 'title': PAGE_TITLE,
    },
}

def _round(o):
    if isinstance(o, float):
        return round(o, 4)
    if isinstance(o, dict):
        return {kk: _round(vv) for kk, vv in o.items()}
    if isinstance(o, list):
        return [_round(x) for x in o]
    return o

HTML += JS_SRC.replace('__BOOT__', json.dumps(_round(BOOT), separators=(',', ':')))
HTML += '\n</div>\n'

out = os.environ.get('OUT', os.path.join(HERE, 'index.html'))
open(out, 'w').write(HTML)
print('wrote', out, len(HTML), 'chars')
print(f"{HOME} {m(me['s'])} p{pctile(scores,me['s']):.0f} | per {k(me_per)} "
      f"p{pctile(per,me_per):.0f} | gap {our_gap:.2f}x")
