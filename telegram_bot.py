#!/usr/bin/env python3
"""
📱 주식 알림봇 – 텔레그램 봇 (네이버 증권 API 기반)
pykrx/KRX 완전 제거 → 해외 서버에서도 동작
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

import pandas as pd
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# ─── 환경변수 ────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
KST = ZoneInfo("Asia/Seoul")
# ─────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

CONFIG = {
    "min_price":      1_000,
    "min_market_cap": 50_000_000_000,   # 500억
    "min_vol_ratio":  500,               # 전일 대비 500%
    "ma_short":       5,
    "ma_long":        20,
    "markets":        ["KOSPI", "KOSDAQ"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://finance.naver.com/",
}


# ══════════════════════════════════════════════
#  네이버 증권 API
# ══════════════════════════════════════════════
def get_naver_stock_list(market: str) -> pd.DataFrame:
    """네이버 증권에서 전종목 시세 가져오기"""
    market_code = "KOSPI" if market == "KOSPI" else "KOSDAQ"
    page, results = 1, []

    while True:
        url = (
            f"https://m.stock.naver.com/api/stocks/all"
            f"?market={market_code}&page={page}&pageSize=100&sosok="
        )
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            data = r.json()
            items = data.get("stocks", data.get("result", []))
            if not items:
                break
            results.extend(items)
            if len(results) >= data.get("totalCount", len(results)):
                break
            page += 1
            time.sleep(0.1)
        except Exception as e:
            log.warning(f"[{market}] 페이지 {page} 실패: {e}")
            break

    if not results:
        return pd.DataFrame()

    rows = []
    for item in results:
        try:
            rows.append({
                "ticker":     item.get("itemCode", item.get("code", "")),
                "name":       item.get("stockName", item.get("name", "")),
                "market":     market,
                "close":      float(item.get("closePrice", item.get("price", 0)) or 0),
                "volume":     int(item.get("accumulatedTradingVolume", item.get("volume", 0)) or 0),
                "market_cap": float(item.get("marketValue", item.get("marketCap", 0)) or 0) * 100_000_000,
            })
        except Exception:
            continue

    return pd.DataFrame(rows)


def get_naver_prev_volume(ticker: str) -> int:
    """전일 거래량 조회"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/price"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        # 전일 거래량 필드 탐색
        prev = (data.get("previousVolume")
                or data.get("prevVolume")
                or data.get("yesterdayVolume")
                or 0)
        return int(prev)
    except Exception:
        return 0


def get_naver_daily_prices(ticker: str, days: int = 30) -> pd.Series:
    """일봉 종가 시리즈 반환 (이동평균 계산용)"""
    url = (
        f"https://api.stock.naver.com/chart/domestic/item/{ticker}/day"
        f"?startDateTime=&endDateTime=&count={days}"
    )
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        prices = [float(c["closePrice"]) for c in data if "closePrice" in c]
        if prices:
            return pd.Series(prices[::-1])   # 오래된 순으로
    except Exception:
        pass

    # 폴백: 네이버 PC 버전 일봉
    url2 = f"https://finance.naver.com/item/sise_day.naver?code={ticker}"
    try:
        dfs = pd.read_html(
            requests.get(url2, headers=HEADERS, timeout=15).text,
            encoding="euc-kr"
        )
        for df in dfs:
            if "종가" in df.columns:
                prices = df["종가"].dropna().astype(float).tolist()
                return pd.Series(prices[::-1])
    except Exception:
        pass

    return pd.Series(dtype=float)


# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks() -> tuple[list[dict], str]:
    trade_date = datetime.now(KST).strftime("%Y%m%d")
    log.info(f"스크리닝 시작 (KST: {trade_date})")

    all_rows = []
    for market in CONFIG["markets"]:
        log.info(f"[{market}] 종목 목록 로딩...")
        df = get_naver_stock_list(market)
        if not df.empty:
            all_rows.append(df)
            log.info(f"[{market}] {len(df)}개 로드")
        else:
            log.warning(f"[{market}] 데이터 없음")

    if not all_rows:
        raise RuntimeError("시장 데이터를 가져올 수 없습니다. (네이버 증권 API 실패)")

    df = pd.concat(all_rows, ignore_index=True)

    # 1차 필터
    df = df[df["close"] >= CONFIG["min_price"]].copy()
    df = df[df["market_cap"] >= CONFIG["min_market_cap"]].copy()
    log.info(f"1차 필터 (주가/시총): {len(df)}개")

    # 전일 거래량 & 거래량 비율 필터
    results = []
    ma_s_n = CONFIG["ma_short"]
    ma_l_n = CONFIG["ma_long"]
    passed_vol = 0

    for _, row in df.iterrows():
        ticker = row["ticker"]
        if not ticker:
            continue

        prev_vol = get_naver_prev_volume(ticker)
        if prev_vol <= 0:
            continue

        vol_ratio = row["volume"] / prev_vol * 100
        if vol_ratio < CONFIG["min_vol_ratio"]:
            continue
        passed_vol += 1

        # 이동평균 정배열
        prices = get_naver_daily_prices(ticker, days=max(ma_l_n + 5, 30))
        if len(prices) < ma_l_n:
            continue

        ma_s = prices.rolling(ma_s_n).mean().iloc[-1]
        ma_l = prices.rolling(ma_l_n).mean().iloc[-1]
        close = row["close"]

        if close > ma_s > ma_l:
            results.append({
                "ticker":      ticker,
                "name":        row["name"],
                "market":      row["market"],
                "close":       close,
                "volume":      row["volume"],
                "prev_volume": prev_vol,
                "vol_ratio":   vol_ratio,
                "market_cap":  row["market_cap"],
                "ma5":         round(ma_s, 0),
                "ma20":        round(ma_l, 0),
            })

        time.sleep(0.05)

    log.info(f"거래량 필터: {passed_vol}개 → 정배열 최종: {len(results)}개")
    return sorted(results, key=lambda x: x["vol_ratio"], reverse=True), trade_date


# ══════════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════════
def fmt_won(v):
    if v >= 1_0000_0000_0000: return f"{v/1_0000_0000_0000:.1f}조"
    if v >= 1_0000_0000:      return f"{v/1_0000_0000:.0f}억"
    return f"{v:,.0f}원"

def fmt_price(v): return f"{v:,.0f}원"

def fmt_vol(v):
    if v >= 1_000_000: return f"{v/1_000_000:.1f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return str(int(v))

def escape_md(text):
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


# ══════════════════════════════════════════════
#  메시지 빌더
# ══════════════════════════════════════════════
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
                "KOSPI \\+ KOSDAQ 전종목 분석 중\\.\n"
                "\\(약 10\\~30분 소요\\)"
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
#  /test 명령어 — API 접근 테스트
# ══════════════════════════════════════════════
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("🔬 API 접근 테스트 중\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)

    tests = [
        # 네이버
        ("네이버 전종목",    "https://m.stock.naver.com/api/stocks/all?market=KOSPI&page=1&pageSize=3&sosok=0"),
        ("네이버 종목시세",  "https://m.stock.naver.com/api/stock/005930/price"),
        # Yahoo Finance
        ("Yahoo 삼성전자",   "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?interval=1d&range=5d"),
        ("Yahoo Screener",   "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=day_gainers&count=3"),
        # GitHub (종목 목록용)
        ("GitHub KRX list",  "https://raw.githubusercontent.com/FinanceData/krx-tickers/main/KRX_TICKERS.csv"),
    ]

    lines = ["*API 접근 테스트 결과*\n"]
    for name, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            snippet = r.text[:80].replace("\n", " ")
            lines.append(
                f"✅ {escape_md(name)}: `{r.status_code}` "
                f"`{escape_md(snippet)}`"
            )
        except Exception as e:
            lines.append(f"❌ {escape_md(name)}: `{escape_md(str(e)[:80])}`")

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
        f"  • 거래량 전일 대비 `500%` 이상\n"
        f"  • 주가 `1,000원` 이상\n"
        f"  • 시가총액 `500억` 이상\n"
        f"  • 정배열 \\(종가 \\> 5일선 \\> 20일선\\)\n\n"
        f"💬 *명령어:*\n"
        f"  /scan — 즉시 스크리닝\n"
        f"  /test — API 접근 테스트\n"
        f"  /status — 봇 상태\n"
        f"  /help — 도움말\n\n"
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
        f"📡 데이터 소스: 네이버 증권 API",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *도움말*\n\n"
        "/scan — 즉시 스크리닝 실행\n"
        "/test — 네이버 API 접근 확인\n"
        "/status — 봇 상태 및 다음 실행 시각\n"
        "/help — 이 메시지\n\n"
        "⏰ 자동 실행: 매 평일 오후 4시 10분",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now(KST).weekday() >= 5:
        return
    log.info("자동 스캔 시작")
    await run_screening(context, TELEGRAM_CHAT_ID, silent=True)


# ══════════════════════════════════════════════
#  헬스체크 서버
# ══════════════════════════════════════════════
def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        def log_message(self, *a): pass
    t = threading.Thread(target=HTTPServer(("0.0.0.0", port), Handler).serve_forever, daemon=True)
    t.start()
    log.info(f"헬스체크 서버: 포트 {port}")


# ══════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN 없음"); sys.exit(1)
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID 없음"); sys.exit(1)

    async def run():
        start_health_server()

        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start",  cmd_start))
        app.add_handler(CommandHandler("scan",   cmd_scan))
        app.add_handler(CommandHandler("test",   cmd_test))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(CommandHandler("help",   cmd_help))
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
        log.info("폴링 시작 완료 ✅")

        import signal
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()

        log.info("종료 중...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    asyncio.run(run())

if __name__ == "__main__":
    main()
