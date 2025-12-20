import streamlit as st
import os
import smtplib
from email.mime.text import MIMEText
import streamlit.components.v1 as components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta


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
    
def save_to_google_sheet(email):
    try:
        # 1. 인증 정보 가져오기 (Secrets에서)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = st.secrets["gcp_service_account"] 
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # 2. 시트 열기 (파일 이름 정확해야 함!)
        sheet = client.open("구독자 리스트").sheet1

        # 3. 데이터 준비
        start_date = datetime.now().strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d") # 1년 구독
        reg_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 4. 행 추가 (이메일, 시작일, 종료일, 등록시간)
        sheet.append_row([email, start_date, end_date, reg_time])
        return True
        
    except Exception as e:
        st.error(f"구글 시트 저장 오류: {e}")
        return False    
    
# ---------------------------------------------------------




st.title("💸 AI 퀀트 투자 연구소")

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
        st.info("아직 오늘의 리포트가 생성되지 않았습니다. (매일 아침 8시 업데이트)")

with col2:
    st.info("💡 이 사이트 활용법")
    st.markdown("""
    1. 좌측 사이드바에서 메뉴를 선택하세요.
    2. MonteCarlo: 환율/주가 상관관계 및 몬테카를로 시뮬레이션
    3. Stock Scoring: 기술적 지표 기반 매수 강도 채점
    """)
    
    st.success("📩 **뉴스레터 구독**")
    
    #구독 로직 구현
    with st.form(key='sub_form'):
        user_email = st.text_input("이메일을 입력하세요", placeholder="example@email.com")
        submit_btn = st.form_submit_button("구독 신청")
        
        if submit_btn:
            if "@" not in user_email:
                st.warning("올바른 이메일 형식을 입력해주세요.")
            else:
                with st.spinner("처리 중..."):
                    if save_to_google_sheet(user_email):
                        st.balloons()
                        st.success(f"환영합니다! '{user_email}' 님이 구독되었습니다.")
                    else:
                        st.error("오류가 발생했습니다.")

st.divider()
st.caption("⚠️ **Disclaimer**: 본 서비스는 모의 투자 및 연구 목적으로 제작되었으며, 실제 투자에 대한 법적 책임을 지지 않습니다. 모든 데이터는 실시간이 아닐 수 있습니다.")

with st.sidebar:
    st.caption("☕ **개발자에게 커피 한 잔 쏘기**")
    
    buymeacoffee_url = "https://www.buymeacoffee.com/revoltac"
    
    st.markdown(
        f"""
        <div style="text-align:center;">
            <a href="{buymeacoffee_url}" target="_blank">
                <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 200px !important;" >
            </a>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    st.caption("서버 비용과 개발에 큰 힘이 됩니다!")
    
    st.caption("문의사항: ksmsk0701@gmail.com")
