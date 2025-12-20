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

# API 키 확인
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 Secrets 설정이 비어있습니다!")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]

# 사용자님이 성공하셨다는 1.5 모델을 메인으로 씁니다
RELAY_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b"]

# ==============================================================================
# [2] AI 및 데이터 엔진 (디버깅 강화판)
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
                # [수정] 429 에러도 로그에 남김!
                msg = f"[{model}] 429 과부하 (Too Many Requests) - 서버가 바쁨"
                error_logs.append(msg)
                time.sleep(1)
                continue
            
            else:
                # 기타 에러
                msg = f"[{model}] Error {res.status_code}: {res.text}"
                error_logs.append(msg)
                continue
                
        except Exception as e:
            error_logs.append(f"[{model}] 통신 오류: {str(e)}")
            continue
            
    # 여기까지 왔다는 건 모든 모델이 실패했다는 뜻
    return None, "\n".join(error_logs)

@st.cache_data(ttl=600)
def fetch_market_data():
    # 1. 주식 데이터
    try:
        tickers = ['^TNX', '^VIX', 'BTC-USD', 'GC=F', '^GSPC', '^IXIC']
        df = yf.download(tickers, period="5d", progress=False)['Close'].ffill()
        last = df.iloc[-1]
        prev = df.iloc[-2]
        chg = ((last - prev) / prev) * 100
    except:
        last, chg = None, None

    # 2. 뉴스 데이터 (검색어 단순화)
    # 구글 뉴스 차단을 피하기 위해 검색어를 아주 단순하게 변경
    rss_url = "https://news.google.com/rss/search?q=Economy+Finance+Bitcoin&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            return last, chg, [] # 뉴스가 없으면 빈 리스트 반환
            
        scored_news = []
        for e in feed.entries[:5]: # 그냥 최신 5개 가져옴 (점수 로직 생략하여 에러 최소화)
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
PROMPT_BRIEFING = """
ROLE: Investor.
TASK: Analyze the news below in KOREAN.
FORMAT:
[MARKET SCORE] (0-100)
[UPCOMING EVENTS] (3 events)
[MARKET VIEW] (1 sentence)
[TRENDING ASSETS] (3 assets)
[NEWS ANALYSIS]
1. ACTION: (Buy/Sell/Hold) | REASON: ...
"""

PROMPT_DEEP = "Analyze in KOREAN.\nACTION: [Buy/Sell/Hold]\nSUMMARY: -Fact\nRISK: -Risk"

def parse_section(text, header):
    try:
        pattern = re.escape(header) + r"(.*?)(?=\n\[|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except:
        return ""

def main():
    st.title("☕ Strategic AI Partner")
    
    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 데이터 수집 중...")
        
        last, chg, news = fetch_market_data()
        
        # [핵심] 뉴스가 0개면 AI 호출하지 말고 멈춤 (에러 방지)
        if not news:
            status.error("❌ 구글 뉴스가 이 서버의 접속을 차단했습니다. (뉴스가 0개입니다)")
            st.warning("팁: 잠시 후 다시 시도하거나, Yahoo Finance 라이브러리로 교체해야 합니다.")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title}" for i, n in enumerate(news)])
        
        ai_res, error_log = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success("✅ 완료")
            time.sleep(1)
            status.empty()
        else:
            status.error("분석 실패! (아래 에러 내용을 보세요)")
            st.code(error_log) # 이제 여기에 429인지 뭔지 뜹니다!
            st.stop()

    # 결과 화면 (이전과 동일)
    last, chg, news = st.session_state.get('market_raw', (None, None, []))
    briefing = st.session_state.get('briefing_data', "")

    if last is not None:
        cols = st.columns(6)
        metrics = [("US 10Y", '^TNX'), ("VIX", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("Nasdaq", '^IXIC'), ("BTC", 'BTC-USD'), ("Gold", 'GC=F')]
        for i, (l, k) in enumerate(metrics):
            cols[i].metric(l, f"{last.get(k,0):,.2f}", f"{chg.get(k,0):.2f}%")

    st.divider()

    # 파싱 및 출력
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
            # 정밀 분석 로직 (간소화)
            body = get_article_content(n.link)
            det, err = call_ai_relay(f"{PROMPT_DEEP}\n{body}")
            if det: st.info(det)
            else: st.error(err)
        st.divider()

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()