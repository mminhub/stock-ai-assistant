import streamlit as st
import feedparser
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import time

# ==============================================================================
# [1] 설정
# ==============================================================================
st.set_page_config(page_title="Strategic AI Partner", layout="wide")

if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 API 키가 없습니다.")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]
RELAY_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

# 프롬프트: 형식을 좀 더 단순하게 요청 (오류 방지)
PROMPT_BRIEFING = """
You are a CIO. Analyze these 5 headlines.
Return result in KOREAN. Use this format:

[MARKET]
SCORE: (0-100)
VIEW: (One sentence summary)

[NEWS]
1. ACTION: (Buy/Sell/Hold) | REASON: (Reason)
2. ACTION: (Buy/Sell/Hold) | REASON: (Reason)
3. ACTION: (Buy/Sell/Hold) | REASON: (Reason)
4. ACTION: (Buy/Sell/Hold) | REASON: (Reason)
5. ACTION: (Buy/Sell/Hold) | REASON: (Reason)
"""

PROMPT_DEEP = """
Analyze this news. Format in Korean:
GRADE: [S/A/B/C]
ACTION: [매수/매도/관망] | [Reason]
PROBABILITY: [0-100] | [Trend] | [Impact]
SUMMARY: -Fact
RISK: -Risk
"""

# ==============================================================================
# [2] 유틸리티 (텍스트 청소 & AI 통신)
# ==============================================================================
def clean_text(text):
    """제목이나 내용에 붙은 이상한 기호 제거"""
    if not text: return ""
    # JSON 괄호, 따옴표 등 제거
    text = re.sub(r'[\[\]\{\}\"]', '', text)
    # 불필요한 공백 제거
    return text.strip()

def call_ai_relay(prompt):
    for model in RELAY_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            res = requests.post(url, headers=headers, json=data, timeout=20)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text'], model
            elif res.status_code == 429:
                time.sleep(2)
                continue
        except:
            continue
    return None, "AI 연결 실패"

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

    sites = "site:cnbc.com OR site:reuters.com OR site:bloomberg.com OR site:finance.yahoo.com"
    keywords = "Fed OR CPI OR Bitcoin OR Nvidia OR Tesla OR Apple OR Gold"
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(f'{keywords} {sites}')}&hl=en-US&gl=US&ceid=US:en"
    
    feed = feedparser.parse(rss_url)
    scored_news = []
    for e in feed.entries:
        # 제목 청소 (이상한 기호 방지)
        e.title = clean_text(e.title)
        
        score = 0
        t = e.title.lower()
        if any(w in t for w in ['fed', 'rate', 'cpi']): score += 5
        if any(w in t for w in ['bitcoin', 'nvidia', 'tesla']): score += 4
        if score > 0: scored_news.append(e)
    
    return last, chg, scored_news[:5]

def get_article_content(link):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(link, headers=headers, timeout=4)
        soup = BeautifulSoup(res.content, 'html.parser')
        text = ' '.join([p.get_text() for p in soup.find_all('p')])
        if len(text) > 200: return text[:3000]
    except:
        pass
    return "원문 접속 불가"

# ==============================================================================
# [3] 파싱 로직
# ==============================================================================
def parse_briefing(text):
    try:
        score = re.search(r'SCORE[:\s]*(\d+)', text).group(1)
        view = re.search(r'VIEW[:\s]*(.*)', text).group(1)
    except:
        score, view = "50", "분석 중..."
    return score, view

def parse_action(text, index):
    try:
        # 숫자 + . + ACTION 패턴 등을 유연하게 찾음
        pattern = f"{index}\.\s*ACTION[:\s]*(.*)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if not match: # 못 찾으면 다른 패턴 시도
             pattern = f"NEWS[\s_]*{index}[\s_]*ACTION[:\s]*(.*)"
             match = re.search(pattern, text, re.IGNORECASE)

        line = match.group(1) if match else "Hold | 대기"
        if "|" in line:
            return line.split("|", 1)
        return line, ""
    except:
        return "Hold", "Parsing Error"

# ==============================================================================
# [4] 메인 실행
# ==============================================================================
def main():
    st.title("☕ Strategic AI Partner")
    
    # [중요] 정밀 분석 결과를 저장할 금고(Dictionary) 초기화
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    # 1차 브리핑 (자동)
    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 시장 데이터 수집 및 분석 중... (약 15초)")
        
        last, chg, news = fetch_market_data()
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title} (Summary: {n.get('description','')[:150]})" for i, n in enumerate(news)])
        
        ai_res, used_model = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success(f"✅ 분석 완료! ({used_model})")
            time.sleep(1)
            status.empty()
        else:
            status.error("분석 실패. 잠시 후 새로고침 해주세요.")
            st.stop()

    last, chg, news = st.session_state['market_raw']
    briefing = st.session_state['briefing_data']

    # 시장 지표
    if last is not None:
        cols = st.columns(6)
        metrics = [("US 10Y", '^TNX'), ("VIX", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("Nasdaq", '^IXIC'), ("BTC", 'BTC-USD'), ("Gold", 'GC=F')]
        for i, (l, k) in enumerate(metrics):
            cols[i].metric(l, f"{last.get(k,0):,.2f}", f"{chg.get(k,0):.2f}%")

    st.divider()

    score, view = parse_briefing(briefing)
    c1, c2 = st.columns([1, 3])
    with c1: 
        st.metric("투자 날씨", f"{score}/100")
        st.progress(int(score))
    with c2: 
        st.info(f"🔭 {clean_text(view)}")

    st.subheader("📰 뉴스 브리핑")

    for i, n in enumerate(news):
        act, rsn = parse_action(briefing, i+1)
        color = "green" if "Buy" in act or "매수" in act else "red" if "Sell" in act or "매도" in act else "orange"
        
        with st.container():
            # 제목 출력 (이상한 기호 제거됨)
            clean_title = clean_text(n.title)
            st.markdown(f":{color}[●] **[{act.strip()}]** {clean_title}")
            st.caption(f"💡 {rsn.strip()}")
            st.markdown(f"[원문 보기]({n.link})")
            
            # [핵심] 정밀 분석 로직 (유지 기능 포함)
            # 1. 이미 분석한 적이 있는지 금고 확인
            if i in st.session_state['deep_results']:
                # 있으면 바로 보여줌 (버튼 안 눌러도 유지됨)
                st.info(f"✅ 분석 완료 ({st.session_state['deep_results'][i]['model']})")
                st.markdown(st.session_state['deep_results'][i]['content'])
                
                # 다시 분석하고 싶을 때를 위한 버튼
                if st.button("다시 분석", key=f"re_deep_{i}"):
                    del st.session_state['deep_results'][i]
                    st.rerun()
            
            else:
                # 2. 분석한 적 없으면 버튼 표시
                if st.button("정밀 분석", key=f"deep_{i}"):
                    with st.spinner("분석 중..."):
                        body = get_article_content(n.link)
                        if "불가" in body: body = n.get('description', '')
                        
                        detail, u_model = call_ai_relay(f"{PROMPT_DEEP}\nTitle: {n.title}\nBody: {body}")
                        
                        if detail:
                            # 3. 결과 나오면 금고에 저장!
                            st.session_state['deep_results'][i] = {
                                'content': detail,
                                'model': u_model
                            }
                            st.rerun() # 화면 새로고침해서 저장된 거 보여주기
                        else:
                            st.error("분석 실패")
        st.divider()

    if st.button("🔄 전체 초기화"):
        st.cache_data.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if __name__ == "__main__":
    main()