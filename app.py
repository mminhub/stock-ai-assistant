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
# [1] 설정 (Lite 모드)
# ==============================================================================
st.set_page_config(page_title="Strategic AI Partner (Lite)", layout="wide")

if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 Secrets 설정이 비어있습니다!")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]

# 전략: 2.5 -> 2.0 (그대로 유지하되 가볍게 요청)
RELAY_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash-exp"]

# ==============================================================================
# [2] AI 엔진 (다이어트 버전)
# ==============================================================================
def clean_text(text):
    if not text: return ""
    return re.sub(r'[\[\]\{\}\"]', '', text).strip()

def call_ai_relay(prompt):
    error_logs = [] 
    
    for model in RELAY_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(url, headers=headers, json=data, timeout=30)
            
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text'], model
            
            elif res.status_code == 429:
                # [수정] 대기 시간을 10초로 대폭 늘림 (확실하게 쉬었다 가기)
                time.sleep(10)
                error_logs.append(f"[{model}] 과부하 -> 10초 대기 후 교체")
                continue
            
            else:
                error_logs.append(f"[{model}] Error {res.status_code}")
                continue
                
        except Exception as e:
            error_logs.append(f"[{model}] Error: {str(e)}")
            continue
            
    return None, "\n".join(error_logs)

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

    # [수정] 뉴스 검색어도 최대한 짧게
    rss_url = "https://news.google.com/rss/search?q=Finance+Stock&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return last, chg, []
            
        scored_news = []
        # [핵심 수정] 뉴스를 3개만 가져옴 (토큰 절약)
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
        if len(text) > 200: return text[:2000] # [수정] 본문 길이도 2000자로 제한
    except:
        pass
    return "원문 접속 불가"

# ==============================================================================
# [3] UI 로직
# ==============================================================================
# [수정] 프롬프트도 다이어트 (짧고 굵게)
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

PROMPT_DEEP = """
Analyze in KOREAN.
ACTION: [Buy/Sell/Hold] | [Reason]
SUMMARY: -Fact
RISK: -Risk
"""

def parse_section(text, header):
    try:
        pattern = re.escape(header) + r"(.*?)(?=\n\[|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except:
        return ""

def main():
    st.title("☕ Strategic AI Partner (Lite)")
    
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 가벼운 모드로 분석 중...")
        last, chg, news = fetch_market_data()
        
        if not news:
            status.error("❌ 뉴스 수집 실패")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title}" for i, n in enumerate(news)])
        
        ai_res, success_model = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success(f"✅ 완료 ({success_model})")
            time.sleep(1)
            status.empty()
        else:
            status.error("현재 서버 혼잡도가 매우 높습니다. (429 Error)")
            st.warning("팁: 우측 상단 'Reboot app'을 눌러서 서버(IP)를 바꿔보세요.")
            st.code(success_model)
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
                det, succ_model = call_ai_relay(f"{PROMPT_DEEP}\n{body}")
                if det: 
                    st.session_state['deep_results'][i] = det
                    st.success(f"완료 ({succ_model})")
                    st.rerun()
                else: 
                    st.error(succ_model)
        st.divider()

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        if 'briefing_data' in st.session_state: del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()