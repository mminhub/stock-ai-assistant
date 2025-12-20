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
# [1] 설정
# ==============================================================================
st.set_page_config(page_title="Strategic AI Partner", layout="wide")

if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 Secrets 설정이 비어있습니다!")
    st.info("Streamlit 사이트 설정(Settings) -> Secrets 메뉴에 GOOGLE_API_KEY를 넣어주세요.")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]

# 👇 [요청하신 전략 적용]
# 1순위: 2.5 (Target)
# 2순위: 2.0 계열 (Backup)
RELAY_MODELS = [
    "gemini-2.5-flash",       # 메인 타겟
    "gemini-2.0-flash-exp",   # 1차 보조
    "gemini-2.0-flash"        # 2차 보조 (비상용)
]

# ==============================================================================
# [2] AI 및 데이터 엔진
# ==============================================================================
def clean_text(text):
    if not text: return ""
    return re.sub(r'[\[\]\{\}\"]', '', text).strip()

def call_ai_relay(prompt):
    error_logs = [] 
    
    # 모델 리스트를 순서대로 실행 (릴레이)
    for model in RELAY_MODELS:
        # v1beta 사용
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            # 타임아웃 30초
            res = requests.post(url, headers=headers, json=data, timeout=30)
            
            if res.status_code == 200:
                # 성공하면 바로 결과와 모델명 리턴하고 종료
                return res.json()['candidates'][0]['content']['parts'][0]['text'], model
            
            elif res.status_code == 429:
                # 2.5가 과부하면 -> 2초만 쉬고 바로 2.0으로 넘김 (기다리는 시간 단축)
                time.sleep(2)
                error_logs.append(f"[{model}] 429 과부하 -> 다음 타자 교체")
                continue
            
            else:
                # 404나 기타 에러면 -> 바로 다음 모델로 넘김
                error_logs.append(f"[{model}] Error {res.status_code}: {res.text}")
                continue
                
        except Exception as e:
            error_logs.append(f"[{model}] 통신 오류: {str(e)}")
            continue
            
    # 여기까지 왔다는 건 2.5, 2.0 전부 다 실패했다는 뜻
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

    # 구글 뉴스 (검색어 심플하게 유지)
    rss_url = "https://news.google.com/rss/search?q=Economy+Finance+Bitcoin&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return last, chg, []
            
        scored_news = []
        for e in feed.entries[:5]:
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
        if len(text) > 200: return text[:3000]
    except:
        pass
    return "원문 접속 불가"

# ==============================================================================
# [3] UI 로직
# ==============================================================================
PROMPT_BRIEFING = f"""
ROLE: Conservative CIO.
DATE: {datetime.now().strftime('%Y-%m-%d')}
INSTRUCTION: Analyze news. Output in KOREAN.
FORMAT:
[MARKET SCORE] (0-100)
[UPCOMING EVENTS] (3 events)
[MARKET VIEW] (1 sentence)
[TRENDING ASSETS] (3 assets)
[NEWS ANALYSIS]
1. ACTION: (Buy/Sell/Hold) | REASON: ...
"""

PROMPT_DEEP = """
Analyze in KOREAN.
GRADE: [S/A/B/C]
ACTION: [매수/매도/관망] | [Reason]
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
    st.title("☕ Strategic AI Partner")
    st.caption("Target: Gemini 2.5 / Backup: Gemini 2.0")
    
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 2.5 모델 호출 중... (실패 시 2.0 전환)")
        last, chg, news = fetch_market_data()
        
        if not news:
            status.error("❌ 뉴스 수집 실패 (잠시 후 다시 시도)")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title} ({n.get('published', '')})" for i, n in enumerate(news)])
        
        # 여기서 릴레이 호출 시작
        ai_res, success_model = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success(f"✅ 완료! (수행한 모델: {success_model})")
            time.sleep(1)
            status.empty()
        else:
            status.error("모든 모델(2.5, 2.0)이 응답하지 않습니다.")
            st.warning("현재 구글 서버 요청량이 많습니다. 30초 뒤에 다시 시도해주세요.")
            st.code(success_model) # 여기에 에러 로그 출력
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
                # 정밀 분석도 똑같이 릴레이 적용
                det, succ_model = call_ai_relay(f"{PROMPT_DEEP}\n{body}")
                if det: 
                    st.session_state['deep_results'][i] = det
                    st.success(f"분석 완료 ({succ_model})")
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