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
st.set_page_config(page_title="AI 주식 과외 선생님", layout="wide")

# 1. 로그인 (보안)
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]:
        return True
    
    st.title("🔒 로그인 (Authorized Access Only)")
    password = st.text_input("비밀번호를 입력하세요", type="password")
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
# [2] AI 엔진 (한국어 & 용어 설명 특화)
# ==============================================================================
def clean_text(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', text) # HTML 태그 제거
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
                    wait_time = 10 * (attempt + 1)
                    # UI에 방해되지 않게 조용히 대기
                    time.sleep(wait_time) 
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

    # 구글 뉴스 (영어 뉴스지만 AI가 한국어로 번역할 것임)
    rss_url = "https://news.google.com/rss/search?q=Finance+Stock+Market&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return last, chg, []
        scored_news = []
        for e in feed.entries[:3]:
            # [핵심] 제목과 함께 '요약(Snippet)'도 미리 저장해둠 (원문 접속 실패 대비)
            e.title = clean_text(e.title)
            e['summary_clean'] = clean_text(e.get('summary', ''))
            scored_news.append(e)
        return last, chg, scored_news
    except:
        return last, chg, []

def get_article_content(link, summary_backup):
    """
    원문 크롤링을 시도하되, 실패하면 RSS에 있던 요약본을 리턴합니다.
    절대 빈 손으로 돌아가지 않습니다.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(link, headers=headers, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, 'html.parser')
            text = ' '.join([p.get_text() for p in soup.find_all('p')])
            if len(text) > 200: 
                return text[:2500] # 너무 길면 자름
    except:
        pass
    
    # 크롤링 실패 시, 백업해둔 요약본 리턴 (비상용)
    return f"[원문 접속 차단됨. 요약본으로 대체합니다]\n{summary_backup}"

# ==============================================================================
# [3] 프롬프트 (한국어 강제 & 용어 설명 추가)
# ==============================================================================
PROMPT_BRIEFING = f"""
You are a friendly AI Investment Tutor for a college student beginner.
Current Date: {datetime.now().strftime('%Y-%m-%d')}

TASK: Analyze the news headlines and summaries below.
LANGUAGE: **KOREAN ONLY** (Translate everything to Korean).

FORMAT:
[시장 점수] (0~100점, 점수가 높을수록 안전/호황)
[주요 일정] (앞으로 있을 경제 일정 3개)
[시장 한줄평] (친구에게 말하듯 쉬운 말투로)
[요즘 뜨는 테마] (주목할만한 섹터 3개)
[뉴스 3줄 요약]
1. (뉴스 제목) -> (호재/악재/중립) : 이유
2. ...
3. ...
"""

PROMPT_DEEP = """
You are a friendly Investment Tutor.
Analyze the provided text in **KOREAN**.

Target Audience: A college student who is new to stocks.
1. **Translate** complex financial terms into easy Korean concepts.
2. If the text is short (summary only), analyze based on that.

OUTPUT FORMAT:
**📢 판단:** [매수 / 매도 / 관망]
**💡 이유:** (초보자가 이해하기 쉽게 설명)
**📉 리스크:** (조심해야 할 점)

---
**🔰 주린이 용어 사전**
(Pick 2-3 difficult financial terms from the text and explain them simply. 
Example: 'CPI' means Consumer Price Index, which shows inflation...)
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

    st.title("🎓 내 손안의 AI 주식 과외 선생님")
    st.caption("어려운 영어 뉴스도 한국어로 쉽게, 모르는 용어는 친절하게!")

    if 'deep_results' not in st.session_state:
        st.session_state['deep_results'] = {}

    if 'briefing_data' not in st.session_state:
        status = st.info("🔄 선생님이 뉴스 읽는 중... (잠시만 기다려주세요)")
        last, chg, news = fetch_market_data()
        
        if not news:
            status.error("❌ 뉴스를 가져오지 못했어요.")
            st.stop()
            
        st.session_state['market_raw'] = (last, chg, news)
        
        # 제목 + 요약본을 같이 보냄
        news_txt = "\n".join([f"[{i+1}] {n.title}\n(Summary: {n.summary_clean})" for i, n in enumerate(news)])
        
        ai_res, _ = call_ai_relay(f"{PROMPT_BRIEFING}\n{news_txt}")
        
        if ai_res:
            st.session_state['briefing_data'] = ai_res
            status.empty()
            st.toast("분석이 완료되었습니다!")
        else:
            status.error("분석에 실패했습니다. (서버 혼잡)")
            st.stop()

    last, chg, news = st.session_state.get('market_raw', (None, None, []))
    briefing = st.session_state.get('briefing_data', "")

    # 지표 표시
    if last is not None:
        cols = st.columns(6)
        metrics = [("미국 국채 10년", '^TNX'), ("공포지수(VIX)", '^VIX'), ("S&P 500", '^GSPC'), 
                   ("나스닥", '^IXIC'), ("비트코인", 'BTC-USD'), ("금", 'GC=F')]
        for i, (label, ticker) in enumerate(metrics):
            val = last.get(ticker, 0)
            c = chg.get(ticker, 0)
            cols[i].metric(label, f"{val:,.2f}", f"{c:+.2f}%")

    st.divider()

    # 파싱
    score_txt = parse_section(briefing, "[시장 점수]")
    view_txt = parse_section(briefing, "[시장 한줄평]")
    events_txt = parse_section(briefing, "[주요 일정]")
    trending_txt = parse_section(briefing, "[요즘 뜨는 테마]")
    news_summary_txt = parse_section(briefing, "[뉴스 3줄 요약]")

    # 메인 대시보드
    c1, c2 = st.columns([1, 3])
    with c1:
        try:
            score = int(re.search(r'\d+', score_txt).group())
        except: score = 50
        st.metric("오늘의 시장 점수", f"{score}점")
        st.progress(score)
    with c2:
        st.info(f"🗣️ **선생님 한마디:** {view_txt}")

    with st.expander("📅 주요 일정 & 테마 보따리", expanded=True):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**[주요 일정]**")
            st.write(events_txt)
        with col_b:
            st.markdown("**[뜨는 테마]**")
            st.write(trending_txt)

    st.divider()
    st.subheader("📚 오늘의 뉴스 수업")
    
    # 전체 요약 먼저 보여주기
    if news_summary_txt:
        st.markdown(news_summary_txt)
        st.divider()

    # 개별 뉴스 카드
    for i, n in enumerate(news):
        with st.container():
            st.markdown(f"#### {i+1}. {n.title}")
            st.caption(f"원본 링크: {n.link}")
            
            # 정밀 분석 버튼
            if st.button(f"📖 {i+1}번 뉴스 자세히 배우기", key=f"btn_{i}"):
                with st.spinner("선생님이 원문 읽고 쉽게 풀이하는 중..."):
                    # 원문 접속 시도 -> 실패하면 요약본 사용 (안전장치)
                    body_content = get_article_content(n.link, n.summary_clean)
                    
                    detail, _ = call_ai_relay(f"{PROMPT_DEEP}\nTitle: {n.title}\nContent: {body_content}")
                    
                    if detail:
                        st.session_state['deep_results'][i] = detail
                        st.rerun()
                    else:
                        st.error("분석 실패 (잠시 후 다시 시도해주세요)")

            # 분석 결과 표시
            if i in st.session_state['deep_results']:
                with st.chat_message("assistant"):
                    st.markdown(st.session_state['deep_results'][i])
        
        st.divider()

    if st.button("🔄 수업 다시 시작 (새로고침)"):
        st.cache_data.clear()
        if 'briefing_data' in st.session_state: del st.session_state['briefing_data']
        st.rerun()

if __name__ == "__main__":
    main()