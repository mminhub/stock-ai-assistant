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
# [1] 설정 (Secrets에서 키를 가져오는 안전한 방식)
# ==============================================================================
st.set_page_config(page_title="Strategic AI Partner", layout="wide")

# 여기서 Secrets를 확인합니다. 없으면 에러를 띄웁니다.
if "GOOGLE_API_KEY" not in st.secrets:
    st.error("🚨 'Secrets' 설정이 비어있습니다!")
    st.info("Streamlit 사이트 설정(Settings) -> Secrets 메뉴에 GOOGLE_API_KEY를 넣어주세요.")
    st.stop()

API_KEY = st.secrets["GOOGLE_API_KEY"]
RELAY_MODELS = ["gemini-1.5-flash"]

# ==============================================================================
# [2] 프롬프트 및 유틸리티
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
                time.sleep(2)
                continue
            else:
                error_logs.append(f"[{model}] Error {res.status_code}: {res.text}")
                continue
        except Exception as e:
            error_logs.append(f"[{model}] Exception: {str(e)}")
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

    sites = "site:cnbc.com OR site:reuters.com OR site:bloomberg.com OR site:finance.yahoo.com"
    keywords = "Fed OR CPI OR Bitcoin OR Nvidia OR Tesla OR Apple OR Gold OR Earnings"
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(f'{keywords} {sites}')}&hl=en-US&gl=US&ceid=US:en"
    
    feed = feedparser.parse(rss_url)
    
    sorted_entries = sorted(
        feed.entries, 
        key=lambda x: x.get('published_parsed', time.struct_time((2000,1,1,0,0,0,0,0,0))), 
        reverse=True
    )
    
    scored_news = []
    for e in sorted_entries:
        e.title = clean_text(e.title)
        scored_news.append(e)
        if len(scored_news) >= 5: break
    
    return last, chg, scored_news

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

def parse_section(text, header):
    try:
        pattern = re.escape(header) + r"(.*?)(?=\n\[|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    except:
        return ""

def parse_briefing(text):
    score = parse_section(text, "[MARKET SCORE]")
    events = parse_section(text, "[UPCOMING EVENTS]")
    view = parse_section(text, "[MARKET VIEW]")
    trending = parse_section(text, "[TRENDING ASSETS]")
    return score, events, view, trending

def parse_action(text, index):
    try:
        pattern = f"{index}\.\s*ACTION[:\s]*(.*)"
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
             pattern = f"NEWS[\s_]*{index}[\s_]*ACTION[:\s]*(.*)"
             match = re.search(pattern, text, re.IGNORECASE)
        line = match.group(1) if match else "Hold | 대기"
        if "|" in line:
            return line.split("|", 1)
        return line, ""
    except:
        return "Hold", "Parsing Error"

# ==============================================================================
# [3] 메인 UI
# ==============================================================================
def main():
    st.title("☕ Strategic AI Partner")
    
    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 분석 중... (잠시만 기다려주세요)")
        last, chg, news = fetch_market_data()
        st.session_state['market_raw'] = (last, chg, news)
        
        news_txt = "\n".join([f"[{i+1}] {n.title} ({n.get('published', '')})" for i, n in enumerate(news)])
        
        ai_res, error_log = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            st.success("✅ 완료")
            time.sleep(1)
            status.empty()
        else:
            status.error("분석 실패! (아래 에러 메시지를 확인하세요)")
            st.code(error_log)
            st.stop()

    last, chg, news = st.session_state['market_raw']
    briefing = st.session_state['briefing_data']

    if last is not None:
        cols = st.columns(6)
        metrics = [("US 10Y", '^TNX'), ("VIX", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("Nasdaq", '^IXIC'), ("BTC", 'BTC-USD'), ("Gold", 'GC=F')]
        for i, (l, k) in enumerate(metrics):
            cols[i].metric(l, f"{last.get(k,0):,.2f}", f"{chg.get(k,0):.2f}%")

    st.divider()

    score_txt, events_txt, view_txt, trending_txt = parse_briefing(briefing)

    c1, c2 = st.columns([1, 3])
    with c1: 
        try:
            score_val = int(re.search(r'\d+', score_txt).group())
        except: score_val = 50
        st.metric("Risk Score", f"{score_val}/100")
        st.progress(score_val)
    with c2: 
        st.info(f"🔭 {view_txt}")

    with st.expander("📅 주요 일정 (Calendar)", expanded=True):
        st.markdown(events_txt)
    with st.expander("🚀 급부상 자산 (Trending)", expanded=True):
        st.markdown(trending_txt)

    st.divider()
    st.subheader("📰 뉴스 분석")

    for i, n in enumerate(news):
        act, rsn = parse_action(briefing, i+1)
        color = "green" if "Buy" in act or "매수" in act else "red" if "Sell" in act or "매도" in act else "orange"
        
        with st.container():
            st.markdown(f":{color}[●] **[{act.strip()}]** {n.title}")
            st.caption(f"💡 {rsn.strip()}")
            st.markdown(f"[원문 보기]({n.link})")
            
            if i in st.session_state['deep_results']:
                st.info("✅ 분석 완료")
                st.markdown(st.session_state['deep_results'][i]['content'])
                if st.button("다시 분석", key=f"re_deep_{i}"):
                    del st.session_state['deep_results'][i]
                    st.rerun()
            else:
                if st.button("정밀 분석", key=f"deep_{i}"):
                    with st.spinner("분석 중..."):
                        body = get_article_content(n.link)
                        if "불가" in body: body = n.get('description', '')
                        detail, u_model = call_ai_relay(f"{PROMPT_DEEP}\nTitle: {n.title}\nBody: {body}")
                        if detail:
                            st.session_state['deep_results'][i] = {'content': detail, 'model': u_model}
                            st.rerun()
                        else:
                            st.error(u_model)
        st.divider()

    if st.button("🔄 새로고침"):
        st.cache_data.clear()
        del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()