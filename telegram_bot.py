#!/usr/bin/env python3
"""
📱 주식 알림봇 – Yahoo Finance + 네이버 기반
"""

import asyncio
import logging
import os
import sys
import time
import threading
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
    "Accept":     "application/json",
}

# ══════════════════════════════════════════════
#  Yahoo Finance API
# ══════════════════════════════════════════════
def yahoo_screener(exchange: str, offset: int = 0, size: int = 250) -> list[dict]:
    """Yahoo Finance Screener로 한국 주식 목록 조회
    exchange: KSC (KOSPI), KSQ (KOSDAQ)
    """
    url = "https://query1.finance.yahoo.com/v1/finance/screener"
    payload = {
        "offset": offset,
        "size": size,
        "sortField": "dayvolume",
        "sortType": "DESC",
        "quoteType": "EQUITY",
        "query": {
            "operator": "and",
            "operands": [
                {"operator": "eq", "operands": ["exchange", exchange]},
            ]
        },
        "userId": "",
        "userIdType": "guid",
    }
    r = requests.post(url, json=payload, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("finance", {}).get("result", [{}])[0].get("quotes", [])


def yahoo_chart(ticker: str, days: int = 30) -> dict:
    """Yahoo Finance 일봉 차트 (종가, 거래량)"""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1d&range={days}d"
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get("chart", {}).get("result", [{}])[0]


def get_all_kr_stocks() -> list[dict]:
    """KOSPI + KOSDAQ 전종목 가져오기"""
    results = []
    for exchange, market in [("KSC", "KOSPI"), ("KSQ", "KOSDAQ")]:
        offset = 0
        while True:
            try:
                quotes = yahoo_screener(exchange, offset=offset, size=250)
                if not quotes:
                    break
                for q in quotes:
                    results.append({**q, "market": market})
                log.info(f"[{market}] offset={offset} → {len(quotes)}개")
                if len(quotes) < 250:
                    break
                offset += 250
                time.sleep(0.3)
            except Exception as e:
                log.warning(f"[{market}] offset={offset} 실패: {e}")
                break
    return results


# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks() -> tuple[list[dict], str]:
    trade_date = datetime.now(KST).strftime("%Y%m%d")
    log.info(f"스크리닝 시작 (KST: {trade_date})")

    all_stocks = get_all_kr_stocks()
    if not all_stocks:
        raise RuntimeError("Yahoo Finance에서 종목 데이터를 가져올 수 없습니다.")
    log.info(f"전체 {len(all_stocks)}개 종목 로드")

    results = []
    ma_s_n = CONFIG["ma_short"]
    ma_l_n = CONFIG["ma_long"]

    for q in all_stocks:
        try:
            ticker      = q.get("symbol", "")
            name        = q.get("longName") or q.get("shortName") or ticker
            close       = float(q.get("regularMarketPrice", 0) or 0)
            volume      = int(q.get("regularMarketVolume", 0) or 0)
            prev_volume = int(q.get("averageDailyVolume3Month", 0) or 0)  # 3개월 평균
            market_cap  = float(q.get("marketCap", 0) or 0)
            market      = q.get("market", "KOSPI")

            # 1차 필터
            if close < CONFIG["min_price"]:         continue
            if market_cap < CONFIG["min_market_cap"]: continue
            if prev_volume <= 0:                    continue

            vol_ratio = volume / prev_volume * 100
            if vol_ratio < CONFIG["min_vol_ratio"]: continue

            # 이동평균 정배열 — Yahoo 일봉 차트
            chart = yahoo_chart(ticker, days=40)
            closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]

            if len(closes) < ma_l_n:
                continue

            import statistics
            ma_s = sum(closes[-ma_s_n:]) / ma_s_n
            ma_l = sum(closes[-ma_l_n:]) / ma_l_n

            if not (close > ma_s > ma_l):
                continue

            # 종목코드 정리 (005930.KS → 005930)
            code = ticker.replace(".KS", "").replace(".KQ", "")

            results.append({
                "ticker":      code,
                "name":        name,
                "market":      market,
                "close":       close,
                "volume":      volume,
                "prev_volume": prev_volume,
                "vol_ratio":   vol_ratio,
                "market_cap":  market_cap,
                "ma5":         round(ma_s, 0),
                "ma20":        round(ma_l, 0),
            })
            log.info(f"  ✅ {name}({code}) 거래량비율={vol_ratio:.0f}%")

        except Exception as e:
            log.debug(f"종목 처리 오류 {q.get('symbol','')}: {e}")
            continue

        time.sleep(0.05)

    log.info(f"최종 {len(results)}개 종목")
    return sorted(results, key=lambda x: x["vol_ratio"], reverse=True), trade_date


# ══════════════════════════════════════════════
#  유틸리티 & 메시지
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
        name    = escape_md(r["name"])
        ticker  = escape_md(r["ticker"])
        price   = escape_md(fmt_price(r["close"]))
        vol_str = escape_md("{:,.0f}%".format(r["vol_ratio"]))
        ma5     = escape_md(fmt_price(r["ma5"]))
        ma20    = escape_md(fmt_price(r["ma20"]))
        cap     = escape_md(fmt_won(r["market_cap"]))
        lines.append(
            f"{i}\\. {mkt} *{name}* `{ticker}`\n"
            f"   💰 {price}  {fire} `{vol_str}`\n"
            f"   MA5 `{ma5}` \\| MA20 `{ma20}`\n"
            f"   🏦 {cap}"
        )
    return "\n".join(lines)

def build_buttons(results):
    if not results:
        return None
    rows, row = [], []
    for i, r in enumerate(results):
        row.append(InlineKeyboardButton(
            r["name"],
            url=f"https://m.stock.naver.com/chart/A{r['ticker']}"
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
                "Yahoo Finance 데이터 분석 중\\.\n"
                "\\(약 10\\~20분 소요\\)"
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
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("🔬 Yahoo Finance 테스트 중\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    lines = ["*Yahoo Finance 테스트*\n"]

    # 1. Screener
    try:
        quotes = yahoo_screener("KSC", size=5)
        sample = quotes[0].get("shortName", "?") if quotes else "없음"
        lines.append(f"✅ KOSPI Screener: `{len(quotes)}개` \\(예: {escape_md(sample)}\\)")
    except Exception as e:
        lines.append(f"❌ KOSPI Screener: `{escape_md(str(e)[:80])}`")

    # 2. KOSDAQ Screener
    try:
        quotes = yahoo_screener("KSQ", size=5)
        lines.append(f"✅ KOSDAQ Screener: `{len(quotes)}개`")
    except Exception as e:
        lines.append(f"❌ KOSDAQ Screener: `{escape_md(str(e)[:80])}`")

    # 3. 차트
    try:
        chart = yahoo_chart("005930.KS", days=10)
        closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        lines.append(f"✅ 삼성전자 일봉: `{len(closes)}일` 최근가 `{closes[-1]:,.0f}원`")
    except Exception as e:
        lines.append(f"❌ 삼성전자 차트: `{escape_md(str(e)[:80])}`")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ══════════════════════════════════════════════
#  커맨드 핸들러
# ══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 *주식 알림봇*에 오신 것을 환영합니다\\!\n\n"
        f"📋 *스크리닝 조건:*\n"
        f"  • 거래량 3개월 평균 대비 `500%` 이상\n"
        f"  • 주가 `1,000원` 이상\n"
        f"  • 시가총액 `500억` 이상\n"
        f"  • 정배열 \\(종가 \\> 5일선 \\> 20일선\\)\n\n"
        f"💬 *명령어:*\n"
        f"  /scan — 즉시 스크리닝\n"
        f"  /test — API 연결 테스트\n"
        f"  /status — 봇 상태\n\n"
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
        f"⏰ 다음 자동 실행: `{escape_md(nr.strftime('%m/%d %H:%M'))}` \\({h}시간 {m}분 후\\)\n\n"
        f"📡 데이터 소스: Yahoo Finance",
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
    if not TELEGRAM_TOKEN:  print("❌ TELEGRAM_TOKEN 없음"); sys.exit(1)
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
