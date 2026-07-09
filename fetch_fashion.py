# -*- coding: utf-8 -*-
"""
The Pulse — aggregates fashion trends from 5 markets.
Runs on GitHub Actions, outputs a static HTML page.
"""

import html
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import feedparser
import requests

UTC = timezone.utc
TIMEOUT = 20
MAX_PER_SECTION = 16
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 ThePulse/1.0")

# ---------------------------------------------------------------- sources

SECTIONS = [
    {
        "id": "vietnam",
        "category": "fashion",
        "title": "Vietnam",
        "subtitle": "Local brands & street style",
        "feeds": [
            ("Elle Vietnam", "https://elle.vn/feed"),
            ("Harper's Bazaar VN", "https://harpersbazaar.vn/feed"),
            ("GNews VN Fashion", "https://news.google.com/rss/search?q=th%E1%BB%9Di+trang+Vi%E1%BB%87t+Nam+local+brand+2026&hl=vi&gl=VN&ceid=VN:vi"),
            ("GNews VN Streetwear", "https://news.google.com/rss/search?q=streetwear+vietnam+xu+h%C6%B0%E1%BB%9Bng&hl=vi&gl=VN&ceid=VN:vi"),
        ],
    },
    {
        "id": "singapore",
        "category": "fashion",
        "title": "Singapore",
        "subtitle": "Southeast Asian fashion hub",
        "feeds": [
            ("Vogue Singapore", "https://vogue.sg/feed"),
            ("Harper's Bazaar SG", "https://www.harpersbazaar.com.sg/feed"),
            ("Elle Singapore", "https://elle.com.sg/feed"),
            ("GNews SG Fashion", "https://news.google.com/rss/search?q=Singapore+fashion+trends+style&hl=en&gl=SG&ceid=SG:en"),
        ],
    },
    {
        "id": "australia",
        "category": "fashion",
        "title": "Australia",
        "subtitle": "Relaxed luxury & resort",
        "feeds": [
            ("Vogue Australia", "https://www.vogue.com.au/feed"),
            ("Harper's Bazaar AU", "https://www.harpersbazaar.com.au/feed"),
            ("RUSSH", "https://www.russh.com/feed/"),
            ("GNews AU Fashion", "https://news.google.com/rss/search?q=Australian+fashion+trends+2026&hl=en&gl=AU&ceid=AU:en"),
        ],
    },
    {
        "id": "usa",
        "category": "fashion",
        "title": "USA",
        "subtitle": "Runway, streetwear & pop culture",
        "feeds": [
            ("Who What Wear", "https://www.whowhatwear.com/rss"),
            ("Vogue US", "https://www.vogue.com/feed/rss"),
            ("Highsnobiety", "https://www.highsnobiety.com/feed/"),
            ("Hypebeast", "https://hypebeast.com/feed"),
            ("GNews US Fashion", "https://news.google.com/rss/search?q=fashion+trends+2026+summer+style&hl=en&gl=US&ceid=US:en"),
        ],
    },
    {
        "id": "korea",
        "title": "Korea",
        "subtitle": "K-fashion, idol style & Seoul street",
        "category": "fashion",
        "feeds": [
            ("Hypebeast KR", "https://hypebeast.kr/feed"),
            ("GNews K-Fashion", "https://news.google.com/rss/search?q=Korean+fashion+K-fashion+Seoul+style+2026&hl=en&gl=US&ceid=US:en"),
            ("GNews Seoul Street", "https://news.google.com/rss/search?q=Seoul+street+style+trends&hl=en&gl=KR&ceid=KR:en"),
        ],
    },
    {
        "id": "tech-ai",
        "title": "Tech & AI",
        "subtitle": "Innovation, AI breakthroughs & the tech industry",
        "category": "tech",
        "feeds": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("Wired", "https://www.wired.com/feed/rss"),
            ("GNews AI", "https://news.google.com/rss/search?q=artificial+intelligence+AI+breakthrough+2026&hl=en&gl=US&ceid=US:en"),
            ("GNews Tech Industry", "https://news.google.com/rss/search?q=tech+industry+jobs+hiring+layoffs+2026&hl=en&gl=US&ceid=US:en"),
        ],
    },
    {
        "id": "travel",
        "title": "Travel",
        "subtitle": "Destinations, experiences & travel blogs",
        "category": "travel",
        "feeds": [
            ("Nomadic Matt", "https://www.nomadicmatt.com/feed/"),
            ("Lonely Planet", "https://www.lonelyplanet.com/feed.xml"),
            ("GNews Travel Blogs", "https://news.google.com/rss/search?q=travel+blog+experience+destination+2026&hl=en&gl=US&ceid=US:en"),
            ("GNews Asia Travel", "https://news.google.com/rss/search?q=travel+Southeast+Asia+Vietnam+Japan+2026&hl=en&gl=US&ceid=US:en"),
            ("GNews Adventure", "https://news.google.com/rss/search?q=best+places+travel+hidden+gem+2026&hl=en&gl=US&ceid=US:en"),
        ],
    },
]

BLOCKED_KEYWORDS = [
    "casino", "gambling", "lottery", "slot machine",
    "crypto trading", "forex signal", "weight loss pill",
]

# ---------------------------------------------------------------- utils

TAG_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
WS_RE = re.compile(r"\s+")


def strip_html(text):
    text = TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    return WS_RE.sub(" ", text).strip()


def truncate(text, limit=200):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def is_blocked(*texts):
    joined = " ".join(t.lower() for t in texts if t)
    return any(kw in joined for kw in BLOCKED_KEYWORDS)


def extract_thumb(entry):
    for key in ("media_thumbnail", "media_content"):
        for item in entry.get(key, []) or []:
            url = item.get("url")
            if url:
                return url
    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href") or enc.get("url")
        if href and any(ext in href.lower() for ext in (".jpg", ".jpeg", ".png", ".webp")):
            return href
    for field in ("summary", "description"):
        raw = entry.get(field) or ""
        m = IMG_RE.search(raw)
        if m:
            return m.group(1)
    return ""


def entry_datetime(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=UTC)
    return None


def fetch_feed(source, url):
    try:
        resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        if resp.status_code != 200:
            return source, url, [], False, f"HTTP {resp.status_code}"
        parsed = feedparser.parse(resp.content)
        if not parsed.entries:
            return source, url, [], False, "empty feed"
        return source, url, parsed.entries, True, f"{len(parsed.entries)} items"
    except requests.exceptions.Timeout:
        return source, url, [], False, "timeout"
    except Exception as exc:
        return source, url, [], False, type(exc).__name__


# ---------------------------------------------------------------- hotness

STOPWORDS = set("the a an and or but in on at to for of is it this that with from by as are was were be been have has had do does did will would shall should can could may might must".split())
NGRAM_RE = re.compile(r"[a-zà-ỹ0-9]+")


def title_ngrams(title):
    words = [w for w in NGRAM_RE.findall(title.lower()) if w not in STOPWORDS and len(w) > 2]
    grams = set()
    for n in (2, 3):
        for i in range(len(words) - n + 1):
            grams.add(" ".join(words[i:i + n]))
    return grams


def compute_hotness(all_articles):
    gram_sources = {}
    for art in all_articles:
        for g in art["grams"]:
            gram_sources.setdefault(g, set()).add(art["source"])
    gram_score = {g: len(s) for g, s in gram_sources.items()}
    for art in all_articles:
        best, best_gram = 1, ""
        for g in art["grams"]:
            if gram_score.get(g, 1) > best:
                best, best_gram = gram_score[g], g
        art["hot"] = best - 1
        art["hot_gram"] = best_gram
        art["hot_sources"] = best
    return gram_score, gram_sources


def recency_weight(dt, now):
    if not dt:
        return 0.0
    hours = max(0.0, (now - dt).total_seconds() / 3600)
    return max(0.0, 1.0 - hours / 72)


def pick_highlights(sections, now, limit=12):
    pool = [a for s in sections for a in s["articles"]]
    for a in pool:
        a["score"] = a["hot"] * 2.0 + recency_weight(a["dt"], now) * 1.5
    pool.sort(key=lambda a: (a["score"], a["dt"] or datetime(1970, 1, 1, tzinfo=UTC)), reverse=True)
    picked, per_sec, per_src = [], {}, {}
    for a in pool:
        if len(picked) >= limit:
            break
        if per_sec.get(a["sec_id"], 0) >= 3 or per_src.get(a["source"], 0) >= 2:
            continue
        picked.append(a)
        per_sec[a["sec_id"]] = per_sec.get(a["sec_id"], 0) + 1
        per_src[a["source"]] = per_src.get(a["source"], 0) + 1
    if len(picked) < limit:
        for a in pool:
            if a not in picked:
                picked.append(a)
            if len(picked) >= limit:
                break
    return picked


def section_summary(sec, gram_sources):
    arts = sec["articles"]
    if not arts:
        return "No articles loaded for this market in the latest update."
    local = {}
    for a in arts:
        for g in a["grams"]:
            local.setdefault(g, set()).add(a["source"])
    hot_phrases = sorted(
        ((g, len(s)) for g, s in local.items() if len(s) >= 2),
        key=lambda x: (x[1], len(x[0])), reverse=True)
    chosen = []
    for g, n in hot_phrases:
        if any(g in c or c in g for c, _ in chosen):
            continue
        chosen.append((g, n))
        if len(chosen) == 3:
            break
    newest = max(arts, key=lambda a: a["dt"] or datetime(1970, 1, 1, tzinfo=UTC))
    parts = []
    if chosen:
        tags = ", ".join(f'"{g}"' for g, _ in chosen)
        parts.append(f"Trending: {tags}.")
    parts.append(f"Latest: {newest['title'][:65]}… ({newest['source']})")
    return " ".join(parts)


# ---------------------------------------------------------------- collect

def collect():
    jobs = []
    for si, section in enumerate(SECTIONS):
        for source, url in section["feeds"]:
            jobs.append((si, source, url))

    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_feed, s, u): (si, s, u) for si, s, u in jobs}
        for fut in as_completed(futures):
            si, s, u = futures[fut]
            results[(si, u)] = fut.result()

    sections_out, diagnostics = [], []
    seen_links = set()

    for si, section in enumerate(SECTIONS):
        articles = []
        for source, url in section["feeds"]:
            src, _u, entries, ok, note = results[(si, url)]
            diagnostics.append((section["title"], src, url, ok, note))
            if not ok:
                continue
            for e in entries:
                link = (e.get("link") or "").strip()
                title = strip_html(e.get("title") or "")
                # Strip Google News suffix
                title = re.sub(r"\s*-\s*[A-Za-z][A-Za-z &.']+$", "", title)
                if not link or not title or link in seen_links:
                    continue
                summary = truncate(strip_html(e.get("summary") or e.get("description") or ""))
                if is_blocked(title, summary):
                    continue
                dt = entry_datetime(e)
                articles.append({
                    "source": src,
                    "sec_id": section["id"],
                    "grams": title_ngrams(title),
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "thumb": extract_thumb(e),
                    "dt": dt,
                    "hot": 0, "hot_gram": "", "hot_sources": 0,
                })
                seen_links.add(link)

        dated = sorted((a for a in articles if a["dt"]), key=lambda a: a["dt"], reverse=True)
        undated = [a for a in articles if not a["dt"]]
        selected = dated[:MAX_PER_SECTION] + undated[:3]
        sections_out.append({**section, "articles": selected[:MAX_PER_SECTION]})

    return sections_out, diagnostics


# ---------------------------------------------------------------- render

def esc(s):
    return html.escape(s or "", quote=True)


def fmt_dt(dt):
    if not dt:
        return ""
    return dt.strftime("%b %d · %H:%M")


MARKET_EMOJI = {"vietnam": "🇻🇳", "singapore": "🇸🇬", "australia": "🇦🇺", "usa": "🇺🇸", "korea": "🇰🇷", "tech-ai": "💻", "travel": "✈️"}


def render(sections, diagnostics, highlights, summaries):
    now = datetime.now(UTC)
    updated = now.strftime("%B %d, %Y · %H:%M UTC")

    def card(art, size="normal", badge=False):
        if art["thumb"]:
            thumb = f'<div class="thumb" style="background-image:url(\'{esc(art["thumb"])}\')"></div>'
        else:
            thumb = f'<div class="thumb thumb-empty"><span>{esc(art["source"][:2].upper())}</span></div>'
        hot_badge = ""
        if badge and art.get("hot", 0) >= 1:
            hot_badge = f'<span class="badge">{art["hot_sources"]} sources</span>'
        cls = "card" if size == "normal" else "card card-sm"
        return f'''<article class="{cls}">
        {thumb}
        <div class="card-body">
          <div class="card-meta"><span class="src">{esc(art["source"])}</span>{hot_badge}</div>
          <h3><a href="{esc(art["link"])}" target="_blank" rel="noopener">{esc(art["title"])}</a></h3>
          {"<p>" + esc(art["summary"]) + "</p>" if size == "normal" and art["summary"] else ""}
          <time>{fmt_dt(art["dt"])}</time>
        </div>
      </article>'''

    # ---- Homepage: Top Picks
    hl_cards = "".join(card(a, badge=True) for a in highlights)

    # ---- Homepage: snapshots grouped by category
    categories = {}
    for sec in sections:
        cat = sec.get("category", "other")
        categories.setdefault(cat, []).append(sec)

    CAT_LABELS = {"fashion": "👗 Fashion", "tech": "💻 Tech & AI", "travel": "✈️ Travel"}

    snapshots = ""
    for cat_id, cat_label in CAT_LABELS.items():
        cat_secs = categories.get(cat_id, [])
        if not cat_secs:
            continue
        inner = ""
        for sec in cat_secs:
            emoji = MARKET_EMOJI.get(sec["id"], "")
            top3 = "".join(card(a, size="small") for a in sec["articles"][:3])
            inner += f'''<div class="snapshot">
        <div class="snap-head">
          <h3><button class="snap-link" data-target="tab-{sec['id']}">{emoji} {esc(sec['title'])}</button></h3>
          <span class="snap-sub">{esc(sec.get('subtitle', ''))}</span>
        </div>
        <p class="snap-brief">{esc(summaries.get(sec['id'], ''))}</p>
        <div class="snap-cards">{top3}</div>
        <button class="snap-more" data-target="tab-{sec['id']}">See all {sec['title']} →</button>
      </div>'''
        snapshots += f'''<div class="cat-group">
        <h3 class="cat-title">{cat_label}</h3>
        <div class="snapshots">{inner}</div></div>'''

    # ---- Market tabs
    tab_buttons = ['<button class="tab active" data-target="tab-home">Overview</button>']
    tab_panels = []

    for sec in sections:
        emoji = MARKET_EMOJI.get(sec["id"], "")
        tab_buttons.append(f'<button class="tab" data-target="tab-{sec["id"]}">{emoji} {esc(sec["title"])}</button>')
        page1 = "".join(card(a, badge=True) for a in sec["articles"][:8])
        page2 = "".join(card(a, badge=True) for a in sec["articles"][8:16])
        slider = ""
        if page1:
            pages = f'<div class="slide-page"><div class="grid">{page1}</div></div>'
            nav = ""
            if page2:
                pages += f'<div class="slide-page"><div class="grid">{page2}</div></div>'
                nav = '<div class="slide-nav"><button class="sl-btn prev">‹</button><span class="sl-hint">Swipe or tap arrows for more</span><button class="sl-btn next">›</button></div>'
            slider = f'{nav}<div class="slide-track">{pages}</div>'
        else:
            slider = '<p class="empty">No articles loaded for this market.</p>'
        tab_panels.append(f'''<section class="panel" id="tab-{sec['id']}">
        <header class="sec-hd"><h2>{emoji} {esc(sec['title'])}</h2><span class="rule"></span></header>
        <p class="sec-brief">{esc(summaries.get(sec['id'], ''))}</p>
        {slider}
      </section>''')

    diag_html = "".join(
        f'<li class="{"ok" if ok else "err"}">{"✓" if ok else "✗"} {esc(src)} — {esc(note)}'
        f' <span class="durl">{esc(url[:60])}</span></li>'
        for _s, src, url, ok, note in diagnostics)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Pulse — Fashion · Tech · Travel — {now.strftime('%b %d, %Y')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#FAFAF8; --fg:#111; --rose:#9B2335; --sand:#C4A97D;
  --mute:rgba(17,17,17,.55); --line:rgba(17,17,17,.12); --card-bg:#fff;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--fg);font-family:'DM Sans',sans-serif;line-height:1.55}}
a{{color:inherit;text-decoration:none}}
.wrap{{max-width:1280px;margin:0 auto;padding:0 28px}}
header.mast{{padding:32px 0 18px;border-bottom:2px solid var(--fg)}}
header.mast .wrap{{display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:16px}}
h1{{font-family:'DM Serif Display',serif;font-size:44px;letter-spacing:-.02em}}
h1 em{{color:var(--rose);font-style:italic}}
.meta{{font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--mute);text-align:right}}
.refresh{{display:inline-block;margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:11px;
  border:1px solid var(--rose);color:var(--rose);padding:4px 10px}}
.refresh:hover{{background:var(--rose);color:#fff}}
nav.tabs{{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--fg)}}
nav.tabs .wrap{{display:flex;gap:2px;overflow-x:auto}}
.tab{{font-family:'JetBrains Mono',monospace;font-size:12px;background:none;border:none;
  border-bottom:3px solid transparent;color:var(--mute);padding:12px 14px 9px;cursor:pointer;white-space:nowrap}}
.tab:hover{{color:var(--fg)}}
.tab.active{{color:var(--fg);border-bottom-color:var(--rose);font-weight:500}}
.panel{{display:none;padding:36px 0 8px}}
.panel.active{{display:block}}
.sec-hd{{max-width:1280px;margin:0 auto 16px;padding:0 28px;display:flex;align-items:center;gap:16px}}
.sec-hd h2{{font-family:'DM Serif Display',serif;font-size:26px;white-space:nowrap}}
.rule{{flex:1;height:1px;background:var(--fg);position:relative}}
.rule::after{{content:"";position:absolute;right:0;top:-3px;width:6px;height:6px;background:var(--rose)}}
.sec-brief{{max-width:1280px;margin:-4px auto 20px;padding:0 28px;font-size:14px;color:var(--mute);
  border-left:3px solid var(--sand);padding-left:14px}}
.grid{{max-width:1280px;margin:0 auto;padding:0 28px;display:grid;grid-template-columns:repeat(4,1fr);gap:20px}}
@media(max-width:1080px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:640px){{.grid{{grid-template-columns:1fr}}h1{{font-size:30px}}.meta{{text-align:left}}}}
.card{{display:flex;flex-direction:column;border:1px solid var(--line);background:var(--card-bg)}}
.card-sm{{}}
.thumb{{aspect-ratio:16/9;background-size:cover;background-position:center;border-bottom:1px solid var(--line)}}
.thumb-empty{{display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,#f0ede6 0%,#e8e4db 100%)}}
.thumb-empty span{{font-family:'DM Serif Display',serif;font-size:18px;color:var(--sand);letter-spacing:.1em}}
.card-body{{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}}
.card-meta{{display:flex;align-items:center;justify-content:space-between;gap:6px}}
.src{{font-family:'JetBrains Mono',monospace;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--rose)}}
.badge{{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--sand);border:1px solid var(--sand);
  padding:1px 5px;letter-spacing:.04em;white-space:nowrap}}
.card h3{{font-family:'DM Serif Display',serif;font-weight:400;font-size:16px;line-height:1.3}}
.card h3 a:hover{{text-decoration:underline;text-decoration-color:var(--rose)}}
.card p{{font-size:13px;color:var(--mute);flex:1}}
.card time{{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--mute)}}
.home-sec{{max-width:1280px;margin:0 auto;padding:36px 28px 0}}
.home-sec h2{{font-family:'DM Serif Display',serif;font-size:26px;margin-bottom:18px;display:flex;align-items:center;gap:14px}}
.home-sec h2::after{{content:"";flex:1;height:1px;background:var(--fg)}}
.cat-group{{margin-bottom:32px}}
.cat-title{{font-family:'DM Serif Display',serif;font-size:22px;margin-bottom:4px;color:var(--fg);
  border-bottom:2px solid var(--rose);display:inline-block;padding-bottom:4px}}
.snapshots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px;margin-top:16px}}
.snapshot{{border:1px solid var(--line);background:var(--card-bg);padding:20px}}
.snap-head{{display:flex;align-items:baseline;gap:10px;margin-bottom:8px}}
.snap-head h3{{font-family:'DM Serif Display',serif;font-size:20px}}
.snap-link{{font:inherit;background:none;border:none;cursor:pointer;color:var(--fg)}}
.snap-link:hover{{text-decoration:underline;text-decoration-color:var(--rose)}}
.snap-sub{{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--mute)}}
.snap-brief{{font-size:13px;color:var(--mute);margin-bottom:12px;border-left:2px solid var(--sand);padding-left:10px}}
.snap-cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}
@media(max-width:640px){{.snap-cards{{grid-template-columns:1fr}}}}
.snap-cards .card{{border:none;border-top:1px solid var(--line)}}
.snap-cards .thumb{{aspect-ratio:4/3}}
.snap-cards .card h3{{font-size:14px}}
.snap-cards .card p{{display:none}}
.snap-more{{display:block;width:100%;margin-top:12px;padding:8px;font-family:'JetBrains Mono',monospace;
  font-size:11.5px;background:none;border:1px solid var(--line);color:var(--rose);cursor:pointer;text-align:center}}
.snap-more:hover{{background:var(--rose);color:#fff;border-color:var(--rose)}}
.slide-nav{{max-width:1280px;margin:-4px auto 12px;padding:0 28px;display:flex;align-items:center;gap:10px}}
.sl-btn{{font-size:15px;width:28px;height:28px;border:1px solid var(--fg);background:var(--card-bg);cursor:pointer}}
.sl-btn:hover{{background:var(--rose);border-color:var(--rose);color:#fff}}
.sl-hint{{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--mute)}}
.slide-track{{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;scroll-behavior:smooth}}
.slide-track::-webkit-scrollbar{{height:5px}}
.slide-track::-webkit-scrollbar-thumb{{background:var(--line)}}
.slide-page{{flex:0 0 100%;scroll-snap-align:start}}
.note{{max-width:1280px;margin:16px auto 0;padding:0 28px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--mute)}}
.empty{{max-width:1280px;margin:0 auto;padding:0 28px;color:var(--mute);font-size:14px}}
footer{{margin-top:48px;border-top:2px solid var(--fg);padding:24px 0 36px;font-size:13px}}
footer h4{{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);margin-bottom:8px}}
details{{margin-top:12px}}
summary{{cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--mute)}}
.diag{{list-style:none;margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.9}}
.diag .ok{{color:#48583F}}.diag .err{{color:#8a3324}}
.durl{{opacity:.45}}
.disc{{margin-top:12px;color:var(--mute)}}
</style>
</head>
<body>

<header class="mast">
  <div class="wrap">
    <h1>The <em>Pulse</em></h1>
    <div class="meta">
      {esc(updated)}<br>Auto-updated daily<br>
      <a class="refresh" href="https://github.com/trangtranadtima-cmd/the-pulse/actions/workflows/update.yml" target="_blank" rel="noopener">⟳ Update now</a>
    </div>
  </div>
</header>

<nav class="tabs"><div class="wrap">{''.join(tab_buttons)}</div></nav>

<main>
  <section class="panel active" id="tab-home">
    <div class="home-sec">
      <h2>Top Picks</h2>
      <div class="grid">{hl_cards}</div>
    </div>
    <div class="home-sec">
      <h2>By Market</h2>
      <div class="snapshots">{snapshots}</div>
    </div>
    <p class="note">Headlines sourced from RSS feeds of fashion publications. "N sources" badge = topic covered by multiple outlets. Tap any market card to explore more.</p>
  </section>
  {''.join(tab_panels)}
</main>

<footer>
  <div class="wrap">
    <h4>Sources</h4>
    <p>Vogue · Harper's Bazaar · Elle · Who What Wear · Highsnobiety · Hypebeast · RUSSH · TechCrunch · The Verge · Ars Technica · Wired · Nomadic Matt · Lonely Planet · Google News</p>
    <details>
      <summary>Feed diagnostics (latest run)</summary>
      <ul class="diag">{diag_html}</ul>
    </details>
    <p class="disc">Headlines and descriptions sourced directly from official RSS feeds. Click any article to read the full story at its original source.</p>
  </div>
</footer>

<script>
function activate(id){{
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.target===id));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===id));
  window.scrollTo({{top:0,behavior:'instant'}});
}}
document.querySelectorAll('.tab,.snap-link,.snap-more').forEach(el=>
  el.addEventListener('click',()=>activate(el.dataset.target)));
document.querySelectorAll('.panel').forEach(p=>{{
  const t=p.querySelector('.slide-track');
  if(!t)return;
  p.querySelectorAll('.sl-btn').forEach(b=>
    b.addEventListener('click',()=>t.scrollBy({{left:b.classList.contains('next')?t.clientWidth:-t.clientWidth,behavior:'smooth'}})));
}});
</script>
</body>
</html>'''


def main():
    sections, diagnostics = collect()
    total = sum(len(s["articles"]) for s in sections)
    ok_feeds = sum(1 for *_, ok, _ in diagnostics if ok)
    print(f"Total articles: {total} | Feeds OK: {ok_feeds}/{len(diagnostics)}")
    for sec_title, src, url, ok, note in diagnostics:
        print(f"  [{'OK ' if ok else 'ERR'}] {src:<20} {note:<20} {url[:60]}")

    now = datetime.now(UTC)
    all_articles = [a for s in sections for a in s["articles"]]
    compute_hotness(all_articles)
    highlights = pick_highlights(sections, now, limit=12)
    summaries = {s["id"]: section_summary(s, {}) for s in sections}

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(render(sections, diagnostics, highlights, summaries))
    print("Written index.html")

    if total == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
