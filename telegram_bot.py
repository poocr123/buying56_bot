#!/usr/bin/env python3
"""
📱 주식 알림봇
데이터: Yahoo Finance v8 Chart API (전종목 차트에서 직접 계산)
- 가격, 거래량, 이동평균 모두 차트 데이터 하나로 해결
- 전일 거래량 = 차트의 어제 volume
- 시가총액 = quote API
"""

import asyncio, logging, os, sys, time, threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
KST = ZoneInfo("Asia/Seoul")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

CONFIG = {
    "min_price":      1_000,
    "min_market_cap": 50_000_000_000,
    "min_vol_ratio":  500,
    "ma_short":       5,
    "ma_long":        20,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

# ══════════════════════════════════════════════
#  종목 리스트 (실제 상장 종목 코드)
# ══════════════════════════════════════════════
_KS = """
000020 000040 000050 000060 000070 000080 000100 000120 000140 000150 000180 000210 000220
000240 000250 000270 000300 000320 000370 000400 000420 000480 000490 000520 000540 000570
000590 000640 000650 000660 000670 000680 000720 000760 000810 000850 000880 000900 000990
001020 001040 001060 001080 001120 001200 001230 001250 001340 001360 001380 001430 001440
001450 001460 001510 001520 001530 001570 001590 001620 001680 001700 001720 001750 001760
001800 001820 001880 001940 001970 001980 002020 002030 002070 002080 002100 002140 002150
002170 002180 002200 002220 002240 002250 002280 002300 002320 002380 002390 002420 002440
002460 002540 002550 002570 002580 002630 002640 002670 002690 002700 002720 002780 002790
002820 002860 002880 002900 002930 002940 002990 003000 003030 003070 003090 003120 003130
003140 003160 003200 003220 003230 003250 003260 003290 003300 003350 003360 003380 003410
003420 003430 003450 003490 003520 003530 003550 003560 003570 003580 003600 003620 003640
003650 003670 003680 003700 003730 003750 003760 003780 003800 003820 003860 003900 003920
003940 003960 003970 004000 004020 004040 004060 004080 004090 004130 004170 004180 004200
004210 004220 004240 004280 004300 004310 004360 004380 004420 004430 004440 004450 004490
004520 004540 004560 004570 004580 004590 004610 004620 004630 004660 004690 004700 004720
004800 004820 004840 004860 004900 004920 004960 004990 005010 005020 005040 005090 005100
005110 005120 005130 005180 005200 005210 005230 005250 005260 005290 005300 005320 005330
005340 005360 005380 005385 005390 005400 005410 005420 005430 005440 005450 005460 005490
005520 005550 005560 005570 005590 005600 005610 005620 005630 005640 005650 005660 005680
005690 005720 005730 005740 005750 005800 005810 005830 005840 005870 005880 005930 005940
005950 005960 005970 005980 006020 006040 006050 006070 006090 006100 006120 006130 006140
006150 006160 006180 006200 006220 006230 006260 006270 006280 006300 006310 006340 006360
006380 006400 006410 006430 006440 006460 006490 006520 006560 006580 006600 006620 006640
006660 006700 006730 006760 006800 006820 006840 006860 006880 006920 006960 006980 007010
007020 007040 007070 007080 007130 007160 007180 007220 007260 007270 007310 007370 007440
007460 007490 007540 007590 007600 007680 007730 007770 007800 007840 007860 007900 007940
007960 007990 008040 008060 008080 008120 008150 008160 008180 008250 008280 008310 008330
008360 008450 008490 008530 008580 008620 008640 008660 008700 008730 008770 008810 008840
008880 008930 008990 009080 009120 009140 009150 009200 009240 009290 009320 009370 009420
009440 009460 009490 009530 009560 009580 009620 009720 009780 009820 009840 009880 009930
009970 009990 010060 010130 010140 010200 010240 010320 010380 010400 010470 010520 010530
010600 010620 010640 010720 010780 010840 010950 011040 011070 011090 011100 011170 011200
011280 011300 011390 011430 011470 011560 011580 011640 011680 011720 011760 011780 011790
011810 011870 011900 011970 012050 012080 012130 012180 012220 012250 012280 012320 012330
012360 012380 012420 012450 012540 012580 012630 012650 012690 012750 012800 012840 012870
012900 012950 012980 013060 013120 013140 013220 013280 013360 013420 013460 013550 013620
013690 013750 013810 013860 013940 014030 014060 014100 014140 014200 014260 014320 014350
014420 014440 014530 014580 014630 014680 014720 014780 014860 014990 015040 015080 015120
015150 015200 015360 015380 015400 015480 015540 015590 015640 015650 015670 015760 016050
016100 016150 016220 016280 016360 016380 016420 016480 016520 016580 016660 016720 016790
016860 017060 017080 017170 017220 017280 017390 017400 017460 017510 017560 017600 017670
017680 017700 017820 017860 017900 017940 018040 018070 018110 018150 018260 018300 018380
018430 018440 018470 018520 018560 018630 018670 018720 018750 018800 018830 018860 018920
018970 019070 019170 019300 019430 019540 019600 019680 019750 019810 019860 019940 019970
019990 020020 020050 020080 020140 020150 020200 020280 020370 020400 020440 020570 020650
020710 020820 021050 021080 021240 021280 021450 021820
"""

_KQ = """
030200 033100 033640 033780 034020 034230 034490 034730 034830 034950 035080 035150 035200
035420 035720 035900 036030 036460 036570 036810 037030 037350 037460 037560 037730 038040
038060 038120 039030 039200 039420 039440 039490 039560 039670 039740 040080 040150 040180
040340 040350 040430 040440 040460 040480 040520 040560 040600 040630 040680 040710 040750
040770 040830 040870 040940 040960 041040 041140 041440 041510 041570 041600 041630 041660
041720 041830 041920 041960 042000 042420 042520 042670 042700 042940 043090 043220 043270
043360 043410 043580 043710 043940 044060 044080 044490 044820 044990 045100 045300 045510
045610 045700 046390 046400 046560 046600 046620 046680 046700 046730 046750 046780 046870
046900 047050 047560 047780 048870 049070 049770 049830 049960 050090 050120 050130 050170
050220 050280 050340 050370 050430 050440 050460 050520 050560 050580 050640 050660 050700
050720 050760 050800 050860 050880 050930 051000 051050 051080 051140 051160 051200 051230
051250 051280 051330 051360 051390 051420 051460 051490 051520 051580 051630 051660 051700
051730 051780 051820 051860 051900 051930 051960 051990 052020 052080 052110 052130 052170
052200 052230 052260 052290 052330 052370 052400 052430 052460 052490 052520 052560 052600
052630 052680 052710 052750 052780 052820 052860 052890 052930 052960 052990 053030 053060
053100 053130 053170 053220 053250 053290 053340 053380 053420 053460 053510 053560 053600
053660 053710 053750 053800 053850 053910 053960 054040 054090 054120 054160 054200 054250
054290 054320 054360 054400 054460 054500 054540 054580 054640 054690 054730 054780 054840
054900 054960 054990 055020 055050 055080 055150 055180 055230 055280 055340 055380 055430
055470 055520 055600 055650 055710 055780 055840 055900 055950 055990 056060 056140 056170
056200 056260 056310 056380 056440 056490 056570 056620 056670 056730 056800 056870 056930
056990 057130 057180 057230 057290 057340 057390 057440 057490 057540 057590 057630 057700
057730 057800 057840 057900 057950 058010 058080 058110 058160 058200 058250 058300 058370
058430 058470 058520 058580 058640 058690 058730 058790 058850 058900 058970 059030 059080
059130 059190 059230 059280 059340 059410 059480 059520 059570 059630 059690 059730 059840
059910 059960 059990 060050 060110 060160 060220 060280 060330 060380 060440 060510 060570
060630 060710 060770 060870 060980 061040 061100 061170 061230 061290 061370 061430 061500
061570 061630 061700 061770 061850 061920 061990 062100 062180 062280 062360 062450 062550
062620 062700 062800 062870 062950 063090 063130 063200 063280 063360 063440 063530 063600
063660 063730 063800 063860 063940 064090 064140 064240 064310 064380 064450 064520 064590
064680 064760 064860 064990 065060 065130 065260 065440 065510 065620 065700 065730 065870
065960 066050 066090 066160 066290 066380 066440 066580 066680 066760 066870 066970 067090
067160 067310 067480 067600 067680 067780 067990 068270 068400 068510 068620 068710 068810
068920 069140 069260 069460 069560 069640 069790 069970
091810 091990 095340 095670 095720 095800 095870 096450 096620 096690 096760 097050 097230
097290 097390 097520 097620 097700 097870 098040 098150 098230 098450 098520 098600 098680
098760 098860 098960 099060 099130 099220 099310 099390 099500 099620 099700 099800 099870
099950 100030 100090 100170 100280 100390 100540 100660 100780 100930 101060 101180 101300
101420 101490 101540 101660 101780 101870 102000 102110 102260 102380 102490 102660 102810
102990 103120 103290 103440 103590 103710 104080 104160 104260 104360 104490 104600 104750
104860 105400 108320 108490 108670 108720 108800 108920 109080 109240 109320 109410 109540
109600 109640 109710 109840 109970 110060 110990 112190 112300 112460 112560 112630 112710
112830 112950 113050 113120 113220 113340 113460 113570 113640 113730 113820 113930 114040
114160 114280 114430 114590 114680 114800 114910 115000
247540 086520 091990 196170 041510 263750 293490 112040 357780 039030 145020 214150 066970
042700 035900 122870 058470 064760 032500 237690 031980 101490 108320 153490 155900 173940
175330 176750 179900 180400 185750 191410 192400 205500 206640 208640 214370 215600 217500
219130 220100 222810 228670 234080 236810 241560 243070 246250 248070 256840 258250 263020
263800 265520 267270 270600 272210 278280 282330 286940 293780 294870 298060 300080 301060
302430 304100 307280 314330 317400 319400 321550 322000 323280 328130 329430 330350 330590
335890 336570 336830 338100 339950 340570 343510 347700 348210 348370 357550 357580 358570
362320 363280 366330 368770 371850 372910 376300 377450 377480 382800 383310 384600 388500
389020 389260 389480 390110 390440 391030 393210 396270 399720 401020 402030 402340 403870
403930 406730 411570 412350 413640 418420 419530 421460 422220 424790 425490 425830 426550
427950 428870 429530 429710 431090 431840 433270 434480 434730 434870 435150 435760 436530
437730 438090 438170 438250 438560 441270 441790 444560 444760 445680 447270 447590 447680
452360 454910 456100 461040 463800 468610 469270 470560 473130 475560 476380 478150 480810
489730 490130 095340 095610 095700 097900 098000 098290 098370 098460 098560
"""

def _build(s, suffix, market):
    seen, out = set(), []
    for c in s.split():
        c = c.strip()
        if len(c) == 6 and c not in seen:
            seen.add(c)
            out.append((c + suffix, market))
    return out

ALL_TICKERS = _build(_KS, ".KS", "KOSPI") + _build(_KQ, ".KQ", "KOSDAQ")


# ══════════════════════════════════════════════
#  Yahoo Finance API
# ══════════════════════════════════════════════
def yahoo_chart(symbol: str, days: int = 45) -> dict | None:
    """v8 chart — 가격·거래량·시총 모두 포함"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range={days}d"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        result = r.json().get("chart", {}).get("result")
        return result[0] if result else None
    except Exception:
        return None


def parse_chart(chart: dict) -> dict | None:
    try:
        meta      = chart.get("meta", {})
        quote     = chart.get("indicators", {}).get("quote", [{}])[0]
        closes    = [c for c in (quote.get("close") or []) if c is not None]
        volumes   = [v for v in (quote.get("volume") or []) if v is not None]

        if len(closes) < 3 or len(volumes) < 2:
            return None

        today_vol = meta.get("regularMarketVolume") or volumes[-1]
        prev_vol  = volumes[-2]   # ← 전일 거래량 (차트에서 직접)
        price     = meta.get("regularMarketPrice") or closes[-1]
        mkt_cap   = meta.get("marketCap") or 0

        return {
            "price":     price,
            "today_vol": today_vol,
            "prev_vol":  prev_vol,
            "mkt_cap":   mkt_cap,
            "closes":    closes,
        }
    except Exception:
        return None


# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks() -> tuple[list[dict], str, int]:
    trade_date = datetime.now(KST).strftime("%Y%m%d")
    total      = len(ALL_TICKERS)
    log.info(f"스크리닝 시작 (KST {trade_date}) / {total}개 종목")

    results  = []
    ma_s_n   = CONFIG["ma_short"]
    ma_l_n   = CONFIG["ma_long"]
    checked  = 0

    for i, (symbol, market) in enumerate(ALL_TICKERS, 1):
        try:
            chart = yahoo_chart(symbol, days=45)
            if not chart:
                continue

            d = parse_chart(chart)
            if not d:
                continue

            checked   += 1
            price      = d["price"]
            today_vol  = d["today_vol"]
            prev_vol   = d["prev_vol"]
            mkt_cap    = d["mkt_cap"]
            closes     = d["closes"]

            # 1차 필터
            if price < CONFIG["min_price"]:           continue
            if mkt_cap < CONFIG["min_market_cap"]:    continue
            if prev_vol <= 0:                         continue

            vol_ratio = today_vol / prev_vol * 100
            if vol_ratio < CONFIG["min_vol_ratio"]:   continue
            if len(closes) < ma_l_n:                  continue

            # 이평선 정배열
            ma_s = sum(closes[-ma_s_n:]) / ma_s_n
            ma_l = sum(closes[-ma_l_n:]) / ma_l_n
            if not (price > ma_s > ma_l):
                continue

            code = symbol.replace(".KS","").replace(".KQ","")
            name = chart.get("meta", {}).get("longName") or \
                   chart.get("meta", {}).get("shortName") or code

            results.append({
                "ticker":    code,
                "name":      name,
                "market":    market,
                "close":     price,
                "volume":    today_vol,
                "prev_vol":  prev_vol,
                "vol_ratio": vol_ratio,
                "mkt_cap":   mkt_cap,
                "ma5":       round(ma_s, 0),
                "ma20":      round(ma_l, 0),
            })
            log.info(f"  ✅ {name}({code}) 거래량비율={vol_ratio:.0f}%")

        except Exception as e:
            log.debug(f"오류 {symbol}: {e}")

        if i % 100 == 0:
            log.info(f"진행 {i}/{total} / 유효 {checked} / 통과 {len(results)}")

        time.sleep(0.1)

    log.info(f"완료: {checked}/{total} 유효 → {len(results)}개 통과")
    return sorted(results, key=lambda x: x["vol_ratio"], reverse=True), trade_date, total


# ══════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════
def fmt_won(v):
    if v >= 1_0000_0000_0000: return f"{v/1_0000_0000_0000:.1f}조"
    if v >= 1_0000_0000:      return f"{v/1_0000_0000:.0f}억"
    return f"{v:,.0f}원"
def fmt_price(v): return f"{v:,.0f}원"
def escape_md(t):
    for ch in r"\_*[]()~`>#+-=|{}.!": t = t.replace(ch, f"\\{ch}")
    return t

def build_message(results, trade_date, total):
    ds = f"{trade_date[:4]}\\.{trade_date[4:6]}\\.{trade_date[6:]}"
    if not results:
        return (f"📊 *{ds} 스크리닝 결과*\n\n"
                f"🔍 조건에 맞는 종목이 없습니다\\.\n"
                f"\\(스캔 {total}종목 / 조건: 거래량 500%↑ 정배열\\)")
    lines = [f"📊 *{ds} 스크리닝 결과*",
             f"✅ *{len(results)}개 종목* 발견 \\(`{total}`개 스캔\\)\n"]
    for i, r in enumerate(results, 1):
        mkt  = "🔵" if r["market"] == "KOSPI" else "🟣"
        fire = "🔥🔥" if r["vol_ratio"] >= 1000 else "🔥" if r["vol_ratio"] >= 700 else "📈"
        vol_str = escape_md("{:,.0f}%".format(r["vol_ratio"]))
        lines.append(
            f"{i}\\. {mkt} *{escape_md(r['name'])}* `{escape_md(r['ticker'])}`\n"
            f"   💰 {escape_md(fmt_price(r['close']))}  {fire} `{vol_str}`\n"
            f"   MA5 `{escape_md(fmt_price(r['ma5']))}` \\| MA20 `{escape_md(fmt_price(r['ma20']))}`\n"
            f"   🏦 {escape_md(fmt_won(r['mkt_cap']))}"
        )
    return "\n".join(lines)

def build_buttons(results):
    if not results: return None
    rows, row = [], []
    for i, r in enumerate(results):
        row.append(InlineKeyboardButton(r["name"],
            url=f"https://m.stock.naver.com/chart/A{r['ticker']}"))
        if len(row) == 2 or i == len(results)-1:
            rows.append(row); row = []
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════════════════════
#  스크리닝 실행 (비동기)
# ══════════════════════════════════════════════
async def run_screening(context, chat_id, silent=False):
    now_kst = datetime.now(KST)
    if not silent:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🔍 *스크리닝 시작\\.\\.\\.*\n\n"
                f"KST: `{escape_md(now_kst.strftime('%Y-%m-%d %H:%M'))}`\n"
                f"총 `{len(ALL_TICKERS)}`종목 분석 중\\.\n"
                "\\(약 5\\~10분 소요\\)"
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    try:
        results, trade_date, total = await asyncio.get_event_loop().run_in_executor(
            None, screen_stocks)
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_message(results, trade_date, total),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=build_buttons(results),
        )
    except Exception as e:
        log.error(f"오류: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ *오류 발생*\n\n`{escape_md(str(e)[:600])}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ══════════════════════════════════════════════
#  /test — 삼성전자 상세 데이터 확인
# ══════════════════════════════════════════════
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔬 *테스트 중\\.\\.\\.*", parse_mode=ParseMode.MARKDOWN_V2)

    lines = [f"*차트 API 테스트* \\(내장 종목 `{len(ALL_TICKERS)}`개\\)\n"]

    for symbol, name in [("005930.KS","삼성전자"), ("247540.KQ","에코프로비엠"),
                          ("000660.KS","SK하이닉스"), ("086520.KQ","에코프로")]:
        try:
            chart = yahoo_chart(symbol, days=30)
            d = parse_chart(chart) if chart else None
            if not d:
                lines.append(f"❌ {escape_md(name)}: 데이터 없음")
                continue

            vol_ratio = d["today_vol"] / d["prev_vol"] * 100 if d["prev_vol"] else 0
            verdict   = "✅통과" if vol_ratio >= CONFIG["min_vol_ratio"] else "❌미달"
            cap_str   = fmt_won(d["mkt_cap"]) if d["mkt_cap"] else "정보없음"

            lines.append(
                f"📌 *{escape_md(name)}*\n"
                f"   가격: `{escape_md(fmt_price(d['price']))}` "
                f"시총: `{escape_md(cap_str)}`\n"
                f"   오늘: `{escape_md('{:,}'.format(d['today_vol']))}` "
                f"전일: `{escape_md('{:,}'.format(d['prev_vol']))}`\n"
                f"   거래량비율: `{escape_md('{:.0f}%'.format(vol_ratio))}` "
                f"\\({escape_md(verdict)}\\)"
            )
        except Exception as e:
            lines.append(f"❌ {escape_md(name)}: `{escape_md(str(e)[:60])}`")

    lines.append(f"\n기준: 거래량비율 `{CONFIG['min_vol_ratio']}%` 이상")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)


# ══════════════════════════════════════════════
#  커맨드 핸들러
# ══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 *주식 알림봇*에 오신 것을 환영합니다\\!\n\n"
        f"📋 *조건:*\n"
        f"  • 전일 대비 거래량 `500%` 이상\n"
        f"  • 주가 `1,000원` 이상\n"
        f"  • 시가총액 `500억` 이상\n"
        f"  • 정배열 \\(종가 \\> 5일선 \\> 20일선\\)\n\n"
        f"💬 /scan  /test  /status\n\n"
        f"📌 내 채팅 ID: `{escape_md(chat_id)}`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_screening(context, str(update.effective_chat.id))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(KST)
    wd  = ["월","화","수","목","금","토","일"][now.weekday()]
    nr  = now.replace(hour=16, minute=10, second=0, microsecond=0)
    if now >= nr or now.weekday() >= 5:
        d = 1
        while True:
            c = (now + timedelta(days=d)).replace(hour=16, minute=10)
            if c.weekday() < 5: nr = c; break
            d += 1
    diff = nr - now
    h, rem = divmod(int(diff.total_seconds()), 3600); m = rem // 60
    await update.message.reply_text(
        f"🟢 *봇 정상 작동 중*\n\n"
        f"🕐 `{escape_md(now.strftime('%Y.%m.%d %H:%M'))}` \\({wd}요일\\)\n"
        f"⏰ 다음 자동: `{escape_md(nr.strftime('%m/%d %H:%M'))}` "
        f"\\({h}시간 {m}분 후\\)\n"
        f"📡 Yahoo Finance v8 chart \\| `{len(ALL_TICKERS)}`종목",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now(KST).weekday() >= 5: return
    log.info("자동 스캔 시작")
    await run_screening(context, TELEGRAM_CHAT_ID, silent=True)


# ══════════════════════════════════════════════
#  헬스체크 + 메인
# ══════════════════════════════════════════════
def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        def log_message(self, *a): pass
    threading.Thread(
        target=HTTPServer(("0.0.0.0", port), Handler).serve_forever,
        daemon=True).start()
    log.info(f"헬스체크 서버: 포트 {port}")

def main():
    if not TELEGRAM_TOKEN:   print("❌ TELEGRAM_TOKEN 없음"); sys.exit(1)
    if not TELEGRAM_CHAT_ID: print("❌ TELEGRAM_CHAT_ID 없음"); sys.exit(1)

    async def run():
        start_health_server()
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start",  cmd_start))
        app.add_handler(CommandHandler("scan",   cmd_scan))
        app.add_handler(CommandHandler("test",   cmd_test))
        app.add_handler(CommandHandler("status", cmd_status))
        app.job_queue.run_daily(
            scheduled_scan,
            time=datetime.strptime("16:10", "%H:%M").time(),
            name="daily_scan",
        )
        log.info("봇 시작")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        log.info("✅ 폴링 시작")
        import signal
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
        await app.updater.stop(); await app.stop(); await app.shutdown()

    asyncio.run(run())

if __name__ == "__main__":
    main()
