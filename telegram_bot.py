#!/usr/bin/env python3
"""
📱 주식 알림봇 – 텔레그램 봇
명령어:
  /scan    → 즉시 스크리닝 실행
  /status  → 봇 상태 확인
  /help    → 도움말
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# ─── 환경변수에서 읽어옴 (Railway Variables에서 설정) ───
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# ────────────────────────────────────────────────────

# 스크리너 임포트
from stock_alert import (
    screen_stocks,
    get_last_trading_day,
    fmt_price, fmt_won, fmt_vol,
    CONFIG,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
#  텔레그램 메시지 포맷터
# ──────────────────────────────────────────────
def build_summary_message(results: list[dict], trade_date: str) -> str:
    date_str = f"{trade_date[:4]}.{trade_date[4:6]}.{trade_date[6:]}"

    if not results:
        return (
            f"📊 *{date_str} 스크리닝 결과*\n\n"
            "🔍 조건에 맞는 종목이 없습니다\\."
        )

    lines = [f"📊 *{date_str} 스크리닝 결과*"]
    lines.append(f"✅ *{len(results)}개 종목* 발견\\!\n")
    lines.append("─" * 28)

    for i, r in enumerate(results, 1):
        mkt = "🔵" if r["market"] == "KOSPI" else "🟣"
        vol_icon = "🔥🔥" if r["vol_ratio"] >= 1000 else "🔥" if r["vol_ratio"] >= 700 else "📈"

        # MarkdownV2 특수문자 이스케이프
        name   = escape_md(r["name"])
        ticker = escape_md(r["ticker"])
        price  = escape_md(fmt_price(r["close"]))
        vol_r  = escape_md(f"{r['vol_ratio']:,.0f}%")
        cap    = escape_md(fmt_won(r["market_cap"]))
        ma5    = escape_md(fmt_price(r["ma5"]))
        ma20   = escape_md(fmt_price(r["ma20"]))

        lines.append(
            f"\n{i}\\. {mkt} *{name}* `{ticker}`\n"
            f"   💰 {price}  {vol_icon} `{vol_r}`\n"
            f"   MA5 `{ma5}` \\| MA20 `{ma20}`\n"
            f"   🏦 시총 {cap}"
        )

    lines.append("\n─" * 28)
    lines.append("_\\* 네이버 차트는 각 종목 버튼으로 확인_")
    return "\n".join(lines)


def build_stock_buttons(results: list[dict]) -> InlineKeyboardMarkup | None:
    if not results:
        return None
    buttons = []
    row = []
    for i, r in enumerate(results):
        url = f"https://m.stock.naver.com/chart/A{r['ticker']}"
        row.append(InlineKeyboardButton(f"{r['name']}", url=url))
        if len(row) == 2 or i == len(results) - 1:
            buttons.append(row)
            row = []
    return InlineKeyboardMarkup(buttons)


def escape_md(text: str) -> str:
    """MarkdownV2 특수문자 이스케이프"""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


# ──────────────────────────────────────────────
#  스크리닝 실행 (비동기 래퍼)
# ──────────────────────────────────────────────
async def run_screening(context: ContextTypes.DEFAULT_TYPE, chat_id: str, silent: bool = False):
    """스크리닝을 별도 스레드에서 실행 후 결과 전송"""

    if not silent:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🔍 *스크리닝 시작\\.\\.\\.*\n\n"
                "KOSPI \\+ KOSDAQ 전종목 분석 중입니다\\.\n"
                "\\(약 10\\~30분 소요\\)"
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    try:
        trade_date = get_last_trading_day()
        results    = await asyncio.get_event_loop().run_in_executor(
            None, screen_stocks, trade_date
        )

        msg     = build_summary_message(results, trade_date)
        buttons = build_stock_buttons(results)

        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=buttons,
        )

        # HTML 리포트도 저장
        from stock_alert import generate_html_report
        html = generate_html_report(results, trade_date)
        filename = f"stock_alert_{trade_date}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        # HTML 파일도 전송
        with open(filename, "rb") as f:
            await context.bot.send_document(
                chat_id=chat_id,
                document=f,
                filename=filename,
                caption=f"📄 {trade_date[:4]}.{trade_date[4:6]}.{trade_date[6:]} 전체 리포트",
            )

    except Exception as e:
        log.error(f"스크리닝 오류: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ 오류가 발생했습니다\\.\n`{escape_md(str(e))}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ──────────────────────────────────────────────
#  커맨드 핸들러
# ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text(
        f"👋 *주식 알림봇에 오신 것을 환영합니다\\!*\n\n"
        f"📋 *스크리닝 조건:*\n"
        f"  • 거래량 전일 대비 `500%` 이상\n"
        f"  • 주가 `1,000원` 이상\n"
        f"  • 시가총액 `500억` 이상\n"
        f"  • 이평선 정배열 \\(종가 \\> 5일선 \\> 20일선\\)\n\n"
        f"💬 *명령어:*\n"
        f"  /scan — 즉시 스크리닝\n"
        f"  /status — 봇 상태\n"
        f"  /help — 도움말\n\n"
        f"📌 채팅 ID: `{escape_md(chat_id)}`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await run_screening(context, chat_id)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    weekday_names = ["월", "화", "수", "목", "금", "토", "일"]
    wd = weekday_names[now.weekday()]

    # 다음 실행 예정 시각
    next_run = now.replace(hour=16, minute=10, second=0, microsecond=0)
    if now >= next_run or now.weekday() >= 5:
        days_ahead = 1
        while True:
            candidate = (now + timedelta(days=days_ahead)).replace(hour=16, minute=10)
            if candidate.weekday() < 5:
                next_run = candidate
                break
            days_ahead += 1

    diff = next_run - now
    hours, rem = divmod(int(diff.total_seconds()), 3600)
    mins = rem // 60

    now_str  = escape_md(now.strftime("%Y.%m.%d %H:%M"))
    next_str = escape_md(next_run.strftime("%m/%d %H:%M"))

    await update.message.reply_text(
        f"🟢 *봇 정상 작동 중*\n\n"
        f"🕐 현재: `{now_str}` \\({wd}요일\\)\n"
        f"⏰ 다음 자동 실행: `{next_str}` \\({hours}시간 {mins}분 후\\)\n\n"
        f"📐 *현재 조건:*\n"
        f"  • 거래량 비율: `{CONFIG['min_vol_ratio']}%` 이상\n"
        f"  • 최소 주가: `{CONFIG['min_price']:,}원`\n"
        f"  • 최소 시총: `500억`\n"
        f"  • MA: `{CONFIG['ma_short']}일` \\> `{CONFIG['ma_long']}일` 정배열",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *도움말*\n\n"
        "/scan — 지금 바로 스크리닝 실행\n"
        "/status — 봇 상태 및 다음 실행 시각\n"
        "/help — 이 메시지\n\n"
        "⏰ *자동 실행*: 매 평일 오후 4시 10분\n\n"
        "⚙️ *조건 변경*: `stock\\_alert\\.py` 의 `CONFIG` 수정",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ──────────────────────────────────────────────
#  자동 스케줄 작업
# ──────────────────────────────────────────────
async def scheduled_scan(context: ContextTypes.DEFAULT_TYPE):
    """매일 자동 실행 (JobQueue)"""
    now = datetime.now()
    if now.weekday() >= 5:  # 주말 제외
        return
    log.info(f"[자동 스캔] {now.strftime('%Y-%m-%d %H:%M')} 시작")
    await run_screening(context, TELEGRAM_CHAT_ID, silent=True)


# ──────────────────────────────────────────────
#  메인
# ──────────────────────────────────────────────
def main():
    if TELEGRAM_TOKEN == "여기에_봇_토큰_입력":
        print("=" * 50)
        print("❌ 토큰 설정이 필요합니다!")
        print()
        print("1. 텔레그램에서 @BotFather 검색")
        print("2. /newbot 명령으로 봇 생성")
        print("3. 발급된 토큰을 TELEGRAM_TOKEN에 입력")
        print()
        print("4. @userinfobot 에서 본인 채팅 ID 확인")
        print("5. TELEGRAM_CHAT_ID에 입력")
        print("=" * 50)
        return

    print("=" * 50)
    print("  📱 주식 알림봇 텔레그램 시작")
    print(f"  ⏰ 자동 실행: 매 평일 16:10")
    print("  🛑 종료: Ctrl+C")
    print("=" * 50)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # 명령어 등록
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help",   cmd_help))

    # 자동 스케줄 (매일 16:10)
    app.job_queue.run_daily(
        scheduled_scan,
        time=datetime.strptime("16:10", "%H:%M").time(),
        name="daily_scan",
    )

    log.info("봇 시작 완료. 폴링 중...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
