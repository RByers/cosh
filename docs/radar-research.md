# Cloudflare Radar browser share: research and implementation

Status (2026-11-03): the code is in place and unit-tested against synthetic
responses. **No data has been fetched yet** because the Radar API needs an API
token and none is configured on this machine. See [What you need to
do](#what-you-need-to-do).

```
export CLOUDFLARE_API_TOKEN=...      # custom token, Account > Radar > Read
python3 -m cosh radar                # fetch (serial, >= 1 s apart) + write CSV
python3 -m cosh radar --offline      # rebuild the CSV from the raw cache only
python3 -m unittest tests.test_radar
```

## 1. Access and auth

- **The API needs a token.** `https://api.cloudflare.com/client/v4/radar/...`
  without credentials answers HTTP **400** with error code 9106 ("Missing
  X-Auth-Key, X-Auth-Email or Authorization headers"). Checked 2026-11-03.
- **No unauthenticated route that we may use.** `radar.cloudflare.com` (the
  site, its internal `/api/` data endpoints, CSV downloads, the quarterly
  reports and even `robots.txt`) returns a JavaScript bot challenge (HTTP 403,
  "Just a moment...") to non-browser clients. We do not get around it.
- **Token:** a free Cloudflare account is enough. Create a *Custom Token* with
  permission **Account > Radar > Read**. The reference also lists "User
  Details Read" as an accepted permission. Send it as
  `Authorization: Bearer <token>`. The code reads `CLOUDFLARE_API_TOKEN`.
- **Rate limits:** the Radar docs give none. The general Cloudflare API limit
  is 1,200 requests per 5 minutes per user. A full backfill is about 75
  requests (25 quarters × 3 device types), and a weekly update is 3 requests.
  We still keep to the house rules: serial requests, at least 1 s apart, gzip,
  and exponential backoff that honours `Retry-After` on 429/5xx.

## 2. Endpoint and parameters we use

`GET /radar/http/timeseries_groups/BROWSER`

This is the "timeseries groups by dimension" (v2) endpoint. The older
`/radar/http/timeseries_groups/browser` and `/browser_family` endpoints are
marked deprecated, but they take the same parameters, so if v2 misbehaves,
switching `ENDPOINT` in `cosh/radar.py` should be enough.

| Parameter | Value | Why |
|---|---|---|
| `aggInterval` | `1d` (`--agg 1w` optional) | Allowed values are `15m`, `1h`, `1d`, `1w`. The API rejects an interval that is too fine for the range. Daily buckets have exact UTC-day boundaries, so we build ISO weeks (Mon–Sun, UTC) and calendar months locally. Radar's own week alignment is not documented. |
| `dateStart` / `dateEnd` | one calendar quarter per request, `YYYY-MM-DDT00:00:00Z` | `dateRange` is capped at 52 weeks or 364 days and is relative to now, so explicit dates are used instead. `dateEnd` is *inclusive* (floored to 15 min), so the parser drops any bucket at or after the chunk end. |
| `botClass` | `LIKELY_HUMAN` | Human traffic only: bot score ≥ 30. Scores 1–29 are "likely automated". |
| `deviceType` | none (`DEVICES = ("ALL",)`) | The `device` column holds `all`. The code can also fetch `DESKTOP` / `MOBILE`, but the UI uses only `all`, so they aren't fetched by default. |
| `os` | none, and `IOS` for the `browser_ios` series | Used to **exclude iOS** (below). Radar takes a single `os` value: `-IOS` and comma lists are rejected (HTTP 400), and a repeated parameter makes separate series. |
| `limitPerGroup` | `50` | Top N browsers per range. The rest is summed into an `other` series. The minimum is 2 and the maximum is undocumented; change it with `--limit-per-group`. |
| `normalization` | `PERCENTAGE` | Values are percentage *strings* of human HTTP requests. We store fractions (0–1). |
| `format` | `JSON` | `CSV` exists, but JSON keeps the `meta` block (lastUpdated, confidence annotations). |

The response is `result.serie_0 = {timestamps: [...], "<browser>": ["12.3", ...], "other": [...]}`,
plus `result.meta`. The parser reads every list-valued key except `timestamps`
as one browser.

**History.** The docs do not say how far back HTTP data goes. Radar launched
in September 2020, and the API is known to have data from at least 2022. The
code requests from `--start 2020-09-01`, **newest quarter first**:

- Any non-200 for a chunk less than a year old, and any auth error (some come
  back as HTTP 400), stops the run without caching anything.
- An older chunk that returns 4xx is cached as "no data" and skipped on later
  runs, unless `--retry-errors` is given.

After the first real run, record the actual start date here.

**Excluding iOS (2026-11-03).** iOS is left out entirely. Every iOS browser
must use WebKit (Chrome iOS, which Radar files under `ChromeMobile`, included),
and iOS in-app browsers use WKWebView, so Chromium usage there is negligible.
Because Radar can't exclude an OS in one query, three series are fetched per
quarter:

| series | endpoint | extra parameters |
|---|---|---|
| `browser` | `timeseries_groups/BROWSER` | none (all OSes) |
| `browser_ios` | `timeseries_groups/BROWSER` | `os=IOS` |
| `os` | `timeseries_groups/OS` | no `limitPerGroup` (Radar rejects it for OS) |

For each day and browser *b*, with *w* the iOS share of human requests:
`non_ios(b) = (all(b) − w·ios(b)) / (1 − w)`, clamped at 0
(`radar.exclude_ios`). A day missing either iOS series is dropped rather than
left with iOS in it. Check on 2026-10-26: for Android-only browsers the
result matched a direct `os=ANDROID` query to 4 decimals (ChromeMobileWebview
0.09968 vs 0.09965, Instagram 0.00682 vs 0.00682, ChromeMobile 0.23708 vs
0.23707). iOS was 18% of human requests that day. On iOS, ChromeMobile
(Chrome iOS) was 24% and Facebook 0.22%, so Facebook's non-iOS share is
*lower* than its all-OS share. Instagram's iOS traffic is mostly labelled as
`MobileSafariWebview` instead.

## 3. Files

- `data/public/radar/raw/<series>_<device>_<agg>_<quarterStart>_<quarterEnd>.json`
  (`series` is `browser`, `browser_ios` or `os`): the request parameters, HTTP
  status, `fetched_at`, a `complete` flag and the unmodified response. Radar
  data is public (CC BY-NC 4.0, §6), so this is committed.
- **Re-runs are incremental:**
  - A complete past quarter is never fetched again.
  - The current quarter is fetched again only when a new UTC day has ended
    since its last fetch.
  - `--offline` rebuilds the CSV from the cache without any network access.
- `data/public/radar_browser_share.csv`: one row per
  (period, granularity, device, browser).

  | column | meaning |
  |---|---|
  | `period` | `2026-W44` (ISO week) or `2026-10` (month) |
  | `period_start`, `period_end` | inclusive UTC dates |
  | `granularity` | `week` or `month` (with `--agg 1w`, only `week`) |
  | `device` | `all`, `desktop`, `mobile` |
  | `browser` | name exactly as Radar reports it; `Other` = Radar's `other` bucket |
  | `is_chromium`, `kind` | from `config/browsers.csv`; empty means not in the config (a warning is printed) |
  | `days` | number of daily points in the period. Partial weeks and months (the first and the current one) have fewer than 7 or 28–31 days, so filter on this column. |
  | `raw_share` | mean of the daily shares of human requests from **non-iOS** devices (0–1). A browser that is missing on a day counts as 0. |
  | `chromium_share` | `raw_share` / sum of `raw_share` over `is_chromium=1` with `kind` `browser`, `webview` or `in_app` (bots and TVs excluded). These shares sum to 1 per period and device. This is the denominator of the value ratio. |

  Until 2026-11-03 `chromium_share` covered standalone browsers only, and a
  `chromium_share_all` column added WebViews and in-app browsers. Both
  included iOS.

- The weekly value is the *unweighted* mean of the daily shares. A true
  request-weighted weekly share would weight days by traffic volume, but
  weekday/weekend volume differences are small at this level and affect
  numerator and denominator alike.

## 4. Browsers and Chromium classification

`config/browsers.csv` maps each Radar browser name to `is_chromium` (0/1), a
`kind` (`browser`, `webview`, `in_app` or `other`) and a note. The names are
our best guess at Radar's labels. Its browser report uses ua-parser style
names, for example "Chrome Mobile WebView" and "Mobile Safari UI/WKWebView".
**Check them against the first real response:** the run prints any name that
is missing from the config, and such names count as non-Chromium until they
are added.

Clear cases:

- **Chromium:** Chrome, Chrome Mobile (Android), Edge and Edge Android,
  Samsung Internet, Opera / Opera GX / Opera Android, Yandex Browser, Vivaldi,
  Whale, Silk, Coc Coc, MIUI/Mi Browser, Huawei Browser, HeyTap, Vivo Browser,
  Brave, Arc.
- **Not Chromium:** Safari / Mobile Safari, Firefox / Firefox Mobile, all iOS
  browsers (Apple requires WebKit, so Chrome iOS, Edge iOS, Opera iOS and
  Firefox iOS are WebKit), Opera Mini (server-side proxy), IE, legacy
  EdgeHTML, and the AOSP stock browser.

Judgement calls:

- **Android WebView** (`Chrome Mobile WebView`): `is_chromium=1`,
  `kind=webview`.
  - It is Chromium code shipped by Google, though the user picked an *app*,
    not a browser. Radar's own browser report drops WebViews.
  - **Decision (2026-11-03, user): counted in `chromium_share` and credited to
    google.com.** It is about 12% of Chromium usage.
  - **Replaced (2026-11-04, user): left out of the value ratio's denominator
    and credited to no org.** Many different browsers and apps embed Android
    WebView, so its usage can't be attributed to Google or any other single
    org. The web UI drops it like ChromeDerivative (`RATIO_EXCLUDED_BROWSERS`
    in `web/src/data.ts`) and renormalizes each org's share to the rest. It
    stays in `chromium_share` in the CSV and in the usage chart.
- **In-app browsers** (Facebook, Instagram, Snapchat, Pinterest, Microsoft
  365, …; `kind=in_app`): **counted in `chromium_share`** (user, 2026-11-03).
  On Android they are WebView (Chromium); on iOS they are WKWebView, and iOS
  is excluded (§2). Facebook and Instagram are credited to meta.com and Microsoft365
  to microsoft.com (user, 2026-11-03). The rest
  are credited to no org, which dilutes every org slightly.
- **UC Browser, QQ Browser, Sogou, 360 Browser:** Chromium-derived kernels
  (U4, X5/XWeb) or dual Chromium+Trident engines. Classified `1`.
- **DuckDuckGo:** WebView2 on Windows (Chromium), WebKit on macOS and iOS,
  Android WebView on Android. It cannot be split, so it is classified `0`.
- **Chromium (unbranded):** kept as a Chromium browser that maps to no org.
  It dilutes every org slightly.
- **Edge on iOS:** if Radar files it under Edge or Edge Mobile, it is
  (wrongly) counted as Chromium. It is small and cannot be separated.
- **The `other` bucket:** never counted as Chromium. With `limitPerGroup=50`
  it should be tiny. If it is not, raise the limit.

## 5. Org ↔ browser mapping

`config/org_browsers.csv` has the columns `org_domain,browser,notes`.

- google.com → Chrome, Chrome Mobile. Android System WebView
  (`ChromeMobileWebview`) was credited to Google until 2026-11-04; it is now
  credited to no org and left out of the ratio (§4).
- microsoft.com → Edge, Edge Mobile, Microsoft 365's in-app browser (`Microsoft365`)
- samsung.com → Samsung Internet
- meta.com → the Facebook and Instagram in-app browsers (fb.com reviewers are
  counted as meta.com; `DOMAIN_ALIASES` in `cosh/orgs.py`)
- opera.com → Opera, Opera Mobile, Opera GX
- brave.com → *none.* Excluded (2026-11-03): Radar's Brave label is about 0%
  and the real usage is counted as Chrome (§6). The web UI lists brave.com
  with usage "unknown" (`UNKNOWN_USAGE_ORGS` in `web/src/data.ts`).
- yandex-team.ru → Yandex Browser
- vivaldi.com → Vivaldi
- navercorp.com and naver.com → Whale
- amazon.com → Silk
- coccoc.com → Coc Coc
- huawei.com → Huawei Browser
- xiaomi.com → MIUI/Mi Browser
- tencent.com → QQ Browser
- alibaba-inc.com → UC Browser (UCWeb is part of Alibaba)

An org's derived-value share is the sum of `chromium_share` over its browsers.
Chromium browsers with no org (unbranded Chromium, HeyTap, Vivo and others)
stay in the denominator, so org shares do not have to sum to 1. This is
deliberate: those users still get value from Chromium, and nobody is credited
with it.

## 6. Limitations

- **UA-based identification.** Radar identifies browsers from the
  `User-Agent` header, plus User-Agent Client Hints since 2024 Q1. That
  change may cause a step change around January 2024.
- **Brave and Vivaldi are mostly invisible.** Brave sends Chrome's UA and
  Client Hints, and Vivaldi does too on most sites. Both are counted as
  Chrome. Brave's and Vivaldi's shares will be roughly 0, which overstates
  Chrome's share and therefore *understates* Google's value ratio. The same
  applies to Arc, Kiwi and other forks. If needed, an external estimate such
  as Brave's published MAU could be used to re-split Chrome's share.
- **Request share, not user share.** These are shares of HTTP requests, not
  of users or page views. Heavy users and request-heavy sites weigh more.
- **Bot filtering is probabilistic.** `LIKELY_HUMAN` means a bot score of 30
  or more. Some automation that uses headless Chrome will still get through,
  which inflates Chrome.
- **Cloudflare sample bias.** The data covers only traffic to sites behind
  Cloudflare's proxy. That is a large but not representative sample, with
  skews by region and kind of site. Markets that matter for Yandex (Russia),
  Whale (Korea) and the Chinese browsers may be under-represented.
- **Taxonomy drift.** Radar's labels and parser can change over time (for
  example the DuckDuckGo UA change in 2023 Q4). Watch for browsers that appear
  or vanish abruptly.
- **Global only.** We use no `location` filter. Per-country data is
  available if it is ever needed.

## 7. Licence and attribution

Radar data from the API or downloaded from radar.cloudflare.com is licensed
under **CC BY-NC 4.0**. Graphs and images embedded from the Radar site are
under CC BY 4.0. (The French About page says CC BY 4.0 for the data as well;
the English and other language versions say BY-NC.)

What this means for us:

- **Attribution.** Credit Cloudflare Radar, link to
  https://radar.cloudflare.com/ and the licence, and say that the data was
  modified (renormalised). For example: "Browser usage: Cloudflare Radar
  (radar.cloudflare.com), CC BY-NC 4.0; renormalised to Chromium-based
  browsers by cosh."
- **Non-commercial use only.** For an exception, contact the address on the
  Radar About page.
- **Repository.** Committing `data/public/radar/**` is fine under the
  licence, given the attribution. Put a note in the data directory or the
  README.

## 8. Joining with the review data

- **Week alignment.** The review summaries are keyed by `iso_week` (Mon–Sun,
  UTC). Join on `radar_browser_share.csv` where `granularity='week'`,
  `device='all'` and `period = iso_week`. The weeks are built from UTC days,
  so the boundaries match exactly.
- **Partial weeks.** Use only weeks with `days = 7`. The current week is
  partial until it ends.
- **Org share.** `derived_value_share(O, w) = Σ chromium_share` over the
  browsers that `config/org_browsers.csv` maps to O. Then
  `value_ratio = contribution_share / derived_value_share`.
- **Smoothing.** Weekly review shares are noisy. A smoother option is
  month-to-month: aggregate the review data to calendar months and join
  `granularity='month'`.
- **Missing values.** An org with no mapped browser, or a share of ~0 (Vivaldi;
  Brave is excluded outright), has an undefined or infinite ratio. Report its contribution share
  only.
- **Device split.** `desktop` and `mobile` rows can feed a sensitivity
  analysis; Edge's share, for example, is far higher on desktop.

## Findings from the first real fetch (2026-11-03)

**History.**
- Daily data for all devices is available from **2023-07-01**, which gives
  174 full ISO weeks through 2026-W44.
- Requests for 2023 Q2 returned HTTP 500 six times in a row, so the fetch
  stopped there.
- Earlier data may need a different `aggInterval` or smaller chunks.
  Untested.
- So far only `device=all` is fetched; desktop and mobile come later.

**Browser names.** Radar uses CamelCase labels such as `ChromeMobile`,
`SamsungInternet` and `ChromeMobileWebview`. `config/browsers.csv` and
`config/org_browsers.csv` now use these real names. All 40 labels seen are
classified.

**Brave** has its own label but rounds to 0.00%. It is invisible in practice,
as predicted.
- Checked 2026-11-03: over 2025-W45..2026-W44 the `Brave` row averages
  0.0022% of Chromium usage (range 0.0007%–0.0084%); in 2023–2024 it is
  0.0001%. Brave's own figure of about 100M monthly users against Chrome's
  ~3.5B puts it at roughly 2–3% of Chromium, about 1000 times more.
- Brave sends an unmodified Chrome `User-Agent` and identifies itself only
  in `Sec-CH-UA` (`"Brave";v="…"`). Radar uses Client Hints since 2024 Q1,
  but the share did not move, so whatever traffic it does label Brave is a
  sliver. Cloudflare documents nothing about this.
- So brave.com is **excluded** from the ratio. Its usage is unknown and
  most likely counted as Chrome, which overstates Google's usage share by a
  few points and so slightly understates Google's ratio.

**`ChromeDerivative`** is Radar's bucket for Chromium-based browsers it can't
name.
- It was 0.2–0.7% of Chromium usage from 2023-07 to 2026-08, then jumped to
  7.3% in 2026-09, 10.8% in 2026-10 and 11.3% in 2026-11.
- It sits in the denominator with no org, so from September 2026 it lowers
  Chrome's share, and raises Google's ratio, by about 10%.
- **Decision (2026-11-03): keep it in the denominator.** It may be real
  Chromium-based browser usage, and the denominator should include all
  Chromium usage. The UI explains the jump instead of hiding it.

**Investigation of the September 2026 `ChromeDerivative` jump** (2026-11-03).
Shares below are of all `LIKELY_HUMAN` requests (Radar's raw percentage), not
Chromium-only shares.
- **Step change on 2026-09-09.** It was 0.20% on Sept 8, 3.6% on Sept 9, 6.3%
  on Sept 10, and 7–8% since then with no further growth. A partial first
  day looks like a deploy rollout, not organic adoption.
- **Taken from every browser in proportion, not from Chrome.** Comparing
  2026-08-25..09-07 with 2026-09-14..09-27, after removing ChromeDerivative
  and renormalizing, other browsers barely move: Chrome +2%, ChromeMobile −2%,
  Edge 0%, MobileSafari +3%, Safari +7%, Firefox −4%. The exception is
  SamsungInternet, at −15%. The new ~7% looks like traffic that previously had
  no browser label (and so was outside the normalized top 50), not Chrome
  traffic that was relabeled.
- **Not a bot-to-human reclassification.** Radar's overall human/bot split
  (`BOT_CLASS`) stayed at about 66/34 through 09-09. Within `LIKELY_AUTOMATED`,
  ChromeDerivative jumped on the same day too, from 0.2% to about 2.5%. So the
  change is in how browsers are labeled, not in bot scoring.
- ~~**Device mix is like human browsing.**~~ **Wrong (2026-11-04):** Radar
  silently ignores a `browser=` filter, so this was the device mix of *all*
  human traffic. Per-OS queries show the new traffic is desktop only. See
  [the follow-up below](#chromederivative-follow-up-firefox-safari-countries-2026-11-04).
- **No public explanation from Cloudflare.**
  - Radar annotations for 2026-08-25..09-25 list only outages.
  - The Radar changelog for Aug–Oct 2026 has nothing on browser or bot
    classification.
  - The nearest related item is Bot Management "Adaptive Intelligence"
    (blog, 2026-08-31): continuously retrained models, with new detections
    rolled out gradually. It mentions catching clients that claim to be one
    browser but show another's signals, but says nothing about Radar's
    browser labels.
- **Best guess (unconfirmed):** Radar changed browser detection on 2026-09-09,
  perhaps to use TLS or JS fingerprints rather than the UA string. That
  started labeling previously unlabeled, mostly human-like Chromium traffic.
  Agentic browsers may be part of it; the data can't tell.
- **To confirm:** ask Cloudflare's Radar team (radar@cloudflare.com or the
  community forum).

**Chromium shares**, as of 2026-11-03: non-iOS traffic, with WebView and
in-app browsers in the denominator (the current `chromium_share`):

| week | Chrome (desktop + Android) | Android WebView | Edge | Samsung Internet | Opera (+ mobile) | Meta (Facebook + Instagram) | ChromeDerivative |
|---|---|---|---|---|---|---|---|
| 2023-W27 | 73.6% | 9.0% | 5.9% | 3.3% | 2.5% | 3.8% | 0.5% |
| 2026-W44 | 66.1% | 11.6% | 7.8% | 1.5% | 1.4% | 1.0% | 10.3% |

Under the earlier definition (all OSes, standalone browsers only), which the
ChromeDerivative percentages above also use:

| week | Chrome (desktop + Android) | Edge | Samsung Internet | Opera (+ mobile) | Yandex | ChromeDerivative |
|---|---|---|---|---|---|---|
| 2023-W27 | 85.3% | 6.4% | 3.6% | 2.7% | 0.7% | 0.5% |
| 2026-W44 | 77.3% | 8.3% | 1.6% | 1.5% | <0.1% | 11.0% |

## ChromeDerivative follow-up: Firefox, Safari, countries (2026-11-04)

The raw responses (about 70 requests, serial, ≥ 1 s apart) and the scripts are
in `data/public/radar/adhoc/2026-11-04-chromederivative/`. Responses under
`ignored/` used the `browser=` filter. Radar accepts that filter but ignores
it and returns all-traffic data, so they are kept only as a record.
Filters that do work: `location`, `os`, `asn`, `deviceType`,
`browserFamily`. `OS`, `DEVICE_TYPE`, `TLS_VERSION`, `HTTP_VERSION` and
`POST_QUANTUM` reject `limitPerGroup`. `/http/timeseries` at `1d` rejects a
3-month range. Every endpoint caps a range at 374 days.

**Firefox and Safari did not drop at the jump.** Their falls in `BROWSER`
share are dilution: a new ~7% enters the denominator.
- `BROWSER` share, weekdays Sep 1–4 vs Sep 14–17: Chrome −7%, Edge −7%,
  Firefox −10%, Safari −2%, MobileSafari −5%, SamsungInternet −18%.
- `BROWSER_FAMILY` daily share has **no step** on 09-09: Firefox was 3.66%
  on 09-08 and 3.63% on 09-10, and the Chrome family stayed at about 69%.
  So the family series already counted this traffic (as `chrome`).
  `BROWSER` had dropped it.
- Volume (`browserFamily`, `MIN0_MAX`), Sep 1–7 vs Sep 15–21: all human
  traffic −1.3%, Firefox −5.3%, Chrome −2.1%, Safari +1.1%, Edge −0.7%. No step.
- Over a year (weekly, family volume / total volume, Nov 2025 = 1.00), Firefox
  falls steadily: 0.94 in Aug, 0.89 on Sep 14, 0.87 at the end of Oct. Chrome
  falls 0.95 → 0.91 and Safari stays at 0.92–0.95. Firefox's decline is real
  but gradual, not tied to 09-09.
- The year-ago window (Sep 2025) can't serve as a seasonal baseline: the
  family volumes rise 30–50% there while total traffic rises 5%, which looks
  like a Radar change in Sept 2025.

**Desktop only.** `ChromeDerivative` share, Sep 1–7 → Sep 15–21: Windows
0.15 → 16.3%, macOS 0.0 → 10.8%, Linux 0.2 → 3.9%, ChromeOS 0.0 → 0.15%,
**Android 0.42 → 0.44% (no jump)**. The same holds within countries. On
Android: KR 0.0 → 0.1%, and the RU and US Android top 8 doesn't include it.
On Windows: RU 39%, KR 34%, US 15%. On US macOS: 8.7%.

**Same day everywhere, very different levels by country** (share of all
human requests, Sep 15–21; the step falls on 09-09 or 09-10 UTC in every
country):

| | ChromeDerivative | | ChromeDerivative |
|---|---|---|---|
| RU | 27.7% | US | 7.1% |
| KR | 19.9% | GB | 7.0% |
| TW | 14.5% | TR | 6.4% |
| PL | 12.5% | BR | 6.2% |
| CN | 11.4% (6.1% before) | JP | 5.8% |
| AR, FR | 9.7% | MX | 5.3% |
| SA | 9.4% | IN | 2.5% |
| DE | 9.0% | NG | 1.5% |
| CA | 8.9% | BD | 1.6% |

- Mobile-heavy countries (IN, NG, BD, PK, ID) are low because the new label
  is desktop only.
- Within each country, every other browser falls in proportion. On RU
  Windows: Chrome −38%, Edge −41%, Opera −43%, Firefox −39%. So the traffic
  was newly counted, not taken from Chrome.
- **Russia fits Yandex Browser.** Statcounter puts Yandex at about 27–29% of
  Russian desktop use (Jun–Aug 2026). Before the jump, Radar's `Yandex`
  label was 0.1% of RU Windows traffic.
- **Korea fits Naver Whale only in part.** Whale has about 4% of Korean
  desktop use, while `ChromeDerivative` is 34% of KR Windows traffic.
- **Weekend skew points to home or leisure use.** On Windows (Sep 14–20),
  weekend share over weekday share is 1.38× for ChromeDerivative (US 1.47×,
  KR 1.22×, RU 1.05×). Chrome is 0.95× and Edge 0.76×.

**News correlation.** Nothing launched on 2026-09-09.
- **ChatGPT Atlas** (macOS, Oct 2025) never shipped on Windows and was
  switched off on 2026-08-09.
- **The ChatGPT desktop app** with a built-in browser launched on 2026-07-09
  (macOS, Windows), and gained Chrome extension support around 09-18. Neither
  date matches.
- **Meta Muse** (09-08) is a cloud agent, not a desktop client.
- **Strawberry 1.0** launched on 10-26.
- A launch also wouldn't step up on the same UTC day in 30 countries, and
  wouldn't peak in Russia, where OpenAI doesn't serve users.

**Conclusion (still unconfirmed by Cloudflare):** on 2026-09-09 Radar's
`BROWSER` classifier started labeling desktop Chromium clients it had
previously left unlabeled. These are not Chrome, and they were already
counted in the `chrome` family. The country pattern fits Chromium forks
that identify themselves only in Client Hints or other non-UA signals:
Yandex (RU), Whale (KR) and likely Brave, Vivaldi, Arc and others. It may
also include desktop apps that embed Chromium (Electron/CEF), which would
fit the weekend skew. It is not an adoption event.

Implication for the UI: excluding `ChromeDerivative` from the ratio
denominator (`RATIO_EXCLUDED_BROWSERS`) is consistent with this. The traffic
was absent from `BROWSER` shares before 09-09, so excluding it keeps the
series comparable over time.

## Facebook's 2024-W39 drop (investigated 2026-11-03)

Radar's `Facebook` label (non-iOS, share of all human requests) fell from about
2.1% to 0.35% over 2024-W38..W41 and has stayed there (0.15% in 2026-W43,
0.17% of Chromium). Instagram has held steady at about 0.7% (0.8% of
Chromium). All-OS Facebook partly recovered from 2024-W47, but the recovery
was iOS-only, and iOS is excluded.

- A user-behaviour change this abrupt (−85% in three weeks) is implausible.
  It looks like a user-agent or classifier change, for example the Android
  Facebook app's in-app browser no longer being recognised as Facebook.
- No single label gained the lost share. Chrome rose 1.9pp across those weeks,
  but its autumn swing is seasonal (+3.4pp in 2023, −1.3pp in 2025).
  ChromeMobile, which fell 2.7pp over the same weeks in 2023, fell only 0.15pp
  in 2024. That points to the traffic being relabelled as Chrome Mobile (which
  would credit it to google.com) or WebView (left out of the ratio since
  2026-11-04). This is unconfirmed.
- Effect: since 2024-W40, meta.com's usage share (and so the denominator of its
  value ratio) is probably understated by about 2pp of Chromium usage. Its
  ratio is therefore overstated by up to roughly 3×, and Google's usage is
  overstated by the same 2pp. No correction is applied.
- For scale: the widely quoted 8.8% for Facebook's in-app browser (Mixpanel,
  2018) is US-only, includes iOS and counts page views. Radar is global,
  excludes iOS here and counts all HTTP requests, so it should be far lower
  even without the drop.
- The usage chart always plots Facebook and Instagram
  (`ALWAYS_CHARTED_BROWSERS` in `web/src/data.ts`).
