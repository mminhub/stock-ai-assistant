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
# [1] 설정 & 보안 (로그인 시스템)
# ==============================================================================
st.set_page_config(page_title="Strategic AI Partner (Secure)", layout="wide")

# 1-1. 비밀번호 확인 함수 (철통 보안)
def check_password():
    """비밀번호가 맞는지 확인하는 문지기 함수"""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🔒 보안 접속 (Authorized Access Only)")
    password = st.text_input("비밀번호를 입력하세요", type="password")
    
    if st.button("로그인"):
        # Secrets에 설정된 비번과 비교
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            st.rerun() # 맞으면 새로고침해서 통과
        else:
            st.error("❌ 비밀번호가 틀렸습니다. 접근이 거부됩니다.")
            
    return False

# 1-2. 문지기 세우기 (여기서 막히면 아래 코드는 실행조차 안 됨)
if "APP_PASSWORD" not in st.secrets:
    st.error("🚨 Secrets에 'APP_PASSWORD'가 설정되지 않았습니다.")
    st.stop()

if not check_password():
    st.stop() # 비밀번호 틀리면 여기서 프로그램 강제 종료

# ---------------- (통과한 사람만 아래 내용을 볼 수 있음) ----------------

if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 Secrets 설정이 비어있습니다!")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]
RELAY_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-exp"]

# ==============================================================================
# [2] 스마트 대기 엔진
# ==============================================================================
def clean_text(text):
    if not text: return ""
    return re.sub(r'[\[\]\{\}\"]', '', text).strip()

def call_ai_with_visual_wait(prompt):
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
                    wait_seconds = 20 * (attempt + 1)
                    with st.status(f"🚦 서버 혼잡! {wait_seconds}초 대기 중... ({model})", expanded=True):
                        progress_bar = st.progress(0)
                        for i in range(wait_seconds):
                            time.sleep(1)
                            progress_bar.progress((i + 1) / wait_seconds)
                    continue
                else:
                    continue
            except Exception:
                continue
    return None, "❌ 분석 실패 (구글 서버 응답 없음)"

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

def get_article_content(link):
    try:
        res = requests.get(link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=4)
        soup = BeautifulSoup(res.content, 'html.parser')
        text = ' '.join([p.get_text() for p in soup.find_all('p')])
        if len(text) > 200: return text[:2000]
    except:
        pass
    return "원문 접속 불가"

# ==============================================================================
# [3] 메인 UI
# ==============================================================================
PROMPT_BRIEFING = f"""
ROLE: CIO.
DATE: {datetime.now().strftime('%Y-%m-%d')}
TASK: Analyze news in KOREAN.
FORMAT:
[MARKET SCORE] (0-100)
[UPCOMING EVENTS] (3 items)
[MARKET VIEW] (1 line)
[TRENDING ASSETS] (3 items)
[NEWS ANALYSIS]
1. ACTION: (Buy/Sell/Hold) | REASON: ...
"""

PROMPT_DEEP = "Analyze in KOREAN.\nACTION: [Buy/Sell/Hold] | [Reason]\nSUMMARY: -Fact\nRISK: -Risk"

def parse_section(text, header):
    try:
        pattern = re.escape(header) + r"(.*?)(?=\n\[|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except:
        return ""

def main():
    # 사이드바에 로그아웃 버튼 추가
    with st.sidebar:
        st.write("🔐 **보안 접속됨**")
        if st.button("로그아웃"):
            st.session_state["password_correct"] = False
            st.rerun()

    st.title("☕ Strategic AI Partner (Secure)")
    
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 시장 분석 중...")
        last, chg, news = fetch_market_data()
        
        if not news:
            status.error("❌ 뉴스 수집 불가")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        news_txt = "\n".join([f"[{i+1}] {n.title}" for i, n in enumerate(news)])
        
        ai_res, success_model = call_ai_with_visual_wait(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success(f"✅ 완료 ({success_model})")
            time.sleep(1)
            status.empty()
        else:
            status.error("분석 실패 (서버 혼잡)")
            st.stop()

    last, chg, news = st.session_state.get('market_raw', (None, None, []))
    briefing = st.session_state.get('briefing_data', "")

    if last is not None:
        cols = st.columns(6)
        metrics = [("US 10Y", '^TNX'), ("VIX", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("Nasdaq", '^IXIC'), ("BTC", 'BTC-USD'), ("Gold", 'GC=F')]
        for i, (l, k) in enumerate(metrics):
            cols[i].metric(l, f"{last.get(k,0):,.2f}", f"{chg.get(k,0):.2f}%")

    st.divider()

    score_txt = parse_section(briefing, "[MARKET SCORE]")
    view_txt = parse_section(briefing, "[MARKET VIEW]")
    events_txt = parse_section(briefing, "[UPCOMING EVENTS]")
    trending_txt = parse_section(briefing, "[TRENDING ASSETS]")
    
    c1, c2 = st.columns([1, 3])
    with c1:
        st.metric("Risk Score", score_txt[:3] if score_txt else "50")
    with c2:
        st.info(view_txt if view_txt else "분석 내용 없음")
        
    with st.expander("📅 일정 & 🚀 트렌드", expanded=True):
        st.write(events_txt)
        st.divider()
        st.write(trending_txt)

    st.divider()
    for i, n in enumerate(news):
        st.markdown(f"**{i+1}. {n.title}**")
        st.caption(f"[원문]({n.link})")
        if st.button("정밀 분석", key=f"d_{i}"):
            if i in st.session_state.get('deep_results', {}):
                st.info("✅ 저장된 분석")
                st.markdown(st.session_state['deep_results'][i])
            else:
                body = get_article_content(n.link)
                det, succ_model = call_ai_with_visual_wait(f"{PROMPT_DEEP}\n{body}")
                if det: 
                    st.session_state['deep_results'][i] = det
                    st.success(f"완료 ({succ_model})")
                    st.rerun()
                else: 
                    st.error("분석 실패")
        st.divider()

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        if 'briefing_data' in st.session_state: del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()