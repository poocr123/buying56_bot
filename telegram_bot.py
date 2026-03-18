#!/usr/bin/env python3
"""
📱 주식 알림봇 – Yahoo Finance v8 Chart API 기반
종목 리스트: 내장 (KOSPI/KOSDAQ 주요 500종목)
데이터: Yahoo Finance v8 (해외서버 접근 가능 확인됨)
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
    "Accept":     "application/json, text/plain, */*",
}

# ══════════════════════════════════════════════
#  내장 종목 리스트 (KOSPI .KS / KOSDAQ .KQ)
#  시가총액 500억 이상 주요 종목
# ══════════════════════════════════════════════
KR_TICKERS = [
    # ── KOSPI 대형주 ──────────────────────────
    ("005930.KS","삼성전자","KOSPI"),    ("000660.KS","SK하이닉스","KOSPI"),
    ("373220.KS","LG에너지솔루션","KOSPI"), ("207940.KS","삼성바이오로직스","KOSPI"),
    ("005380.KS","현대차","KOSPI"),       ("000270.KS","기아","KOSPI"),
    ("068270.KS","셀트리온","KOSPI"),     ("105560.KS","KB금융","KOSPI"),
    ("055550.KS","신한지주","KOSPI"),     ("012330.KS","현대모비스","KOSPI"),
    ("035420.KS","NAVER","KOSPI"),        ("051910.KS","LG화학","KOSPI"),
    ("035720.KS","카카오","KOSPI"),       ("003550.KS","LG","KOSPI"),
    ("032830.KS","삼성생명","KOSPI"),     ("086790.KS","하나금융지주","KOSPI"),
    ("028260.KS","삼성물산","KOSPI"),     ("066570.KS","LG전자","KOSPI"),
    ("017670.KS","SK텔레콤","KOSPI"),     ("009150.KS","삼성전기","KOSPI"),
    ("034730.KS","SK","KOSPI"),           ("018260.KS","삼성SDS","KOSPI"),
    ("011200.KS","HMM","KOSPI"),          ("096770.KS","SK이노베이션","KOSPI"),
    ("030200.KS","KT","KOSPI"),           ("316140.KS","우리금융지주","KOSPI"),
    ("003490.KS","대한항공","KOSPI"),     ("010950.KS","S-Oil","KOSPI"),
    ("047050.KS","포스코인터내셔널","KOSPI"), ("000810.KS","삼성화재","KOSPI"),
    ("139480.KS","이마트","KOSPI"),       ("361610.KS","SK아이이테크놀로지","KOSPI"),
    ("097950.KS","CJ제일제당","KOSPI"),   ("024110.KS","기업은행","KOSPI"),
    ("010130.KS","고려아연","KOSPI"),     ("271560.KS","오리온","KOSPI"),
    ("004020.KS","현대제철","KOSPI"),     ("033780.KS","KT&G","KOSPI"),
    ("009830.KS","한화솔루션","KOSPI"),   ("042660.KS","한화오션","KOSPI"),
    ("007070.KS","GS리테일","KOSPI"),     ("011070.KS","LG이노텍","KOSPI"),
    ("003670.KS","포스코퓨처엠","KOSPI"), ("000120.KS","CJ대한통운","KOSPI"),
    ("021240.KS","코웨이","KOSPI"),       ("329180.KS","HD현대중공업","KOSPI"),
    ("010140.KS","삼성중공업","KOSPI"),   ("047810.KS","한국항공우주","KOSPI"),
    ("161390.KS","한국타이어앤테크놀로지","KOSPI"), ("002790.KS","아모레퍼시픽그룹","KOSPI"),
    ("006800.KS","미래에셋증권","KOSPI"), ("000100.KS","유한양행","KOSPI"),
    ("036570.KS","엔씨소프트","KOSPI"),   ("251270.KS","넷마블","KOSPI"),
    ("180640.KS","한진칼","KOSPI"),       ("267250.KS","HD현대","KOSPI"),
    ("086280.KS","현대글로비스","KOSPI"), ("078930.KS","GS","KOSPI"),
    ("005490.KS","POSCO홀딩스","KOSPI"),  ("000720.KS","현대건설","KOSPI"),
    ("002380.KS","KCC","KOSPI"),          ("008770.KS","호텔신라","KOSPI"),
    ("009240.KS","한샘","KOSPI"),         ("018880.KS","한온시스템","KOSPI"),
    ("006360.KS","GS건설","KOSPI"),       ("090430.KS","아모레퍼시픽","KOSPI"),
    ("016360.KS","삼성증권","KOSPI"),     ("034020.KS","두산에너빌리티","KOSPI"),
    ("015760.KS","한국전력","KOSPI"),     ("036460.KS","한국가스공사","KOSPI"),
    ("071050.KS","한국금융지주","KOSPI"), ("032640.KS","LG유플러스","KOSPI"),
    ("011790.KS","SKC","KOSPI"),          ("004990.KS","롯데지주","KOSPI"),
    ("023530.KS","롯데쇼핑","KOSPI"),     ("011780.KS","금호석유","KOSPI"),
    ("000150.KS","두산","KOSPI"),         ("005830.KS","DB손해보험","KOSPI"),
    ("020150.KS","롯데에너지머티리얼즈","KOSPI"), ("019170.KS","신풍제약","KOSPI"),
    ("003230.KS","삼양식품","KOSPI"),     ("005300.KS","롯데칠성","KOSPI"),
    ("007310.KS","오뚜기","KOSPI"),       ("000080.KS","하이트진로","KOSPI"),
    ("302440.KS","SK바이오사이언스","KOSPI"), ("241560.KS","두산밥캣","KOSPI"),
    ("003410.KS","쌍용C&E","KOSPI"),      ("014680.KS","한화생명","KOSPI"),
    ("326030.KS","SK바이오팜","KOSPI"),   ("175330.KS","JB금융지주","KOSPI"),
    ("138040.KS","메리츠금융지주","KOSPI"), ("100840.KS","SNT모티브","KOSPI"),
    ("010620.KS","HD현대미포","KOSPI"),   ("012450.KS","한화에어로스페이스","KOSPI"),
    ("000990.KS","DB하이텍","KOSPI"),     ("009420.KS","한올바이오파마","KOSPI"),
    ("006400.KS","삼성SDI","KOSPI"),      ("028050.KS","삼성엔지니어링","KOSPI"),
    # ── KOSDAQ 주요주 ─────────────────────────
    ("247540.KQ","에코프로비엠","KOSDAQ"), ("086520.KQ","에코프로","KOSDAQ"),
    ("091990.KQ","셀트리온헬스케어","KOSDAQ"), ("196170.KQ","알테오젠","KOSDAQ"),
    ("041510.KQ","에스엠","KOSDAQ"),       ("263750.KQ","펄어비스","KOSDAQ"),
    ("293490.KQ","카카오게임즈","KOSDAQ"), ("112040.KQ","위메이드","KOSDAQ"),
    ("357780.KQ","솔브레인","KOSDAQ"),     ("039030.KQ","이오테크닉스","KOSDAQ"),
    ("145020.KQ","휴젤","KOSDAQ"),         ("214150.KQ","클래시스","KOSDAQ"),
    ("036030.KQ","다원시스","KOSDAQ"),     ("066970.KQ","엘앤에프","KOSDAQ"),
    ("095340.KQ","ISC","KOSDAQ"),          ("017800.KQ","현인텔리전스","KOSDAQ"),
    ("035900.KQ","JYP Ent.","KOSDAQ"),     ("122870.KQ","와이지엔터테인먼트","KOSDAQ"),
    ("041960.KQ","블리자드","KOSDAQ"),     ("054040.KQ","한국팩키지","KOSDAQ"),
    ("240810.KQ","원익IPS","KOSDAQ"),      ("131970.KQ","두산테스나","KOSDAQ"),
    ("950130.KQ","엑세스바이오","KOSDAQ"), ("141080.KQ","레고켐바이오","KOSDAQ"),
    ("299900.KQ","스튜디오드래곤","KOSDAQ"), ("067160.KQ","아프리카TV","KOSDAQ"),
    ("236850.KQ","에이피알","KOSDAQ"),     ("039200.KQ","오스코텍","KOSDAQ"),
    ("057050.KQ","현대홈쇼핑","KOSDAQ"),   ("080160.KQ","모비스","KOSDAQ"),
    ("078600.KQ","대주전자재료","KOSDAQ"), ("058470.KQ","리노공업","KOSDAQ"),
    ("064760.KQ","티씨케이","KOSDAQ"),     ("042700.KQ","한미반도체","KOSDAQ"),
    ("032500.KQ","케이엠더블유","KOSDAQ"), ("036810.KQ","에프에스티","KOSDAQ"),
    ("065350.KQ","신성델타테크","KOSDAQ"), ("089030.KQ","테크윙","KOSDAQ"),
    ("025980.KQ","알파홀딩스","KOSDAQ"),   ("083660.KQ","CSA코스믹","KOSDAQ"),
    ("237690.KQ","에스티팜","KOSDAQ"),     ("900140.KQ","일진하이솔루스","KOSDAQ"),
    ("031980.KQ","피에스케이","KOSDAQ"),   ("101490.KQ","에스앤에스텍","KOSDAQ"),
    ("211050.KQ","인카금융서비스","KOSDAQ"), ("060310.KQ","3S","KOSDAQ"),
    ("900250.KQ","크리스탈지노믹스","KOSDAQ"), ("950160.KQ","코오롱티슈진","KOSDAQ"),
    ("108320.KQ","LX세미콘","KOSDAQ"),     ("119850.KQ","지엔씨에너지","KOSDAQ"),
    ("054450.KQ","텔레칩스","KOSDAQ"),     ("083450.KQ","GST","KOSDAQ"),
]


# ══════════════════════════════════════════════
#  Yahoo Finance v8 Chart API
# ══════════════════════════════════════════════
def yahoo_chart(symbol: str, days: int = 30) -> dict | None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range={days}d"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        result = r.json().get("chart", {}).get("result")
        return result[0] if result else None
    except Exception as e:
        log.debug(f"chart 실패 {symbol}: {e}")
        return None


def parse_chart(chart: dict) -> dict | None:
    """차트에서 현재가/거래량/시총/종가시리즈 추출"""
    try:
        meta   = chart.get("meta", {})
        quote  = chart.get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        vols   = [v for v in (quote.get("volume") or []) if v is not None]

        if len(closes) < 2:
            return None

        return {
            "close":      meta.get("regularMarketPrice") or closes[-1],
            "volume":     meta.get("regularMarketVolume") or (vols[-1] if vols else 0),
            "prev_vol":   vols[-2] if len(vols) >= 2 else 0,
            "market_cap": meta.get("marketCap") or 0,
            "closes":     closes,
        }
    except Exception:
        return None


# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks() -> tuple[list[dict], str]:
    trade_date = datetime.now(KST).strftime("%Y%m%d")
    log.info(f"스크리닝 시작 (KST: {trade_date}) / 총 {len(KR_TICKERS)}종목")

    results = []
    ma_s_n  = CONFIG["ma_short"]
    ma_l_n  = CONFIG["ma_long"]

    for i, (symbol, name, market) in enumerate(KR_TICKERS, 1):
        try:
            chart = yahoo_chart(symbol, days=40)
            if chart is None:
                continue

            d = parse_chart(chart)
            if d is None:
                continue

            close      = d["close"]
            volume     = d["volume"]
            prev_vol   = d["prev_vol"]
            market_cap = d["market_cap"]
            closes     = d["closes"]

            # 필터
            if close < CONFIG["min_price"]:         continue
            if market_cap < CONFIG["min_market_cap"]: continue
            if prev_vol <= 0:                       continue

            vol_ratio = volume / prev_vol * 100
            if vol_ratio < CONFIG["min_vol_ratio"]: continue

            # 이평선 정배열
            if len(closes) < ma_l_n:
                continue
            ma_s = sum(closes[-ma_s_n:]) / ma_s_n
            ma_l = sum(closes[-ma_l_n:]) / ma_l_n

            if not (close > ma_s > ma_l):
                continue

            code = symbol.replace(".KS", "").replace(".KQ", "")
            results.append({
                "ticker":    code,
                "name":      name,
                "market":    market,
                "close":     close,
                "volume":    volume,
                "prev_vol":  prev_vol,
                "vol_ratio": vol_ratio,
                "market_cap":market_cap,
                "ma5":       round(ma_s, 0),
                "ma20":      round(ma_l, 0),
            })
            log.info(f"  ✅ {name}({code}) 거래량비율={vol_ratio:.0f}%")

        except Exception as e:
            log.debug(f"오류 {symbol}: {e}")

        if i % 50 == 0:
            log.info(f"진행: {i}/{len(KR_TICKERS)}")
        time.sleep(0.1)

    log.info(f"스크리닝 완료 → {len(results)}개 종목")
    return sorted(results, key=lambda x: x["vol_ratio"], reverse=True), trade_date


# ══════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════
def fmt_won(v):
    if v >= 1_0000_0000_0000: return f"{v/1_0000_0000_0000:.1f}조"
    if v >= 1_0000_0000:      return f"{v/1_0000_0000:.0f}억"
    return f"{v:,.0f}원"

def fmt_price(v): return f"{v:,.0f}원"

def escape_md(text):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def build_message(results, trade_date):
    ds = f"{trade_date[:4]}\\.{trade_date[4:6]}\\.{trade_date[6:]}"
    if not results:
        return f"📊 *{ds} 스크리닝 결과*\n\n🔍 조건에 맞는 종목이 없습니다\\."
    lines = [f"📊 *{ds} 스크리닝 결과*", f"✅ *{len(results)}개 종목* 발견\\!\n"]
    for i, r in enumerate(results, 1):
        mkt     = "🔵" if r["market"] == "KOSPI" else "🟣"
        fire    = "🔥🔥" if r["vol_ratio"] >= 1000 else "🔥" if r["vol_ratio"] >= 700 else "📈"
        lines.append(
            f"{i}\\. {mkt} *{escape_md(r['name'])}* `{escape_md(r['ticker'])}`\n"
            f"   💰 {escape_md(fmt_price(r['close']))}  {fire} "
            f"`{escape_md('{:,.0f}%'.format(r['vol_ratio']))}`\n"
            f"   MA5 `{escape_md(fmt_price(r['ma5']))}` \\| "
            f"MA20 `{escape_md(fmt_price(r['ma20']))}`\n"
            f"   🏦 {escape_md(fmt_won(r['market_cap']))}"
        )
    return "\n".join(lines)

def build_buttons(results):
    if not results:
        return None
    rows, row = [], []
    for i, r in enumerate(results):
        row.append(InlineKeyboardButton(
            r["name"], url=f"https://m.stock.naver.com/chart/A{r['ticker']}"
        ))
        if len(row) == 2 or i == len(results) - 1:
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
                f"총 `{len(KR_TICKERS)}`종목 Yahoo Finance 분석 중\\.\n"
                "\\(약 3\\~5분 소요\\)"
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    try:
        results, trade_date = await asyncio.get_event_loop().run_in_executor(
            None, screen_stocks
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=build_message(results, trade_date),
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
#  /test
# ══════════════════════════════════════════════
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔬 테스트 중\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    lines = ["*Yahoo Finance v8 테스트*\n"]

    for symbol, name in [("005930.KS", "삼성전자"), ("247540.KQ", "에코프로비엠")]:
        try:
            chart = yahoo_chart(symbol, days=10)
            d = parse_chart(chart) if chart else None
            if d:
                vr = d["volume"] / d["prev_vol"] * 100 if d["prev_vol"] else 0
                lines.append(
                    f"✅ {escape_md(name)}: "
                    f"`{escape_md(fmt_price(d['close']))}` "
                    f"거래량비율 `{escape_md('{:.0f}%'.format(vr))}`"
                )
            else:
                lines.append(f"⚠️ {escape_md(name)}: 데이터 파싱 실패")
        except Exception as e:
            lines.append(f"❌ {escape_md(name)}: `{escape_md(str(e)[:80])}`")

    lines.append(f"\n총 내장 종목수: `{len(KR_TICKERS)}`개")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2
    )


# ══════════════════════════════════════════════
#  커맨드 핸들러
# ══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 *주식 알림봇*에 오신 것을 환영합니다\\!\n\n"
        f"📋 *스크리닝 조건:*\n"
        f"  • 전일 대비 거래량 `500%` 이상\n"
        f"  • 주가 `1,000원` 이상\n"
        f"  • 시가총액 `500억` 이상\n"
        f"  • 정배열 \\(종가 \\> 5일선 \\> 20일선\\)\n\n"
        f"💬 *명령어:*  /scan  /test  /status\n\n"
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
        f"🕐 현재: `{escape_md(now.strftime('%Y.%m.%d %H:%M'))}` \\({wd}요일\\)\n"
        f"⏰ 다음 자동 실행: `{escape_md(nr.strftime('%m/%d %H:%M'))}` "
        f"\\({h}시간 {m}분 후\\)\n\n"
        f"📡 Yahoo Finance v8 \\| 내장 종목 `{len(KR_TICKERS)}`개",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now(KST).weekday() >= 5:
        return
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
        daemon=True
    ).start()
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
        log.info("봇 시작 (폴링 모드)")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        log.info("✅ 폴링 시작 완료")
        import signal
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    asyncio.run(run())

if __name__ == "__main__":
    main()
