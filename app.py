import streamlit as st
import feedparser
import yfinance as yf
import requests
import re
import time
from datetime import datetime
import urllib.parse
from bs4 import BeautifulSoup

# ==============================================================================
# [1] 설정 & 보안
# ==============================================================================
st.set_page_config(page_title="AI 주식 과외 선생님 (Original Only)", layout="wide")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True
    
    st.title("🔒 로그인")
    password = st.text_input("비밀번호", type="password")
    if st.button("접속"):
        if "APP_PASSWORD" in st.secrets and password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
    return False

if "APP_PASSWORD" in st.secrets:
    if not check_password(): st.stop()

if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 Secrets 설정이 비어있습니다!")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]
RELAY_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-exp"]

# ==============================================================================
# [2] AI 엔진 (원문 분석 필수)
# ==============================================================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'[\[\]\{\}\"]', '', text).strip()

def call_ai_relay(prompt):
    max_retries = 3
    for attempt in range(max_retries):
        for model in RELAY_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
            headers = {'Content-Type': 'application/json'}
            data = {"contents": [{"parts": [{"text": prompt}]}]}
            
            try:
                res = requests.post(url, headers=headers, json=data, timeout=30)
                if res.status_code == 200:
                    return res.json()['candidates'][0]['content']['parts'][0]['text'], model
                elif res.status_code == 429:
                    time.sleep(5)
                    continue
                else:
                    continue
            except:
                continue
    return None, "서버 응답 없음"

@st.cache_data(ttl=600)
def fetch_market_data():
    try:
        tickers = ['^TNX', '^VIX', 'BTC-USD', 'GC=F', '^GSPC', '^IXIC']
        df = yf.download(tickers, period="5d", progress=False)['Close'].ffill()
        last = df.iloc[-1]
        prev = df.iloc[-2]
        chg = ((last - prev) / prev) * 100
    except:
        last, chg = None, None

    # 구글 뉴스
    rss_url = "https://news.google.com/rss/search?q=Finance+Stock&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return last, chg, []
        scored_news = []
        for e in feed.entries[:3]:
            e.title = clean_text(e.title)
            scored_news.append(e)
        return last, chg, scored_news
    except:
        return last, chg, []

# 👇 [핵심 수정] 은신술(Stealth) 기술 적용 함수
def get_article_content(link):
    """
    뉴스 사이트의 차단을 뚫고 진짜 원문을 가져오는 함수.
    1. 헤더 위조 (사람인 척)
    2. 세션 유지
    3. 최종 URL 추적
    """
    # 1. 완벽한 사람 흉내 (크롬 브라우저 헤더)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8',
        'Referer': 'https://www.google.com/'
    }
    
    try:
        # 세션 시작 (쿠키 유지)
        session = requests.Session()
        
        # 2. 구글 뉴스 링크 접속 -> 진짜 뉴스 사이트로 리다이렉트 추적
        res = session.get(link, headers=headers, timeout=10, allow_redirects=True)
        
        # 접속 성공 (200 OK)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, 'html.parser')
            
            # 3. 본문 추출 알고리즘 (p 태그만 싹 긁어모으기)
            paragraphs = soup.find_all('p')
            
            # 너무 짧은 문장(광고, 메뉴 등)은 버리고, 긴 문장만 수집
            text_content = []
            for p in paragraphs:
                text = p.get_text().strip()
                if len(text) > 30: # 30자 이상인 의미 있는 문장만
                    text_content.append(text)
            
            full_text = ' '.join(text_content)
            
            if len(full_text) > 200: 
                return f"[원문 확보 성공]\n{full_text[:3500]}" # 너무 길면 3500자에서 자름
            else:
                return f"Error: 본문을 찾았으나 내용이 너무 짧습니다. (보안이 강력한 사이트일 수 있음)\nStatus: {res.status_code}"
                
        else:
            return f"Error: 사이트 접속 거부 (Status Code: {res.status_code})"
            
    except Exception as e:
        return f"Error: 크롤링 중 에러 발생 ({str(e)})"

# ==============================================================================
# [3] 프롬프트 (엄격한 분석)
# ==============================================================================
PROMPT_BRIEFING = f"""
ROLE: Friendly Investment Tutor.
DATE: {datetime.now().strftime('%Y-%m-%d')}
TASK: Analyze news headlines in KOREAN.

FORMAT:
[시장 점수] (0~100)
[주요 일정] (3 items)
[시장 한줄평] (Friendly tone)
[요즘 뜨는 테마] (3 items)
[뉴스 3줄 요약]
1. (Title) -> (호재/악재)
"""

PROMPT_DEEP = """
ROLE: Investment Tutor.
TASK: Analyze the **ORIGINAL ARTICLE TEXT** provided below.
LANGUAGE: **KOREAN ONLY**.

🚨 **INSTRUCTION:**
1. Analyze based ONLY on the provided text.
2. If the text starts with "Error:", explain WHY you cannot analyze (e.g., "Site blocked access").
3. Do NOT guess if there is an Error.

OUTPUT FORMAT:
**📢 판단:** [매수 / 매도 / 관망]
**💡 이유:** (Summarize the key facts from the text)
**📉 리스크:** (Risks mentioned in the text)

---
**🔰 주린이 용어 사전**
(Explain 2 difficult terms found in the text)
"""

def parse_section(text, header):
    try:
        pattern = re.escape(header) + r"(.*?)(?=\n\[|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except:
        return ""

# ==============================================================================
# [4] 메인 UI
# ==============================================================================
def main():
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        with st.sidebar:
            if st.button("로그아웃"):
                st.session_state["password_correct"] = False
                st.rerun()

    st.title("🎓 AI 주식 과외 선생님 (정밀 분석반)")
    st.caption("뉴스 원문을 직접 뚫고 들어가서 팩트만 분석합니다.")
    
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 뉴스 헤드라인 수집 중...")
        last, chg, news = fetch_market_data()
        
        if not news:
            status.error("❌ 뉴스 수집 실패")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title}" for i, n in enumerate(news)])
        ai_res, _ = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            status.empty()
        else:
            status.error("서버 혼잡 (잠시 후 다시 시도)")
            st.stop()

    last, chg, news = st.session_state.get('market_raw', (None, None, []))
    briefing = st.session_state.get('briefing_data', "")

    if last is not None:
        cols = st.columns(6)
        metrics = [("미국 국채 10년", '^TNX'), ("공포지수(VIX)", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("나스닥", '^IXIC'), ("비트코인", 'BTC-USD'), ("금", 'GC=F')]
        for i, (label, ticker) in enumerate(metrics):
            val = last.get(ticker, 0)
            c = chg.get(ticker, 0)
            cols[i].metric(label, f"{val:,.2f}", f"{c:+.2f}%")

    st.divider()

    score_txt = parse_section(briefing, "[시장 점수]")
    view_txt = parse_section(briefing, "[시장 한줄평]")
    events_txt = parse_section(briefing, "[주요 일정]")
    trending_txt = parse_section(briefing, "[요즘 뜨는 테마]")
    news_summary_txt = parse_section(briefing, "[뉴스 3줄 요약]")

    c1, c2 = st.columns([1, 3])
    with c1:
        st.metric("오늘의 시장 점수", score_txt[:3] if score_txt else "50")
    with c2:
        st.info(f"🗣️ {view_txt}")

    with st.expander("📅 일정 & 테마", expanded=True):
        c_a, c_b = st.columns(2)
        c_a.write(events_txt)
        c_b.write(trending_txt)

    st.divider()
    if news_summary_txt: st.write(news_summary_txt)

    for i, n in enumerate(news):
        st.divider()
        st.markdown(f"#### {i+1}. {n.title}")
        st.caption(f"링크: {n.link}")
        
        if st.button(f"📖 {i+1}번 뉴스 원문 분석", key=f"btn_{i}"):
            with st.spinner("🕵️‍♂️ 원문 사이트 잠입 중... (차단 우회 시도)"):
                # [핵심] 은신술 함수 호출
                body = get_article_content(n.link)
                
                # 원문 획득 성공 여부 확인
                if "Error:" in body:
                    st.error(f"⚠️ 원문 접속 실패: {body}")
                    st.warning("이 사이트는 보안이 너무 강력해서 로봇 접속을 완벽히 차단했습니다.")
                else:
                    det, _ = call_ai_relay(f"{PROMPT_DEEP}\n{body}")
                    if det:
                        st.session_state['deep_results'][i] = det
                        st.rerun()
                    else:
                        st.error("AI 분석 실패")

        if i in st.session_state['deep_results']:
            with st.chat_message("assistant"):
                st.markdown(st.session_state['deep_results'][i])

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        if 'briefing_data' in st.session_state: del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()