import streamlit as st
import feedparser
import yfinance as yf
import requests
import time

st.set_page_config(page_title="System Diagnosis", layout="wide")
st.title("🛠️ 시스템 정밀 진단 모드")

# 1. API 키 확인
st.subheader("1. API 키 확인")
if "GOOGLE_API_KEY" in st.secrets:
    key = st.secrets["GOOGLE_API_KEY"]
    st.success(f"✅ 키 있음 (앞자리: {key[:5]}...)")
    API_KEY = key
else:
    st.error("❌ API 키가 Secrets에 없습니다.")
    st.stop()

# 2. 주식 데이터 확인 (Yahoo Finance)
st.subheader("2. 주식 데이터 수집 (YFinance)")
try:
    with st.spinner("야후 파이낸스 접속 중..."):
        df = yf.download("^GSPC", period="1d", progress=False)
        if not df.empty:
            st.success(f"✅ 성공 (S&P500 데이터 수신됨)")
        else:
            st.warning("⚠️ 데이터가 비어있음 (서버 차단 가능성)")
except Exception as e:
    st.error(f"❌ 실패: {str(e)}")

# 3. 뉴스 데이터 확인 (Google RSS) - 여기가 유력한 용의자
st.subheader("3. 뉴스 데이터 수집 (Google News)")
try:
    with st.spinner("구글 뉴스 접속 중..."):
        # 서버 차단 우회용 헤더 추가
        rss_url = "https://news.google.com/rss/search?q=Apple&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)
        
        count = len(feed.entries)
        if count > 0:
            st.success(f"✅ 성공 ({count}개 기사 가져옴)")
            st.write(f"첫 번째 기사 제목: {feed.entries[0].title}")
        else:
            st.error("❌ 실패: 기사를 하나도 못 가져왔습니다. (구글이 서버 IP 차단함)")
except Exception as e:
    st.error(f"❌ 오류 발생: {str(e)}")

# 4. AI 모델 연결 확인 (Gemini 2.5)
st.subheader("4. AI 모델 (Gemini 2.5-flash)")
try:
    with st.spinner("Gemini 2.5 호출 중..."):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
        headers = {'Content-Type': 'application/json'}
        data = {"contents": [{"parts": [{"text": "Say 'OK'"}]}]}
        
        res = requests.post(url, headers=headers, json=data, timeout=10)
        
        if res.status_code == 200:
            st.success(f"✅ 성공 (응답: {res.json()['candidates'][0]['content']['parts'][0]['text']})")
        else:
            st.error(f"❌ 실패 (상태 코드: {res.status_code})")
            st.code(res.text) # 에러 원문 출력
            
            # 2.0으로 한번 더 테스트
            st.info("2.0 모델로 재시도...")
            url_2 = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"
            res_2 = requests.post(url_2, headers=headers, json=data, timeout=10)
            if res_2.status_code == 200:
                st.success("✅ 2.0 모델은 살아있음")
            else:
                st.error(f"❌ 2.0도 실패 ({res_2.status_code})")

except Exception as e:
    st.error(f"❌ 통신 오류: {str(e)}")