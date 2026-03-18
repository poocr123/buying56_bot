#!/usr/bin/env python3
"""
📱 주식 알림봇 – 전종목 스캔
종목 리스트: GitHub FinanceData/marcap (매일 업데이트 전체 KRX)
데이터:      Yahoo Finance v8 Chart API
"""

import asyncio, logging, os, sys, time, threading, csv, io
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
    "min_market_cap": 50_000_000_000,   # 500억
    "min_vol_ratio":  500,               # 전일 대비 500%
    "ma_short":       5,
    "ma_long":        20,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
}


# ══════════════════════════════════════════════
#  전종목 리스트 — GitHub FinanceData/marcap
#  https://github.com/FinanceData/marcap
#  컬럼: Date,Code,Name,Market,Shares,MarketCap,...
# ══════════════════════════════════════════════
def fetch_all_tickers() -> list[tuple[str, str, str]]:
    """marcap 연도별 CSV에서 최근 거래일 전종목 반환
    파일 구조: data/2026.csv (연도별 파일, Date 컬럼으로 날짜 구분)
    """
    now_kst = datetime.now(KST)
    year    = now_kst.strftime("%Y")
    url     = f"https://raw.githubusercontent.com/FinanceData/marcap/master/data/{year}.csv"

    try:
        log.info(f"marcap {year}.csv 다운로드 중...")
        r = requests.get(url, timeout=60, stream=True)
        if r.status_code != 200:
            log.warning(f"marcap {year}.csv: HTTP {r.status_code}")
            raise ValueError(f"HTTP {r.status_code}")

        # 스트림으로 읽어서 최근 날짜 종목만 추출
        lines = []
        for chunk in r.iter_lines(decode_unicode=True):
            if chunk:
                lines.append(chunk)

        reader   = csv.DictReader(iter(lines))
        all_rows = list(reader)

        if not all_rows:
            raise ValueError("CSV 데이터 없음")

        # 가장 최근 거래일 찾기
        dates = sorted(set(row.get("Date", "")[:10] for row in all_rows if row.get("Date")), reverse=True)
        latest_date = dates[0] if dates else ""
        log.info(f"marcap 최근 거래일: {latest_date} / 전체 행수: {len(all_rows)}")

        tickers = []
        for row in all_rows:
            if row.get("Date", "")[:10] != latest_date:
                continue
            code   = row.get("Code", "").strip()
            name   = row.get("Name", "").strip()
            market = row.get("Market", "KOSPI").strip()
            if not code or len(code) != 6:
                continue
            suffix = ".KS" if market == "KOSPI" else ".KQ"
            tickers.append((code + suffix, name, market))

        if tickers:
            log.info(f"marcap {latest_date}: {len(tickers)}개 종목 로드 완료")
            return tickers

    except Exception as e:
        log.warning(f"marcap CSV 실패: {e}, 내장 리스트 사용")

    return FALLBACK_TICKERS


# ── 폴백 리스트 (GitHub 접근 실패 시) ──────────
FALLBACK_TICKERS = [
    ("005930.KS","삼성전자","KOSPI"),    ("000660.KS","SK하이닉스","KOSPI"),
    ("373220.KS","LG에너지솔루션","KOSPI"), ("207940.KS","삼성바이오로직스","KOSPI"),
    ("005380.KS","현대차","KOSPI"),       ("000270.KS","기아","KOSPI"),
    ("068270.KS","셀트리온","KOSPI"),     ("105560.KS","KB금융","KOSPI"),
    ("055550.KS","신한지주","KOSPI"),     ("035420.KS","NAVER","KOSPI"),
    ("051910.KS","LG화학","KOSPI"),       ("035720.KS","카카오","KOSPI"),
    ("006400.KS","삼성SDI","KOSPI"),      ("005490.KS","POSCO홀딩스","KOSPI"),
    ("012330.KS","현대모비스","KOSPI"),   ("066570.KS","LG전자","KOSPI"),
    ("003550.KS","LG","KOSPI"),           ("086790.KS","하나금융지주","KOSPI"),
    ("028260.KS","삼성물산","KOSPI"),     ("017670.KS","SK텔레콤","KOSPI"),
    ("034730.KS","SK","KOSPI"),           ("096770.KS","SK이노베이션","KOSPI"),
    ("030200.KS","KT","KOSPI"),           ("316140.KS","우리금융지주","KOSPI"),
    ("003490.KS","대한항공","KOSPI"),     ("010950.KS","S-Oil","KOSPI"),
    ("000810.KS","삼성화재","KOSPI"),     ("009150.KS","삼성전기","KOSPI"),
    ("018260.KS","삼성SDS","KOSPI"),      ("011200.KS","HMM","KOSPI"),
    ("015760.KS","한국전력","KOSPI"),     ("012450.KS","한화에어로스페이스","KOSPI"),
    ("329180.KS","HD현대중공업","KOSPI"), ("010140.KS","삼성중공업","KOSPI"),
    ("034020.KS","두산에너빌리티","KOSPI"), ("042660.KS","한화오션","KOSPI"),
    ("138040.KS","메리츠금융지주","KOSPI"), ("267250.KS","HD현대","KOSPI"),
    ("247540.KQ","에코프로비엠","KOSDAQ"), ("086520.KQ","에코프로","KOSDAQ"),
    ("091990.KQ","셀트리온헬스케어","KOSDAQ"), ("196170.KQ","알테오젠","KOSDAQ"),
    ("041510.KQ","에스엠","KOSDAQ"),       ("263750.KQ","펄어비스","KOSDAQ"),
    ("293490.KQ","카카오게임즈","KOSDAQ"), ("066970.KQ","엘앤에프","KOSDAQ"),
    ("042700.KQ","한미반도체","KOSDAQ"),  ("108320.KQ","LX세미콘","KOSDAQ"),
    ("035900.KQ","JYP Ent.","KOSDAQ"),    ("058470.KQ","리노공업","KOSDAQ"),
]


# ══════════════════════════════════════════════
#  Yahoo Finance v8 Chart
# ══════════════════════════════════════════════
def yahoo_chart(symbol: str, days: int = 30) -> dict | None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range={days}d"
    )
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
        meta   = chart.get("meta", {})
        quote  = chart.get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        vols   = [v for v in (quote.get("volume") or []) if v is not None]
        if len(closes) < 2 or len(vols) < 2:
            return None
        return {
            "close":      meta.get("regularMarketPrice") or closes[-1],
            "volume":     meta.get("regularMarketVolume") or vols[-1],
            "prev_vol":   vols[-2],
            "market_cap": meta.get("marketCap") or 0,
            "closes":     closes,
        }
    except Exception:
        return None


# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks() -> tuple[list[dict], str, int]:
    trade_date = datetime.now(KST).strftime("%Y%m%d")

    tickers = fetch_all_tickers()
    total   = len(tickers)
    log.info(f"스크리닝 시작: {total}개 종목 (KST {trade_date})")

    results  = []
    ma_s_n   = CONFIG["ma_short"]
    ma_l_n   = CONFIG["ma_long"]
    checked  = 0

    for i, (symbol, name, market) in enumerate(tickers, 1):
        try:
            chart = yahoo_chart(symbol, days=40)
            if not chart:
                continue

            d = parse_chart(chart)
            if not d:
                continue

            checked += 1
            close      = d["close"]
            volume     = d["volume"]
            prev_vol   = d["prev_vol"]
            market_cap = d["market_cap"]
            closes     = d["closes"]

            if close < CONFIG["min_price"]:           continue
            if market_cap < CONFIG["min_market_cap"]: continue
            if prev_vol <= 0:                         continue

            vol_ratio = volume / prev_vol * 100
            if vol_ratio < CONFIG["min_vol_ratio"]:   continue
            if len(closes) < ma_l_n:                  continue

            ma_s = sum(closes[-ma_s_n:]) / ma_s_n
            ma_l = sum(closes[-ma_l_n:]) / ma_l_n
            if not (close > ma_s > ma_l):
                continue

            code = symbol.replace(".KS", "").replace(".KQ", "")
            results.append({
                "ticker":     code,
                "name":       name,
                "market":     market,
                "close":      close,
                "volume":     volume,
                "prev_vol":   prev_vol,
                "vol_ratio":  vol_ratio,
                "market_cap": market_cap,
                "ma5":        round(ma_s, 0),
                "ma20":       round(ma_l, 0),
            })
            log.info(f"  ✅ {name}({code}) {vol_ratio:.0f}%")

        except Exception as e:
            log.debug(f"오류 {symbol}: {e}")

        if i % 100 == 0:
            log.info(f"진행 {i}/{total} (유효데이터 {checked}개, 통과 {len(results)}개)")

        time.sleep(0.08)

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

def escape_md(text):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text

def build_message(results, trade_date, total):
    ds = f"{trade_date[:4]}\\.{trade_date[4:6]}\\.{trade_date[6:]}"
    if not results:
        return (
            f"📊 *{ds} 스크리닝 결과*\n\n"
            f"🔍 조건에 맞는 종목이 없습니다\\.\n"
            f"\\(스캔: `{total}`개 종목\\)"
        )
    lines = [
        f"📊 *{ds} 스크리닝 결과*",
        f"✅ *{len(results)}개 종목* 발견 \\(전체 `{total}`개 스캔\\)\n"
    ]
    for i, r in enumerate(results, 1):
        mkt  = "🔵" if r["market"] == "KOSPI" else "🟣"
        fire = "🔥🔥" if r["vol_ratio"] >= 1000 else "🔥" if r["vol_ratio"] >= 700 else "📈"
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
                "전종목 \\(KOSPI\\+KOSDAQ 약 2,500개\\) 분석 중\\.\n"
                "\\(약 5\\~10분 소요\\)"
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    try:
        results, trade_date, total = await asyncio.get_event_loop().run_in_executor(
            None, screen_stocks
        )
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
#  /test
# ══════════════════════════════════════════════
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔬 테스트 중\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
    lines = ["*테스트 결과*\n"]

    # 1. GitHub 종목 리스트
    try:
        tickers = fetch_all_tickers()
        src = "GitHub marcap" if len(tickers) > 100 else "내장 폴백"
        lines.append(f"✅ 종목 리스트: `{len(tickers)}`개 \\({escape_md(src)}\\)")
    except Exception as e:
        lines.append(f"❌ 종목 리스트: `{escape_md(str(e)[:60])}`")

    # 2. Yahoo v8 Chart
    for symbol, name in [("005930.KS", "삼성전자"), ("247540.KQ", "에코프로비엠")]:
        try:
            chart = yahoo_chart(symbol, days=10)
            d = parse_chart(chart) if chart else None
            if d:
                vr = d["volume"] / d["prev_vol"] * 100 if d["prev_vol"] else 0
                lines.append(
                    f"✅ {escape_md(name)}: "
                    f"`{escape_md(fmt_price(d['close']))}` "
                    f"거래량비율 `{vr:.0f}%`"
                )
            else:
                lines.append(f"⚠️ {escape_md(name)}: 데이터 파싱 실패")
        except Exception as e:
            lines.append(f"❌ {escape_md(name)}: `{escape_md(str(e)[:60])}`")

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
        f"📡 Yahoo Finance v8 \\| GitHub marcap 전종목",
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
