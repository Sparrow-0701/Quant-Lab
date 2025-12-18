import streamlit as st
import os
import smtplib
from email.mime.text import MIMEText

st.set_page_config(
    page_title="Quant Lab",
    page_icon="💸",
    layout="wide"
)

# ---------------------------------------------------------
# 구독자 알림 메일 보내는 함수
# ---------------------------------------------------------
def send_subscription_alert(new_email):
    # Streamlit Secrets에서 계정 정보 가져오기
    try:
        sender = st.secrets["GMAIL_USER"]
        password = st.secrets["GMAIL_APP_PWD"]
    except:
        # 로컬 환경이나 시크릿이 없을 경우 예외 처리
        st.error("메일 설정(Secrets)이 되어있지 않습니다.")
        return False

    admin_email = "ksmsk0701@gmail.com"

    # 메일 내용 작성
    msg = MIMEText(f"새로운 뉴스레터 구독 신청이 들어왔습니다!\n\n구독자 이메일: {new_email}\n\n*GitHub Secrets에 이분을 추가해주세요!*")
    msg['Subject'] = f"🔔 신규 구독자 알림: {new_email}"
    msg['From'] = sender
    msg['To'] = admin_email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"메일 전송 오류: {e}")
        return False
# ---------------------------------------------------------


st.title("💸 AI 퀀트 투자 연구소")
st.markdown("### Data-Driven Investment Insights powered by Gemini")

st.divider()

# GitHub Actions가 생성한 리포트 읽어오기
report_path = "data/daily_report.md"

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("📰 오늘의 글로벌 기관 리포트 요약")
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            report_content = f.read()
        st.markdown(report_content)
    else:
        st.info("아직 오늘의 리포트가 생성되지 않았습니다. (매일 아침 7시 업데이트)")

with col2:
    st.info("💡 **이 사이트 활용법**")
    st.markdown("""
    1. **좌측 사이드바**에서 메뉴를 선택하세요.
    2. **Market Simulation**: 환율/주가 상관관계 및 몬테카를로 시뮬레이션
    3. **Stock Scoring**: 기술적 지표 기반 매수 강도 채점
    """)
    
    st.success("📩 **뉴스레터 구독**")
    
    # [기능 추가] 구독 로직 구현
    with st.form(key='sub_form'):
        user_email = st.text_input("이메일을 입력하고 매일 아침 리포트를 받아보세요", placeholder="example@email.com")
        submit_btn = st.form_submit_button("구독 신청")
        
        if submit_btn:
            if "@" not in user_email or "." not in user_email:
                st.warning("올바른 이메일 형식을 입력해주세요.")
            else:
                # 알림 메일 발송 시도
                success = send_subscription_alert(user_email)
                if success:
                    st.balloons() # 성공 축하 효과
                    st.success(f"환영합니다! '{user_email}'로 구독 신청되었습니다.")
                    st.caption("ℹ️ 확인 후 리포트 발송 리스트에 추가할 예정입니다.")
