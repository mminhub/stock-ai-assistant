import streamlit as st
import requests

# =========================================================
# [긴급 테스트] 라이브러리 다 빼고, 키 직접 넣어서 통신만 확인
# =========================================================

# 👇 여기에 사용자님의 키를 직접 붙여넣으세요 (따옴표 안에!)
DIRECT_API_KEY = "PASTE_YOUR_KEY_HERE" 

st.set_page_config(page_title="FINAL TEST")
st.title("🚨 생존 신고 테스트")

if DIRECT_API_KEY == "AIzaSyCxP-itFny7RP6vexmgjcvsuhHwevtp-Qc":
    st.error("코드를 수정해서 API 키를 직접 넣어주세요!")
    st.stop()

st.write(f"🔑 입력된 키 확인: {DIRECT_API_KEY[:10]}...")

# 가장 가벼운 1.5 모델로 테스트
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={DIRECT_API_KEY}"
headers = {'Content-Type': 'application/json'}
data = {"contents": [{"parts": [{"text": "Hello Gemini! Are you working on Streamlit Cloud?"}]}]}

if st.button("AI 호출하기 (Click Me)"):
    with st.spinner("접속 시도 중..."):
        try:
            res = requests.post(url, headers=headers, json=data, timeout=15)
            
            if res.status_code == 200:
                st.balloons()
                st.success("✅ 성공! (API 키도 맞고, 서버 통신도 됩니다)")
                st.markdown(f"**AI의 대답:** {res.json()['candidates'][0]['content']['parts'][0]['text']}")
                st.info("👉 이제 이 코드는 지우고, 원래 코드로 돌아가서 Secrets 설정을 다시 확인하세요. (키 오타가 있었을 겁니다)")
            else:
                st.error("❌ 실패 (키가 틀렸거나, 구글 서버 문제입니다)")
                st.write("응답 코드:", res.status_code)
                st.code(res.text) # 여기에 진짜 이유가 뜹니다
                
        except Exception as e:
            st.error(f"❌ 통신 에러: {str(e)}")