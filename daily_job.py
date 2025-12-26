import os
import io
import time
import smtplib
import requests
import toml
import google.generativeai as genai
from pypdf import PdfReader
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone # timezone 필수
from supabase import create_client

# ==========================================
# 1. 환경 설정
# ==========================================

# 한국 시간대(KST) 정의 - 서버에서도 한국 시간으로 뜨게 함
KST = timezone(timedelta(hours=9))

try:
    # 1. 로컬 개발 환경
    current_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(current_dir, ".streamlit", "secrets.toml")
    
    if os.path.exists(secrets_path):
        secrets = toml.load(secrets_path)
        SUPABASE_URL = secrets["supabase"]["SUPABASE_URL"]
        SUPABASE_KEY = secrets["supabase"]["SUPABASE_KEY"]
        GEMINI_API_KEY = secrets.get("google", {}).get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = secrets.get("google", {}).get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = secrets.get("google", {}).get("SEARCH_ENGINE_ID") 
        GMAIL_USER = secrets["GMAIL"]["GMAIL_USER"]
        GMAIL_APP_PWD = secrets["GMAIL"]["GMAIL_APP_PWD"]
    else:
        # 2. GitHub Actions 환경
        SUPABASE_URL = os.environ.get("SUPABASE_URL")
        SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
        GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
        GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
        SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID")
        GMAIL_USER = os.environ.get("GMAIL_USER")
        GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD")

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)

except Exception as e:
    print(f"❌ 설정 로드 실패: {e}")
    exit()

# 검색 대상 및 키워드
TARGET_SITES = [
    "blackrock.com", "macquarie.com", "kkr.com", "brookfield.com",
    "goldmansachs.com", "jpmorgan.com", "morganstanley.com", "ubs.com",
    "mckinsey.com", "pwc.com", "bain.com", "deloitte.com",
    "worldbank.org", "adb.org", "imf.org"
]
SEARCH_KEYWORD = "Infrastructure Outlook"

# ==========================================
# 2. 핵심 기능 함수
# ==========================================

def get_subscribers_from_db(lang_code=None):
    try:
        query = supabase.table("subscribers").select("email").eq("is_active", True)
        if lang_code:
            query = query.eq("language", lang_code)
        response = query.execute()
        return [row['email'] for row in response.data]
    except Exception as e:
        print(f"❌ 구독자 DB 조회 실패: {e}")
        return []

def search_pdf_reports(keyword, sites):
    if not GOOGLE_SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        print("⚠️ 검색 API 키가 없어 검색을 건너뜁니다.")
        return []
        
    site_query = " OR ".join([f"site:{site}" for site in sites])
    final_query = f"{keyword} filetype:pdf ({site_query})"
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_SEARCH_API_KEY,
        'cx': SEARCH_ENGINE_ID,
        'q': final_query,
        'num': 10,
        'dateRestrict': 'w1'
    }
    try:
        res = requests.get(url, params=params).json()
        return [{'title': i['title'], 'link': i['link']} for i in res.get('items', [])]
    except Exception as e:
        print(f"❌ 검색 실패: {e}")
        return []

def extract_text_fast(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        text = ""
        for i in range(min(len(reader.pages), 10)):
            text += reader.pages[i].extract_text() or ""
        return text if len(text) > 500 else None
    except:
        return None

def generate_synthesis(summaries_text, lang='ko'):
    model = genai.GenerativeModel('gemini-2.5-flash') 
    
    # [수정] 날짜를 KST 기준으로 생성
    today_kst = datetime.now(KST).strftime('%Y-%m-%d')
    
    if lang == 'en':
        prompt = f"""
        Role: You are the Chief Investment Officer (CIO) of a Global Macro Hedge Fund.
        Task: Synthesize the provided individual report summaries into a strategic "Daily Market Intelligence Brief".
        
        [Input Summaries]:
        {summaries_text}
        
        [Constraints]:
        1. **Synthesis over Summary**: Do not just list the reports. Find common themes, contradictions, and unique signals across them.
        2. **Quant Focus**: Highlight volatility, correlation changes, and liquidity conditions if mentioned.
        3. **Tone**: Institutional, predictive, and risk-aware.
        
        [Output Format (Markdown)]:
        # 🌍 Global Market Intelligence ({today_kst})
        
        ## 🔭 Macro View & Sentiment
        (Synthesize the overall market direction: Risk-On vs. Risk-Off. Are the reports generally aligned or conflicting?)
        
        ## 🚀 Alpha Strategies (Sectors & Assets)
        * **Consensus Trades**: (Where is everyone agreeing? e.g., "Long AI", "Short Bonds")
        * **Contrarian/Niche Ideas**: (Unique insights found in specific reports)
        
        ## ⚠️ Risk Radar (Tail Risks)
        * (Specific macro risks, geopolitical tensions, or monetary policy shifts to watch)
        """
    else:
        prompt = f"""
        역할: 당신은 글로벌 매크로 헤지펀드의 최고투자책임자(CIO)입니다.
        임무: 아래 개별 리포트 요약들을 종합하여, 전략적인 '일일 시장 인텔리전스 브리핑'을 작성하십시오.
        
        [입력 데이터]:
        {summaries_text}
        
        [제약 사항]:
        1. **단순 요약 금지**: 리포트를 나열하지 말고, 공통적인 테마나 상충되는 의견(Contradictions)을 찾아 '종합(Synthesis)'하십시오.
        2. **퀀트 관점**: 변동성, 상관관계 변화, 유동성 조건 등이 있다면 강조하십시오.
        3. **어조**: 기관 투자자용 보고서처럼 전문적이고 예측적인 어조를 사용하십시오.
        
        [출력 양식 (Markdown)]:
        # 🌍 글로벌 마켓 인텔리전스 ({today_kst})
        
        ## 🔭 매크로 뷰 & 시장 센티먼트
        (전반적인 시장 방향성 종합: Risk-On vs Risk-Off. 리포트 간의 의견이 일치하는지, 엇갈리는지 분석)
        
        ## 🚀 알파 전략 (유망 섹터 및 자산)
        * **컨센서스 트레이드**: (다수의 리포트가 동의하는 투자처. 예: "AI 매수", "채권 매도")
        * **틈새/역발상 아이디어**: (특정 리포트에서만 발견된 독창적인 인사이트)
        
        ## ⚠️ 리스크 레이더 (Tail Risk)
        * (구체적인 매크로 위험, 지정학적 긴장, 통화 정책 변화 등 주의해야 할 하방 요인)
        """
        
    try:
        res = model.generate_content(prompt)
        return res.text
    except Exception as e:
        return f"분석 실패: {e}"

def send_email_batch(subject, body, receivers):
    if not receivers: return
    
    msg = MIMEMultipart()
    sender_name = "RevolTac" 
    msg['From'] = f"{sender_name} <{GMAIL_USER}>"
    msg['Subject'] = subject
    msg['Bcc'] = ", ".join(receivers) 
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        server.send_message(msg)
        server.quit()
        print(f"✅ 이메일 발송 완료 ({len(receivers)}명)")
    except Exception as e:
        print(f"❌ 이메일 발송 실패: {e}")

# ==========================================
# 3. 메인 로직
# ==========================================
if __name__ == "__main__":
    print("🚀 QuantLab Daily Job 시작...")
    
    reports = search_pdf_reports(SEARCH_KEYWORD, TARGET_SITES)
    
    structured_summaries = [] 
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # 2. 개별 리포트 요약
    for report in reports:
        print(f"Processing: {report['title']}...")
        
        text = extract_text_fast(report['link'])
        
        if text:
            try:
                prompt_ko = f"""
                당신은 글로벌 자산운용사의 시니어 퀀트 리서처(Senior Quant Researcher)입니다.
                제공된 금융 리포트 텍스트를 분석하여, 포트폴리오 매니저(PM)가 즉시 의사결정에 활용할 수 있는 'Actionable Insight'를 도출하십시오.
                
                [텍스트]: {text[:15000]}
                
                [분석 지침]:
                1. 일반적인 내용보다는 구체적인 자산군(Asset Class), 섹터, 종목명, 그리고 수치(%, $, bps)에 집중하십시오.
                2. 저자의 뷰가 Bullish(낙관), Bearish(비관), Neutral(중립) 중 어디에 가까운지 파악하십시오.
                
                [출력 형식 (Markdown)]:
                * **💡 핵심 투자 논지 (Key Thesis)**: (리포트의 주장을 한 문장으로 강력하게 요약)
                * **📊 자산 배분 아이디어**: (Long/Short 추천, 비중 확대/축소 섹터 구체적 명시)
                * **🔢 주요 데이터/근거**: (주장을 뒷받침하는 핵심 지표, 목표 주가, 예상 성장률 등 수치 위주 작성)
                """
                res_ko = model.generate_content(prompt_ko)
                
                # [수정 2] 개별 리포트 요약 - 영어 (Professional Ver.)
                prompt_en = f"""
                You are a Senior Buy-side Quant Researcher at a top-tier asset management firm.
                Analyze the provided financial report to extract 'Actionable Insights' for Portfolio Managers.
                
                [Text]: {text[:15000]}
                
                [Analysis Guidelines]:
                1. Focus strictly on specific Asset Classes, Sectors, Tickers, and quantitative metrics (%, $, bps).
                2. Identify if the author's stance is Bullish, Bearish, or Neutral.
                
                [Output Format (Markdown)]:
                * **💡 Key Thesis**: (Strong one-sentence summary of the core argument)
                * **📊 Asset Allocation Strategy**: (Specific Long/Short ideas, Overweight/Underweight sectors)
                * **🔢 Key Data & Evidence**: (Crucial metrics, price targets, growth forecasts supporting the thesis)
                """
                res_en = model.generate_content(prompt_en)
                
                # DB 저장
                supabase.table("individual_reports").insert({
                    "title": report['title'],
                    "link": report['link'],
                    "summary_ko": res_ko.text,
                    "summary_en": res_en.text
                }).execute()
                
                structured_summaries.append({
                    "title": report['title'],
                    "link": report['link'],
                    "summary_ko": res_ko.text,
                    "summary_en": res_en.text
                })
                
                time.sleep(2) 
                
            except Exception as e:
                print(f"Error processing {report['title']}: {e}")

    if structured_summaries:
        all_text_en = "\n\n".join([f"Title: {s['title']}\nSummary: {s['summary_en']}" for s in structured_summaries])
        
        print("🤖 종합 리포트 생성 중...")
        final_ko = generate_synthesis(all_text_en, 'ko')
        final_en = generate_synthesis(all_text_en, 'en')
        
        # 날짜를 KST 기준으로 생성
        today_kst_str = datetime.now(KST).strftime('%Y-%m-%d')
        today_kst_md = datetime.now(KST).strftime('%m/%d')
        
        # DB 저장 
        db_data = {
            "title": f"Global Market Synthesis ({today_kst_str})",
            "summary_ko": final_ko,
            "summary_en": final_en
        }
        supabase.table("daily_reports").insert(db_data).execute()
        print("💾 종합 리포트 DB 저장 완료!")

        # 메일 본문 조립
        def build_mail_body(synthesis, summaries, lang='ko'):
            body = f"{synthesis}\n\n"
            body += "=" * 40 + "\n\n"
            
            if lang == 'ko':
                body += "📚 [참고한 개별 리포트 원문 요약]\n\n"
                key = 'summary_ko'
            else:
                body += "📚 [Individual Report Summaries]\n\n"
                key = 'summary_en'

            for item in summaries:
                body += f"📌 {item['title']}\n"
                body += f"🔗 {item['link']}\n"
                body += f"{item[key]}\n" 
                body += "-" * 20 + "\n"
            
            return body

        # 메일 발송
        korean_users = get_subscribers_from_db('ko')
        if korean_users:
            body_ko = build_mail_body(final_ko, structured_summaries, 'ko')
            send_email_batch(f"[QuantLab] 오늘의 글로벌 마켓 브리핑 ({today_kst_md})", body_ko, korean_users)

        english_users = get_subscribers_from_db('en')
        if english_users:
            body_en = build_mail_body(final_en, structured_summaries, 'en')
            send_email_batch(f"[QuantLab] Daily Market Brief ({today_kst_md})", body_en, english_users)
            
    else:
        print("💤 처리된 리포트가 없습니다.")