import streamlit as st
from supabase import create_client
import toml,os,sys

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

@st.cache_resource
def init_supabase():
    # 1. Streamlit Cloud Secrets 우선 확인
    try:
        url = st.secrets["supabase"]["SUPABASE_URL"]
        key = st.secrets["supabase"]["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        pass

    # 2. 로컬 secrets.toml 확인
    try:
        secrets_path = os.path.join(parent_dir, ".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            return create_client(secrets["supabase"]["SUPABASE_URL"], secrets["supabase"]["SUPABASE_KEY"])
    except:
        pass
    
    # 3. 환경변수 확인
    return create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

try:
    supabase = init_supabase()
except Exception as e:
    st.error("DB 연결 실패. API 키를 확인해주세요.")
    st.stop()

def render_sidebar():
    """사이드바를 그려주는 공통 함수"""
    
    # CSS 스타일링 (사이드바 배경, 버튼 스타일 등)
    st.markdown("""
        <style>
        /* 사이드바 배경색 변경 */
        [data-testid="stSidebar"] {
            background-color: #f8f9fa;
        }
        /* 사이드바 버튼 스타일 */
        div[data-testid="stSidebar"] .stButton > button {
            width: 100%;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
        }
        /* 메뉴 링크 스타일 */
        .stPageLink a {
            font-weight: 600;
        }
        /* 상단 자동 네비게이션 숨기기 (혹시 config 안 먹을 때 대비용 CSS) */
        [data-testid="stSidebarNav"] {
            display: none;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        # 2. 네비게이션 메뉴
        st.markdown("### 🧭 Menu")
        
        # 각 파일로 이동하는 링크
        st.page_link("./main.py", label="홈 (Dashboard)", icon="🏠")
        st.page_link("./pages/MonteCarlo.py", label="시뮬레이션 (Simulations)", icon="🎲")
        st.page_link("./pages/StockScoring.py", label="종목 스코어링 (Scoring)", icon="💯")

        st.write("") # 여백

        # 3. 미니 대시보드
        with st.container(border=True):
            st.markdown("##### 📊 Market Status")
            
            # DB 데이터 가져오기
            try:
                exchange = supabase.table("exchange_rates").select("*").order("date", desc=True).limit(2).execute()
                
                if exchange.data and len(exchange.data) >= 2:
                    today_exchange = exchange.data[0].get("usd_krw")
                    yesterday_exchange = exchange.data[1].get("usd_krw")
                    diff = (today_exchange - yesterday_exchange)
                    diff_pct = diff/yesterday_exchange*100
                    
                    st.metric(
                        label="USD/KRW", 
                        value=f"{today_exchange:,.2f}", 
                        delta=f"{diff:,.2f}KRW, {diff_pct:,.2f}%",
                    )
                else:
                    st.warning("환율 데이터 부족")
                    
            except Exception as e:
                st.error("데이터 로드 실패")

        st.divider()