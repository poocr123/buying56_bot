"""
보험산업 뉴스 + 인사이트 통합 봇 v2.2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━
발송 스케줄 (평일만)
  08:00 — 인사이트 브리핑 (금감원 + 해외 트렌드)
  09:00 — 보험 뉴스 (전반 + 한화손보)
  12:00 — GPT 심층 분석 (이슈 없으면 생략)
  18:00 — 보험 뉴스 (전반 + 한화손보)
          금요일엔 차주 분석 예고 추가
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import httpx
import pytz
import schedule
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN       = os.getenv("GITHUB_TOKEN", "")
KST = ZoneInfo("Asia/Seoul")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("insurance_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 버전 관리
# ─────────────────────────────────────────────
BOT_VERSION  = "2.2.0"
VERSION_FILE = "bot_version.txt"

VERSION_HISTORY = {
    "2.2.0": {
        "title": "분석 고도화 및 안정화",
        "changes": [
            "08시 인사이트: 금감원 1건 + 해외 1건으로 간소화",
            "08시 인사이트: 새 자료 없으면 발송 생략",
            "12시 분석: GPT 심층 분석 강화 (배경·영향·대응방안·전망)",
            "뉴스 GPT 필터링: 중복 제거 + 중요도 선별 + 한 줄 요약",
            "보험연구원 수집 제거 (정확도 문제)",
            "한화손보 마이너 기사 자동 차단",
            "구글 뉴스 URL 정확도 개선",
        ],
    },
    "2.1.0": {
        "title": "뉴스+인사이트 통합 단일 봇",
        "changes": [
            "뉴스 봇 + 인사이트 봇을 하나로 통합",
            "08시 인사이트 브리핑 추가",
        ],
    },
    "2.0.0": {
        "title": "발송 구조 전면 개편",
        "changes": [
            "09시·18시 뉴스 / 12시 GPT 자율 분석",
            "금요일 18시 차주 분석 예고 추가",
        ],
    },
}

SESSION_FILE       = "session_sent.json"
INSIGHT_CACHE_FILE = "insight_sent_cache.json"

# ─────────────────────────────────────────────
# 뉴스 소스
# ─────────────────────────────────────────────
NEWS_SOURCES_ALL = [
    {"name": "실손보험",   "url": "https://news.google.com/rss/search?q=실손보험&hl=ko&gl=KR&ceid=KR:ko",                    "emoji": "🏥"},
    {"name": "자동차보험", "url": "https://news.google.com/rss/search?q=자동차보험&hl=ko&gl=KR&ceid=KR:ko",                  "emoji": "🚗"},
    {"name": "보험료",     "url": "https://news.google.com/rss/search?q=보험료+인상+인하&hl=ko&gl=KR&ceid=KR:ko",            "emoji": "💰"},
    {"name": "생명보험",   "url": "https://news.google.com/rss/search?q=생명보험+삼성+한화+교보&hl=ko&gl=KR&ceid=KR:ko",     "emoji": "❤️"},
    {"name": "손해보험",   "url": "https://news.google.com/rss/search?q=손해보험+삼성화재+현대해상&hl=ko&gl=KR&ceid=KR:ko",  "emoji": "🛡️"},
    {"name": "보험금",     "url": "https://news.google.com/rss/search?q=보험금+지급+부지급&hl=ko&gl=KR&ceid=KR:ko",          "emoji": "💵"},
    {"name": "보험사기",   "url": "https://news.google.com/rss/search?q=보험사기&hl=ko&gl=KR&ceid=KR:ko",                    "emoji": "🚨"},
    {"name": "보험규제",   "url": "https://news.google.com/rss/search?q=보험+규제+감독+정책&hl=ko&gl=KR&ceid=KR:ko",         "emoji": "🏛️"},
    {"name": "보험신상품", "url": "https://news.google.com/rss/search?q=보험+신상품+출시&hl=ko&gl=KR&ceid=KR:ko",            "emoji": "🆕"},
    {"name": "보험실적",   "url": "https://news.google.com/rss/search?q=보험사+실적+순이익&hl=ko&gl=KR&ceid=KR:ko",          "emoji": "📈"},
    {"name": "보험대리점", "url": "https://news.google.com/rss/search?q=보험대리점+GA+법인보험대리점&hl=ko&gl=KR&ceid=KR:ko","emoji": "🏢"},
    {"name": "Naver경제",  "url": "https://news.naver.com/main/rss/section.nhn?sid1=101",                                     "emoji": "📰"},
]

NEWS_SOURCES_HW = [
    {"name": "한화손해보험", "url": "https://news.google.com/rss/search?q=한화손해보험&hl=ko&gl=KR&ceid=KR:ko", "emoji": "🧡"},
]

GLOBAL_SOURCES = [
    {"name": "Swiss Re",          "url": "https://www.swissre.com/feed/news.rss",                        "emoji": "🇨🇭"},
    {"name": "Munich Re",         "url": "https://www.munichre.com/en/company/media-relations/news.rss", "emoji": "🇩🇪"},
    {"name": "IAIS",              "url": "https://www.iaisweb.org/news/feed/",                           "emoji": "🌐"},
    {"name": "Insurance Journal", "url": "https://www.insurancejournal.com/feed/",                       "emoji": "📰"},
]

FSS_URL = "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218"

# ─────────────────────────────────────────────
# 필터링 키워드
# ─────────────────────────────────────────────
INSURANCE_CORE = [
    "보험료","보험금","보험사","보험사기","보험업",
    "실손보험","실손","자동차보험","운전자보험",
    "생명보험","손해보험","화재보험","종신보험",
    "암보험","치매보험","연금보험","건강보험",
    "삼성생명","한화생명","교보생명","미래에셋생명","신한라이프",
    "삼성화재","현대해상","DB손해보험","KB손해보험","메리츠화재",
    "흥국생명","동양생명","ABL생명",
    "IFRS17","K-ICS","언더라이팅","재보험","보험계리",
    "생보협회","손보협회","보험개발원","보험연구원",
    "보험대리점","GA","법인보험대리점","독립보험대리점",
]
INSURANCE_BROAD = INSURANCE_CORE + ["보험","피보험자","수익자","계약자","가입자","보장"]
INSURANCE_KEYWORDS = INSURANCE_CORE + [
    "감독규정","감독지침","시행령","고시","보험업법","지급여력","요율",
    "모집","설계사","약관","준비금",
]

HW_KEYWORDS = ["한화손해보험","한화손보"]
HW_EXCLUDE  = [
    "채용","봉사","기부","후원","협약","MOU","행사","이벤트",
    "인사","임원","대표이사","사장","회장",
]

EXCLUDE_KEYWORDS = [
    "광고","홍보","이벤트","경품","추첨","할인쿠폰","무료체험",
    "[카드뉴스]","[인포그래픽]","[영상]","별자리","운세","오늘의","날씨",
    "주식","펀드","ETF","은행","대출","금리","채권","가상자산","코인","부동산","증권",
]

PRIORITY_KEYWORDS = {
    "금감원":3,"금융감독원":3,"보험업법":3,"IFRS17":3,"K-ICS":3,
    "삼성생명":3,"삼성화재":3,"한화생명":3,"교보생명":3,
    "현대해상":3,"DB손해보험":3,"메리츠화재":3,
    "실손보험":3,"자동차보험":3,"한화손해보험":3,
    "보험료":2,"인상":2,"인하":2,"보험금":2,
    "실적":2,"순이익":2,"합병":2,"인수":2,
    "보험사기":2,"규제":2,"정책":2,"부지급":2,"보험대리점":2,"GA":2,
    "생명보험":1,"손해보험":1,"신상품":1,"재보험":1,"갱신":1,
}

TOPIC_GROUPS = [
    "삼성생명","한화생명","교보생명","미래에셋생명","신한라이프",
    "삼성화재","현대해상","DB손해보험","KB손해보험","메리츠화재",
    "한화손해보험","실손보험","자동차보험","보험사기","보험료","보험금",
    "IFRS17","K-ICS","재보험","보험대리점","GA",
]

RESPONSE_HINTS = {
    "IFRS17":    "CSM 관리 및 수익성 중심 포트폴리오 전략 재검토 필요",
    "K-ICS":     "지급여력비율 관리 강화 및 자본 효율화 방안 수립",
    "실손보험":  "손해율 관리 및 비급여 청구 모니터링 강화",
    "자동차보험":"사고율·수리비 트렌드 분석으로 요율 적정성 검토",
    "보험료":    "요율 변경 시 고객 커뮤니케이션 및 해지 방어 방안 준비",
    "GA":        "GA 채널 관리 강화 및 불완전판매 방지 체계 점검",
    "설계사":    "모집 규정 준수 교육 강화 및 내부통제 체계 정비",
    "보험사기":  "이상징후 탐지 시스템 고도화 및 SIU 역량 강화",
    "지급여력":  "ALM 전략 재검토 및 리스크 관리 체계 강화",
    "준비금":    "책임준비금 적정성 검토 및 계리 가정 재검토",
}

def calc_priority(title, summary):
    return sum(pts for kw, pts in PRIORITY_KEYWORDS.items() if kw in title + summary)

def get_topic_key(title):
    for t in TOPIC_GROUPS:
        if t in title: return t
    return "기타"

def is_insurance_article(title, summary):
    if any(ex in title for ex in EXCLUDE_KEYWORDS): return False
    if any(kw in title for kw in INSURANCE_CORE): return True
    return any(kw in title + " " + summary for kw in INSURANCE_BROAD)

def is_hanwha_article(title, summary):
    if any(ex in title for ex in EXCLUDE_KEYWORDS): return False
    if any(ex in title for ex in HW_EXCLUDE): return False
    return any(kw in title for kw in HW_KEYWORDS)

def clean_title(title):
    title = re.sub(r"\s[-–—]\s.{2,15}$", "", title).strip()
    for ent, char in {
        "&nbsp;":" ","&amp;":"&","&lt;":"<","&gt;":">",
        "&quot;":'"',"&#39;":"'","&hellip;":"..."
    }.items():
        title = title.replace(ent, char)
    return re.sub(r"&[a-zA-Z0-9#]+;", "", title).strip()

# ─────────────────────────────────────────────
# 캐시
# ─────────────────────────────────────────────
def load_json(path, default):
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_insight_cache() -> set:
    if Path(INSIGHT_CACHE_FILE).exists():
        with open(INSIGHT_CACHE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f)[-3000:])
    return set()

def save_insight_cache(cache: set):
    with open(INSIGHT_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(cache)[-3000:], f, ensure_ascii=False)

def make_hash(title, url=""):
    return hashlib.md5(f"{title}{url}".encode()).hexdigest()

def make_title_hash(title):
    return hashlib.md5(re.sub(r"[^\w]", "", title)[:30].encode()).hexdigest()

# ─────────────────────────────────────────────
# RSS 수집
# ─────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def fetch_page(url: str) -> str:
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=12, follow_redirects=True)
        return resp.text if resp.status_code == 200 else ""
    except Exception as e:
        logger.warning(f"페이지 로드 실패: {e}")
        return ""

def fetch_rss(sources):
    articles = []
    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:30]:
                title = clean_title(entry.get("title", "").strip())
                if not title: continue

                # 구글 뉴스: source 태그에서 실제 URL 추출
                link = ""
                if hasattr(entry, "source") and isinstance(entry.source, dict):
                    link = entry.source.get("href", "")
                if not link:
                    link = entry.get("link", "").strip()

                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:500].strip()
                pub_dt, pub_str = None, ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_dt  = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC")).astimezone(KST)
                    pub_str = pub_dt.strftime("%m/%d %H:%M")
                articles.append({
                    "title": title, "url": link, "summary": summary,
                    "pub_date": pub_str, "pub_dt": pub_dt,
                    "source": source["name"], "emoji": source["emoji"],
                })
        except Exception as e:
            logger.error(f"RSS 오류 [{source['name']}]: {e}")
    return articles

def fetch_fss_news():
    articles = []
    try:
        resp = httpx.get(FSS_URL, headers=HEADERS, timeout=10, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        for row in soup.select("table tbody tr")[:10]:
            cells = row.find_all("td")
            tag   = row.find("a")
            if not tag or len(cells) < 3: continue
            title = tag.get_text(strip=True)
            if not any(kw in title for kw in INSURANCE_BROAD): continue
            href = tag.get("href", "")
            link = f"https://www.fss.or.kr{href}" if href.startswith("/") else href
            articles.append({
                "title": title, "url": link, "summary": "",
                "pub_date": cells[-1].get_text(strip=True), "pub_dt": None,
                "source": "금감원", "emoji": "🏛️", "priority": 10,
            })
    except Exception as e:
        logger.error(f"금감원 뉴스 오류: {e}")
    return articles

def fetch_fss_insight():
    items = []
    try:
        soup = BeautifulSoup(fetch_page(FSS_URL), "html.parser")
        for row in soup.select("table tbody tr")[:8]:
            tag   = row.find("a")
            cells = row.find_all("td")
            if not tag or len(cells) < 3: continue
            title = tag.get_text(strip=True)
            if not any(kw in title for kw in INSURANCE_KEYWORDS + ["보험"]): continue
            href = tag.get("href", "")
            link = f"https://www.fss.or.kr{href}" if href.startswith("/") else href
            items.append({
                "title": title, "url": link,
                "date": cells[-1].get_text(strip=True),
                "source": "금융감독원", "emoji": "🏛️",
                "doc_type": "규제·감독 보도자료",
            })
    except Exception as e:
        logger.error(f"금감원 인사이트 오류: {e}")
    return items

def fetch_global():
    items = []
    for source in GLOBAL_SOURCES:
        try:
            feed = feedparser.parse(source["url"])
            for entry in feed.entries[:4]:
                title   = entry.get("title", "").strip()
                link    = entry.get("link", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))[:500].strip()
                if not title: continue
                pub_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_dt  = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC")).astimezone(KST)
                    pub_str = pub_dt.strftime("%m/%d")
                items.append({
                    "title": title, "url": link, "date": pub_str,
                    "source": source["name"], "emoji": source["emoji"],
                    "doc_type": "해외 보험 트렌드", "body": summary,
                })
        except Exception as e:
            logger.error(f"해외 RSS 오류 [{source['name']}]: {e}")
    return items

def extract_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    for sel in [".view_content", ".board_view", "#contents", ".report_view", "article", "main"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 200:
                return re.sub(r"\s+", " ", text)[:4000]
    return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))[:4000]

# ─────────────────────────────────────────────
# 기사 수집 & 토픽 분산
# ─────────────────────────────────────────────
def collect_articles(sources, filter_fn, date_filter=None, exclude_hashes=None, limit=50):
    if exclude_hashes is None: exclude_hashes = set()
    now       = datetime.now(KST)
    today     = now.date()
    yesterday = today - timedelta(days=1)

    all_arts, seen_titles = [], set()

    for art in fetch_rss(sources):
        h, th = make_hash(art["title"], art["url"]), make_title_hash(art["title"])
        if h in exclude_hashes or th in seen_titles: continue
        if not filter_fn(art["title"], art["summary"]): continue
        if date_filter and art["pub_dt"]:
            d = art["pub_dt"].date()
            if date_filter == "yesterday" and d != yesterday: continue
            if date_filter == "today"     and d != today:     continue
        art["_hash"]     = h
        art["priority"]  = calc_priority(art["title"], art["summary"])
        art["topic_key"] = get_topic_key(art["title"])
        all_arts.append(art)
        seen_titles.add(th)

    if filter_fn == is_insurance_article:
        for art in fetch_fss_news():
            h, th = make_hash(art["title"], art["url"]), make_title_hash(art["title"])
            if h not in exclude_hashes and th not in seen_titles:
                art["_hash"]     = h
                art["topic_key"] = get_topic_key(art["title"])
                art.setdefault("priority", 10)
                all_arts.append(art)
                seen_titles.add(th)

    all_arts.sort(key=lambda x: x.get("priority", 0), reverse=True)

    topic_count, diverse = {}, []
    for art in all_arts:
        tk  = art["topic_key"]
        cnt = topic_count.get(tk, 0)
        if tk == "기타" or cnt < 2:
            diverse.append(art)
            topic_count[tk] = cnt + 1
        if len(diverse) >= limit: break

    if len(diverse) < limit:
        used = {a["_hash"] for a in diverse}
        for art in all_arts:
            if art["_hash"] not in used:
                diverse.append(art)
            if len(diverse) >= limit: break

    return diverse

# ─────────────────────────────────────────────
# GPT-4o
# ─────────────────────────────────────────────
async def gpt_request(prompt: str, max_tokens: int = 1000) -> str:
    if not GITHUB_TOKEN:
        return ""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://models.inference.ai.azure.com/chat/completions",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": max_tokens, "temperature": 0.4},
                timeout=30,
            )
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"GPT 요청 실패: {e}")
        return ""

async def gpt_filter_news(articles: list) -> list:
    """GPT가 중복 제거 + 중요도 판단 + 한 줄 요약 추가"""
    if not GITHUB_TOKEN or not articles:
        return articles[:10]

    news_list = ""
    for i, art in enumerate(articles[:30], 1):
        summary = art.get("summary", "")[:100]
        news_list += f"[{i}] {art['title']}"
        if summary:
            news_list += f" | {summary}"
        news_list += "\n"

    prompt = (
        "당신은 보험산업 전문 애널리스트입니다.\n\n"
        f"보험 뉴스 목록:\n{news_list}\n"
        "기준:\n"
        "1. 중복·유사 기사는 하나만 남기고 제거\n"
        "2. 보험산업에 실질적 영향 있는 기사만 선별\n"
        "   - 높음: 규제변화·보험료·실손·대형사 실적·제도개편\n"
        "   - 보통: 신상품·업계동향·법원판결\n"
        "   - 낮음(제외): 단순홍보·인사·봉사·반복성 기사\n"
        "3. 각 기사에 한 줄 요약(30자 이내) 작성\n\n"
        "JSON으로만 응답:\n"
        '[{"idx": 번호, "importance": "high/medium/low", "summary": "한줄요약"}]'
    )

    result_str = await gpt_request(prompt, max_tokens=1500)
    if not result_str:
        return articles[:10]

    try:
        clean   = re.sub(r"```json|```", "", result_str).strip()
        results = json.loads(clean)
        filtered = []
        for r in results:
            if r.get("importance") == "low":
                continue
            idx = r.get("idx", 0) - 1
            if 0 <= idx < len(articles):
                art = articles[idx].copy()
                art["gpt_summary"]    = r.get("summary", "")
                art["gpt_importance"] = r.get("importance", "medium")
                filtered.append(art)
        if filtered:
            logger.info(f"✅ GPT 필터링: {len(articles)}개 → {len(filtered)}개 선별")
            return filtered[:10]
    except Exception as e:
        logger.warning(f"GPT 필터링 실패, 기존 방식 사용: {e}")

    return articles[:10]

async def gpt_insight_analyze(title: str, body: str, doc_type: str) -> dict:
    if GITHUB_TOKEN:
        is_report = "보고서" in doc_type or "연구" in doc_type
        depth = (
            "보험산업 실무자가 바로 활용할 수 있도록 분석하세요.\n"
            "- summary: 핵심 주장과 수치 중심 (각 100자 이내)\n"
            "- implications: 국내 보험사에 미치는 실질적 영향\n"
            "- response: 원수사(특히 한화손해보험) 관점의 구체적 대응방안"
        ) if is_report else "핵심 내용·시사점·대응방안을 간결하게 정리"

        prompt = (
            f"당신은 보험산업 전문 애널리스트입니다.\n\n"
            f"문서 유형: {doc_type}\n"
            f"제목: {title}\n"
            f"본문: {body[:4000]}\n\n"
            f"{depth}\n\n"
            f"JSON으로만 한국어 분석:\n"
            f'{{"summary":["핵심1","핵심2","핵심3"],"implications":["시사점1","시사점2"],"response":["대응방안1","대응방안2"]}}'
        )
        result_str = await gpt_request(prompt, max_tokens=1200)
        if result_str:
            try:
                clean = re.sub(r"```json|```", "", result_str).strip()
                return json.loads(clean)
            except:
                pass

    # 자동 분석 fallback
    sentences = re.split(r"(?<=[다았었겠]\.)\s+|(?<=니다\.)\s+", body)
    sentences = [s.strip() for s in sentences if 20 < len(s.strip()) < 200]
    bad = ["기자","무단전재","저작권","ⓒ","Copyright","문의","클릭"]
    sentences = [s for s in sentences if not any(b in s for b in bad)]
    title_words = set(re.findall(r"[가-힣A-Z]{2,}", title))
    scored = []
    for i, sent in enumerate(sentences[:50]):
        score = len(title_words & set(re.findall(r"[가-힣A-Z]{2,}", sent))) * 2
        if re.search(r"\d+[조억만원%]", sent): score += 3
        if re.search(r"\d+\.\d+%", sent): score += 2
        if any(kw in sent for kw in INSURANCE_KEYWORDS): score += 3
        score += max(0, 5 - i // 8)
        scored.append((score, i, sent))
    top3 = sorted(scored, key=lambda x: -x[0])[:3]
    top3 = sorted(top3, key=lambda x: x[1])
    summary = [s[2] for s in top3] if top3 else ["본문을 원문에서 확인해 주세요."]
    hints = []
    for kw, hint in RESPONSE_HINTS.items():
        if kw in title + " " + body:
            hints.append(f"[{kw}] {hint}")
        if len(hints) >= 2: break
    return {"summary": summary, "implications": [], "response": hints}

async def gpt_noon_analysis(titles: list) -> dict:
    if not GITHUB_TOKEN:
        return {"skip": True}
    titles_str = "\n".join(f"- {t}" for t in titles[:30])
    prompt = (
        "당신은 보험산업 전문 애널리스트입니다.\n\n"
        f"이번 주 보험 뉴스:\n{titles_str}\n\n"
        "가장 중요한 이슈 1개를 선정해 심층 분석하세요.\n"
        "단순 요약이 아닌 실무진이 바로 활용할 수 있는 깊이 있는 분석이어야 합니다.\n"
        "분석 가치가 없으면 skip:true 반환.\n\n"
        "JSON으로만 응답:\n"
        '{"skip": false, "topic": "이슈 제목", '
        '"background": "배경과 맥락", '
        '"analysis": "핵심 내용 심층 분석", '
        '"industry_impact": "보험산업 전반 영향", '
        '"response": "원수사 단기·중기 대응방안", '
        '"outlook": "향후 전망"}'
        '\n또는 {"skip": true}'
    )
    result_str = await gpt_request(prompt, max_tokens=1500)
    if result_str:
        try:
            clean = re.sub(r"```json|```", "", result_str).strip()
            return json.loads(clean)
        except:
            pass
    return {"skip": True}

async def gpt_weekly_preview(titles: list) -> str:
    if not GITHUB_TOKEN:
        return ""
    titles_str = "\n".join(f"- {t}" for t in titles[:30])
    prompt = (
        "당신은 보험산업 전문 애널리스트입니다.\n\n"
        f"이번 주 보험 뉴스:\n{titles_str}\n\n"
        "다음 주 심층 분석할 토픽 1~2개 선정 후 왜 분석이 필요한지 간략히 예고.\n"
        "300자 이내·실무진 대상·인사말 없이 바로 본론."
    )
    return await gpt_request(prompt, max_tokens=500)

# ─────────────────────────────────────────────
# 텔레그램
# ─────────────────────────────────────────────
async def send_telegram(text: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=15,
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"전송 오류: {e}")
        return False

def build_news_message(header_title, articles):
    now    = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    header = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 {header_title}\n"
        f"🕐 {now}  |  총 {len(articles)}건\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    items = []
    for i, art in enumerate(articles, 1):
        gpt_imp = art.get("gpt_importance", "")
        if gpt_imp == "high":       badge = "🔴"
        elif gpt_imp == "medium":   badge = "🟡"
        else:
            score = art.get("priority", 0)
            badge = "🔴" if score >= 6 else ("🟡" if score >= 3 else "🔵")

        pub     = f"  {art.get('pub_date','')}" if art.get("pub_date") else ""
        fss     = "  📌 금융감독원 보도자료" if art.get("source") == "금감원" else ""
        gpt_sum = art.get("gpt_summary", "")

        item  = f"{badge} {i}. {art['title']}\n"
        if gpt_sum:
            item += f"    └ {gpt_sum}\n"
        item += f"    <a href=\"{art['url']}\">▶ 전문 보기</a>{pub}{fss}\n"
        items.append(item)

    messages, current = [], header
    for item in items:
        if len(current) + len(item) + 5 > 4000:
            messages.append(current.strip())
            current = item
        else:
            current += item + "\n"
    if current.strip():
        messages.append(current.strip())
    return messages

async def send_news(header_title, articles, empty_msg=None):
    if not articles:
        await send_telegram(empty_msg or f"📭 {header_title}\n\n주요 뉴스가 없습니다.")
        return
    for msg in build_news_message(header_title, articles):
        await send_telegram(msg)
        await asyncio.sleep(0.5)
    logger.info(f"✅ '{header_title}' 발송 ({len(articles)}건)")

def format_insight(item: dict, analysis: dict, idx: int) -> str:
    date_str = f"  {item['date']}" if item.get("date") else ""
    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"{item['emoji']} [{idx}] {item['title']}",
        f"📂 {item['doc_type']}  |  {item['source']}{date_str}",
        "",
    ]
    if analysis.get("summary"):
        lines.append("📌 핵심 내용")
        for s in analysis["summary"]:
            lines.append(f"  • {s[:150]}")
        lines.append("")
    if analysis.get("implications"):
        lines.append("💡 보험산업 시사점")
        for s in analysis["implications"]:
            lines.append(f"  • {s[:150]}")
        lines.append("")
    if analysis.get("response"):
        lines.append("🏢 원수사 대응방안")
        for s in analysis["response"]:
            lines.append(f"  • {s[:150]}")
        lines.append("")
    lines.append(f"🔗 <a href=\"{item['url']}\">원문 보기</a>")
    return "\n".join(lines)

# ─────────────────────────────────────────────
# 봇 안내 메시지
# ─────────────────────────────────────────────
async def send_notice():
    prev = ""
    if Path(VERSION_FILE).exists():
        with open(VERSION_FILE, "r") as f:
            prev = f.read().strip()
    if prev == BOT_VERSION:
        return
    with open(VERSION_FILE, "w") as f:
        f.write(BOT_VERSION)

    is_new   = not prev
    now_info = VERSION_HISTORY.get(BOT_VERSION, {})
    title    = now_info.get("title", "업데이트")
    changes  = now_info.get("changes", [])

    update_section = "  • 최초 서비스 시작 🎉" if is_new else "\n".join(f"  • {c}" for c in changes)

    history_lines = ""
    prev_versions = [v for v in VERSION_HISTORY if v != BOT_VERSION][:2]
    if not is_new and prev_versions:
        history_lines = "\n📜 이전 버전 이력\n"
        for v in prev_versions:
            h = VERSION_HISTORY.get(v, {})
            history_lines += f"  v{v}  {h.get('title','')}\n"

    msg = (
        f"🤖 보험뉴스 알림봇 {'시작 안내' if is_new else '업데이트 안내'}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"버전  v{BOT_VERSION}  |  {title}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        + ("안녕하세요! 보험뉴스 자동 알림봇입니다.\n\n" if is_new
           else f"이전 버전 v{prev} 에서 업데이트되었습니다.\n\n")
        + f"🆕 {'서비스 내용' if is_new else '이번 업데이트'}\n"
        + update_section + "\n"
        + history_lines
        + f"\n📅 현재 발송 스케줄 (평일)\n"
        f"  08:00  🔬 인사이트 브리핑\n"
        f"  09:00  📰 보험 뉴스\n"
        f"  12:00  🧠 GPT 심층 분석 (이슈 있을 때만)\n"
        f"  18:00  📰 보험 뉴스\n"
        f"          금요일엔 차주 분석 예고 포함\n\n"
        f"📋 뉴스 구성\n"
        f"  1️⃣  보험산업 전반\n"
        f"  2️⃣  한화손해보험 전용\n\n"
        f"🔴 긴급/중요   🟡 주요   🔵 일반\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"문의사항은 관리자에게 연락해 주세요."
    )
    await send_telegram(msg)
    logger.info(f"📢 안내 메시지 발송 (v{BOT_VERSION})")

# ─────────────────────────────────────────────
# 발송 태스크
# ─────────────────────────────────────────────
async def send_insight():
    """08:00 — 인사이트 브리핑 (금감원 1건 + 해외 1건)"""
    if datetime.now(KST).weekday() >= 5:
        return
    logger.info("🔬 [08:00] 인사이트 브리핑 시작")
    cache    = load_insight_cache()
    mode_str = "GPT-4o" if GITHUB_TOKEN else "자동 분석"
    now_str  = datetime.now(KST).strftime("%Y년 %m월 %d일")
    total_sent = 0

    fss_items    = [it for it in fetch_fss_insight() if make_hash(it["title"] + it["url"]) not in cache]
    global_items = [it for it in fetch_global()      if make_hash(it["title"] + it["url"]) not in cache]

    fss_item    = fss_items[0]    if fss_items    else None
    global_item = global_items[0] if global_items else None

    if not fss_item and not global_item:
        logger.info("인사이트 새 자료 없음 — 발송 생략")
        return

    await send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔬 보험산업 인사이트 브리핑\n"
        f"📅 {now_str}  오전 8시  |  {mode_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    await asyncio.sleep(0.5)

    if fss_item:
        try:
            body     = extract_body(fetch_page(fss_item["url"]))
            analysis = await gpt_insight_analyze(fss_item["title"], body, fss_item["doc_type"])
            await send_telegram(format_insight(fss_item, analysis, 1))
            cache.add(make_hash(fss_item["title"] + fss_item["url"]))
            total_sent += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"금감원 인사이트 오류: {e}")

    if global_item:
        try:
            body     = global_item.get("body") or extract_body(fetch_page(global_item["url"]))
            analysis = await gpt_insight_analyze(global_item["title"], body, global_item["doc_type"])
            await send_telegram(format_insight(global_item, analysis, 2 if fss_item else 1))
            cache.add(make_hash(global_item["title"] + global_item["url"]))
            total_sent += 1
            await asyncio.sleep(1.5)
        except Exception as e:
            logger.error(f"해외 트렌드 인사이트 오류: {e}")

    await send_telegram(
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ 인사이트 브리핑 완료  ({total_sent}건)\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    save_insight_cache(cache)
    logger.info(f"✅ 인사이트 발송 완료 ({total_sent}건)")

async def send_morning():
    """09:00 — 뉴스"""
    if datetime.now(KST).weekday() >= 5:
        return
    logger.info("🌅 [09:00] 뉴스 발송")
    save_json(SESSION_FILE, {"all_day": []})

    arts_raw = collect_articles(NEWS_SOURCES_ALL, is_insurance_article, date_filter="yesterday")
    arts_all = await gpt_filter_news(arts_raw)
    await send_news("📰 보험산업 주요뉴스 (어제)", arts_all)
    await asyncio.sleep(1)

    hw_ex   = {a["_hash"] for a in arts_all}
    arts_hw = collect_articles(NEWS_SOURCES_HW, is_hanwha_article,
                               date_filter="yesterday", exclude_hashes=hw_ex, limit=5)
    now_str = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    await send_news(
        "🧡 한화손해보험 뉴스 (어제)", arts_hw,
        empty_msg=(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧡 한화손해보험 뉴스 (어제)\n"
            f"🕐 {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"한화손해보험 관련 새로운 뉴스가 없습니다."
        )
    )

    session = load_json(SESSION_FILE, {"all_day": []})
    all_day = set(session.get("all_day", []))
    all_day.update(a["_hash"] for a in arts_all + arts_hw)
    save_json(SESSION_FILE, {"all_day": list(all_day)})

async def send_noon():
    """12:00 — GPT 심층 분석"""
    if datetime.now(KST).weekday() >= 5:
        return
    logger.info("☀️ [12:00] GPT 심층 분석")

    arts   = collect_articles(NEWS_SOURCES_ALL, is_insurance_article)
    titles = [a["title"] for a in arts]
    if not titles:
        return

    result = await gpt_noon_analysis(titles)
    if result.get("skip"):
        logger.info("GPT 판단: 분석할 이슈 없음 — 생략")
        return

    topic          = result.get("topic", "오늘의 보험 이슈")
    background     = result.get("background", "")
    analysis       = result.get("analysis", "")
    industry_impact= result.get("industry_impact", "")
    response       = result.get("response", "")
    outlook        = result.get("outlook", "")
    now_str        = datetime.now(KST).strftime("%Y년 %m월 %d일")

    parts = [
        "━━━━━━━━━━━━━━━━━━━━",
        "🧠 보험 심층 분석",
        f"📅 {now_str}  낮 12시",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📌 {topic}",
        "",
    ]
    if background:
        parts += [f"📖 배경 및 맥락", background, ""]
    if analysis:
        parts += [f"🔍 핵심 분석", analysis, ""]
    if industry_impact:
        parts += [f"💡 보험산업 영향", industry_impact, ""]
    if response:
        parts += [f"🏢 원수사 대응방안", response, ""]
    if outlook:
        parts += [f"📈 향후 전망", outlook, ""]
    parts.append("━━━━━━━━━━━━━━━━━━━━")

    msg = "\n".join(parts)
    if len(msg) > 4000:
        await send_telegram(msg[:4000].strip())
        await asyncio.sleep(0.5)
        await send_telegram(msg[4000:].strip())
    else:
        await send_telegram(msg)
    logger.info(f"✅ 12시 심층 분석 발송: {topic}")

async def send_evening():
    """18:00 — 뉴스 + 금요일 차주 예고"""
    if datetime.now(KST).weekday() >= 5:
        return
    logger.info("🌆 [18:00] 뉴스 발송")

    session = load_json(SESSION_FILE, {"all_day": []})
    exclude = set(session.get("all_day", []))

    arts_raw = collect_articles(NEWS_SOURCES_ALL, is_insurance_article,
                                date_filter="today", exclude_hashes=exclude)
    arts_all = await gpt_filter_news(arts_raw)
    await send_news("📰 보험산업 주요뉴스 (오후)", arts_all)
    await asyncio.sleep(1)

    hw_ex   = exclude | {a["_hash"] for a in arts_all}
    arts_hw = collect_articles(NEWS_SOURCES_HW, is_hanwha_article,
                               date_filter="today", exclude_hashes=hw_ex, limit=5)
    now_str = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    await send_news(
        "🧡 한화손해보험 뉴스 (오후)", arts_hw,
        empty_msg=(
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🧡 한화손해보험 뉴스 (오후)\n"
            f"🕐 {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"한화손해보험 관련 새로운 뉴스가 없습니다."
        )
    )

    if datetime.now(KST).weekday() == 4:
        await asyncio.sleep(1)
        arts    = collect_articles(NEWS_SOURCES_ALL, is_insurance_article)
        titles  = [a["title"] for a in arts]
        preview = await gpt_weekly_preview(titles)
        next_mon = datetime.now(KST) + timedelta(days=(7 - datetime.now(KST).weekday()))
        week_str = next_mon.strftime("%m월 %d일")
        now_str2 = datetime.now(KST).strftime("%Y년 %m월 %d일")
        msg = (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 다음 주 분석 예고\n"
            f"📅 {now_str2}  |  {week_str}주\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            + (preview if preview else "다음 주 주요 이슈를 모니터링 후 분석 예정입니다.")
            + f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"월~금 낮 12시 분석 브리핑에서 다룹니다."
        )
        await send_telegram(msg)

    all_day = set(session.get("all_day", []))
    all_day.update(a["_hash"] for a in arts_all + arts_hw)
    save_json(SESSION_FILE, {"all_day": list(all_day)})

# ─────────────────────────────────────────────
# 스케줄러
# ─────────────────────────────────────────────
def run_scheduler():
    mode = "GPT-4o" if GITHUB_TOKEN else "자동 분석"
    logger.info(f"🚀 보험 통합 봇 시작! ({mode} 모드)")
    tz = pytz.timezone("Asia/Seoul")
    asyncio.run(send_notice())
    schedule.every().day.at("08:00", tz).do(lambda: asyncio.run(send_insight()))
    schedule.every().day.at("09:00", tz).do(lambda: asyncio.run(send_morning()))
    schedule.every().day.at("12:00", tz).do(lambda: asyncio.run(send_noon()))
    schedule.every().day.at("18:00", tz).do(lambda: asyncio.run(send_evening()))
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        exit(1)
    if not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_CHAT_ID가 설정되지 않았습니다.")
        exit(1)
    if not GITHUB_TOKEN:
        logger.warning("⚠️  GITHUB_TOKEN 없음 — GPT 분석 비활성화")
    run_scheduler()
