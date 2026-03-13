#!/usr/bin/env python3
"""
📱 주식 알림봇 – 텔레그램 봇 (단일 파일)
명령어:
  /scan    → 즉시 스크리닝 실행
  /status  → 봇 상태 확인
  /help    → 도움말
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
from pykrx import stock
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

# ─── 환경변수에서 읽어옴 (Railway Variables에서 설정) ───
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# ────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════════
#  설정값
# ══════════════════════════════════════════════
CONFIG = {
    "min_price":      1_000,
    "min_market_cap": 50_000_000_000,
    "min_vol_ratio":  500,
    "lookback_days":  60,
    "ma_short":       5,
    "ma_long":        20,
    "markets":        ["KOSPI", "KOSDAQ"],
}

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
#  거래일
# ══════════════════════════════════════════════
def get_last_trading_day():
    for i in range(10):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        try:
            if stock.get_market_ticker_list(d, market="KOSPI"):
                return d
        except Exception:
            pass
    raise RuntimeError("최근 거래일을 찾을 수 없습니다.")

def get_prev_trading_day(date_str):
    date = datetime.strptime(date_str, "%Y%m%d")
    for i in range(1, 10):
        d = (date - timedelta(days=i)).strftime("%Y%m%d")
        try:
            if stock.get_market_ticker_list(d, market="KOSPI"):
                return d
        except Exception:
            pass
    raise RuntimeError("이전 거래일을 찾을 수 없습니다.")

# ══════════════════════════════════════════════
#  스크리닝
# ══════════════════════════════════════════════
def screen_stocks(trade_date):
    log.info(f"스크리닝 시작: {trade_date}")
    prev_date = get_prev_trading_day(trade_date)
    fromdate  = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=CONFIG["lookback_days"])).strftime("%Y%m%d")

    frames = []
    for market in CONFIG["markets"]:
        try:
            df_t = stock.get_market_ohlcv_by_ticker(trade_date, market=market)
            df_p = stock.get_market_ohlcv_by_ticker(prev_date,  market=market)
            df_t.index.name = "ticker"; df_t = df_t.reset_index(); df_t["market"] = market
            pv = df_p[["거래량"]].rename(columns={"거래량":"prev_volume"}); pv.index.name="ticker"; pv=pv.reset_index()
            frames.append(df_t.merge(pv, on="ticker", how="left"))
            log.info(f"[{market}] {len(df_t)}개")
        except Exception as e:
            log.error(f"[{market}] 실패: {e}")
    if not frames:
        raise RuntimeError("데이터를 가져올 수 없습니다.")
    df = pd.concat(frames, ignore_index=True)

    # 시가총액
    cap_frames = []
    for market in CONFIG["markets"]:
        try:
            c = stock.get_market_cap_by_ticker(trade_date, market=market)
            c.index.name = "ticker"; c = c.reset_index()
            cap_frames.append(c[["ticker","시가총액"]])
        except Exception:
            pass
    if cap_frames:
        df = df.merge(pd.concat(cap_frames, ignore_index=True), on="ticker", how="left")
    else:
        df["시가총액"] = 0

    # 종목명
    name_map = {}
    for market in CONFIG["markets"]:
        try:
            for t in stock.get_market_ticker_list(trade_date, market=market):
                name_map[t] = stock.get_market_ticker_name(t)
        except Exception:
            pass
    df["name"] = df["ticker"].map(name_map).fillna("알 수 없음")

    # 1차 필터
    df = df[df["종가"] >= CONFIG["min_price"]].copy()
    df = df[df["시가총액"] >= CONFIG["min_market_cap"]].copy()
    df = df[df["prev_volume"] > 0].copy()
    df["vol_ratio"] = df["거래량"] / df["prev_volume"] * 100
    df = df[df["vol_ratio"] >= CONFIG["min_vol_ratio"]].copy()
    log.info(f"1차 필터: {len(df)}개 통과")
    if df.empty:
        return []

    # 이평선 정배열 필터
    results = []
    for _, row in df.iterrows():
        try:
            hist = stock.get_market_ohlcv_by_date(fromdate, trade_date, row["ticker"])
        except Exception:
            continue
        if len(hist) < CONFIG["ma_long"]:
            continue
        cs   = hist["종가"]
        ma_s = cs.rolling(CONFIG["ma_short"]).mean().iloc[-1]
        ma_l = cs.rolling(CONFIG["ma_long"]).mean().iloc[-1]
        close = row["종가"]
        if close > ma_s > ma_l:
            results.append({
                "ticker":      row["ticker"],
                "name":        row["name"],
                "market":      row["market"],
                "close":       close,
                "volume":      row["거래량"],
                "prev_volume": row["prev_volume"],
                "vol_ratio":   row["vol_ratio"],
                "market_cap":  row["시가총액"],
                "ma5":         round(ma_s, 0),
                "ma20":        round(ma_l, 0),
            })
        time.sleep(0.05)

    log.info(f"최종: {len(results)}개")
    return sorted(results, key=lambda x: x["vol_ratio"], reverse=True)

# ══════════════════════════════════════════════
#  메시지 빌더
# ══════════════════════════════════════════════
def build_message(results, trade_date):
    ds = f"{trade_date[:4]}\\.{trade_date[4:6]}\\.{trade_date[6:]}"
    if not results:
        return f"📊 *{ds} 스크리닝 결과*\n\n🔍 조건에 맞는 종목이 없습니다\\."
    lines = [f"📊 *{ds} 스크리닝 결과*", f"✅ *{len(results)}개 종목* 발견\\!\n"]
    for i, r in enumerate(results, 1):
        mkt  = "🔵" if r["market"]=="KOSPI" else "🟣"
        fire = "🔥🔥" if r["vol_ratio"]>=1000 else "🔥" if r["vol_ratio"]>=700 else "📈"
        lines.append(
            f"{i}\\. {mkt} *{escape_md(r['name'])}* `{escape_md(r['ticker'])}`\n"
            f"   💰 {escape_md(fmt_price(r['close']))}  {fire} `{escape_md(f\"{r['vol_ratio']:,.0f}%\")}`\n"
            f"   MA5 `{escape_md(fmt_price(r['ma5']))}` \\| MA20 `{escape_md(fmt_price(r['ma20']))}`\n"
            f"   🏦 {escape_md(fmt_won(r['market_cap']))}"
        )
    return "\n".join(lines)

def build_buttons(results):
    if not results:
        return None
    rows, row = [], []
    for i, r in enumerate(results):
        row.append(InlineKeyboardButton(r["name"], url=f"https://m.stock.naver.com/chart/A{r['ticker']}"))
        if len(row)==2 or i==len(results)-1:
            rows.append(row); row=[]
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════════════════════
#  스크리닝 실행 (비동기)
# ══════════════════════════════════════════════
async def run_screening(context, chat_id, silent=False):
    if not silent:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔍 *스크리닝 시작\\.\\.\\.*\n\nKOSPI \\+ KOSDAQ 전종목 분석 중\\.\n\\(약 10\\~30분 소요\\)",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    try:
        trade_date = get_last_trading_day()
        results    = await asyncio.get_event_loop().run_in_executor(None, screen_stocks, trade_date)
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
            text=f"❌ 오류 발생\n`{escape_md(str(e))}`",
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
        f"💬 *명령어:*  /scan  /status  /help\n\n"
        f"📌 내 채팅 ID: `{escape_md(chat_id)}`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_screening(context, str(update.effective_chat.id))

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    wd  = ["월","화","수","목","금","토","일"][now.weekday()]
    nr  = now.replace(hour=16, minute=10, second=0, microsecond=0)
    if now >= nr or now.weekday() >= 5:
        d = 1
        while True:
            c = (now + timedelta(days=d)).replace(hour=16, minute=10)
            if c.weekday() < 5: nr = c; break
            d += 1
    diff = nr - now
    h, rem = divmod(int(diff.total_seconds()), 3600); m = rem//60
    await update.message.reply_text(
        f"🟢 *봇 정상 작동 중*\n\n"
        f"🕐 현재: `{escape_md(now.strftime('%Y.%m.%d %H:%M'))}` \\({wd}요일\\)\n"
        f"⏰ 다음 자동 실행: `{escape_md(nr.strftime('%m/%d %H:%M'))}` \\({h}시간 {m}분 후\\)",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *도움말*\n\n"
        "/scan — 즉시 스크리닝 실행\n"
        "/status — 봇 상태 및 다음 실행 시각\n"
        "/help — 이 메시지\n\n"
        "⏰ 자동 실행: 매 평일 오후 4시 10분",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now().weekday() >= 5:
        return
    log.info("자동 스캔 시작")
    await run_screening(context, TELEGRAM_CHAT_ID, silent=True)

# ══════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════
def main():
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_TOKEN 환경변수가 없습니다."); sys.exit(1)
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID 환경변수가 없습니다."); sys.exit(1)
    log.info("봇 시작")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.job_queue.run_daily(
        scheduled_scan,
        time=datetime.strptime("16:10", "%H:%M").time(),
        name="daily_scan",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
