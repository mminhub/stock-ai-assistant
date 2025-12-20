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
# [1] 기본 설정 및 블랙박스 UI
# ==============================================================================
st.set_page_config(page_title="System Blackbox", layout="wide")

st.title("🛠️ AI 비서 (블랙박스 모드)")
st.caption("진행 상황을 실시간으로 중계합니다. 멈추면 어디서 멈췄는지 보세요.")

# 1. API 키 확인
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 API 키가 없습니다. Streamlit Secrets 설정을 확인하세요.")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]

# 👇 [핵심] 2.5가 막혔을 때를 대비해 1.5까지 투입 (총력전)
RELAY_MODELS = [
    "gemini-2.5-flash", 
    "gemini-2.0-flash", 
    "gemini-1.5-flash"
]

# ==============================================================================
# [2] 진행 상황 중계창 (Log Box)
# ==============================================================================
log_container = st.expander("📡 시스템 로그 (클릭해서 진행상황 보기)", expanded=True)

def log(msg, type="info"):
    """화면에 로그를 찍는 함수"""
    if type == "info": log_container.info(msg)
    elif type == "success": log_container.success(msg)
    elif type == "error": log_container.error(msg)
    elif type == "warn": log_container.warning(msg)

# ==============================================================================
# [3] 데이터 수집 및 AI 호출
# ==============================================================================
def clean_text(text):
    if not text: return ""
    return re.sub(r'[\[\]\{\}\"]', '', text).strip()

def fetch_market_and_news():
    log("1. 시장 데이터 수집 시작...")
    
    # 1. 주식
    try:
        tickers = ['^TNX', '^VIX', '^GSPC']
        df = yf.download(tickers, period="1d", progress=False)['Close']
        last = df.iloc[-1]
        log(f"✅ 주식 데이터 확보 완료 (S&P500: {last.get('^GSPC', 0):.2f})", "success")
    except Exception as e:
        last = None
        log(f"⚠️ 주식 데이터 실패: {e}", "warn")

    # 2. 뉴스
    log("2. 구글 뉴스 수집 시작...")
    try:
        keywords = "Fed OR Bitcoin OR Nvidia OR Tesla"
        rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(keywords)}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        
        if len(feed.entries) == 0:
            log("❌ 뉴스를 하나도 못 가져왔습니다. (서버 IP 차단됨)", "error")
            return last, []
            
        news = feed.entries[:5]
        log(f"✅ 뉴스 {len(news)}개 확보 완료", "success")
        return last, news
        
    except Exception as e:
        log(f"❌ 뉴스 수집 중 에러: {e}", "error")
        return last, []

def call_ai_final(prompt):
    log("3. AI 분석 엔진 가동...")
    
    # 모델 3개를 순서대로 시도
    for model in RELAY_MODELS:
        log(f"👉 [{model}] 모델에 접속 시도 중...")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(url, headers=headers, json=data, timeout=20)
            
            if res.status_code == 200:
                log(f"✅ [{model}] 응답 성공!", "success")
                return res.json()['candidates'][0]['content']['parts'][0]['text']
            
            elif res.status_code == 429:
                log(f"🚦 [{model}] 과부하(429) - 구글이 잠깐 쉬래요.", "warn")
                # 여기서 멈추지 않고 다음 모델(1.5)로 넘어감!
                continue
                
            else:
                log(f"❌ [{model}] 에러 발생: {res.status_code}\n{res.text}", "error")
                continue
                
        except Exception as e:
            log(f"❌ [{model}] 통신 오류: {e}", "error")
            continue
            
    return None

# ==============================================================================
# [4] 메인 로직
# ==============================================================================
def main():
    if 'result' not in st.session_state:
        # 데이터 수집
        last_data, news_list = fetch_market_and_news()
        
        if not news_list:
            st.error("뉴스를 가져오지 못해 분석을 중단합니다. (로그 확인)")
            st.stop()
            
        # 프롬프트 작성
        news_text = "\n".join([f"- {n.title}" for n in news_list])
        prompt = f"""
        ROLE: Expert Investor.
        TASK: Analyze these news headlines in KOREAN.
        
        NEWS:
        {news_text}
        
        OUTPUT FORMAT:
        [MARKET SCORE] (0-100)
        [ONE LINE VIEW] (Summary)
        [ANALYSIS]
        1. (News Title) -> (Buy/Sell/Hold) : Reason
        ...
        """
        
        # AI 호출
        ai_response = call_ai_final(prompt)
        
        if ai_response:
            st.session_state['result'] = ai_response
            st.rerun() # 성공하면 화면 새로고침해서 보여줌
        else:
            st.error("🚨 모든 AI 모델이 실패했습니다. 위 로그를 캡처해서 보여주세요.")
            st.stop()

    # 결과 화면 출력
    if 'result' in st.session_state:
        st.divider()
        st.subheader("📊 분석 결과")
        st.info(st.session_state['result'])
        
        if st.button("🔄 처음부터 다시 하기"):
            del st.session_state['result']
            st.rerun()

if __name__ == "__main__":
    main()