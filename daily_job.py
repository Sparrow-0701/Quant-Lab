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
        Role: CIO of a Global Macro Hedge Fund.
        Task: Curate a "Daily Market Intelligence Dashboard" from the provided report summaries.
        Target Audience: Traders reading on mobile. Needs to be "At-a-Glance" readable.

        [Input Summaries]:
        {summaries_text}

        [Constraints]:
        1. **Aggressive Curation**: Do not summarize everything. Pick the "Highest Conviction" calls from the inputs.
        2. **Ticker Extraction**: You MUST extract specific tickers (e.g., $NVDA, $TSLA) mentioned in the reports and list them clearly.
        3. **Visual Structure**: Use dividers, bold text for numbers, and emojis to create a "Dashboard" feel.

        [Output Format (Markdown)]:
        # ☕ Market Briefing ({today_kst})

        ## 🚦 Market Sentiment Meter
        (Create a visual text gauge based on overall tone)
        Example: [🔴 Fear ---⚪ Neutral ---🟢 Greed]
        * **Verdict**: (One word: e.g., "Bullish", "Cautious", "Panic")
        * **Driver**: (1 sentence on why)

        ---

        ## 🏆 Top High-Conviction Calls (Must Read)
        (Aggregate the specific 'Long/Overweight' ideas from input reports)
        | Ticker | Strategy | Key Rationale |
        | :--- | :--- | :--- |
        | **$TICKER** | Long/Short | (Short phrase, e.g., "Strong AI Demand") |
        | **$TICKER** | Long/Short | (Short phrase) |
        *(If no specific tickers, mention top sectors)*

        ---

        ## ⚡ 3-Minute Macro Digest
        * **🌍 Global Theme**: (Dominant narrative)
        * **⚠️ Risk Radar**: (Biggest threat today)
        * **📊 Key Data**: (Most important number, e.g., "CPI 3.2%")

        ## 🦄 The "Hidden Gem" Insight
        * (A unique/contrarian idea found in the reports that others might miss)
        """
    else:
        prompt = f"""
        역할: 글로벌 매크로 헤지펀드 CIO.
        임무: 개별 리포트들을 종합하여, 핵심 종목과 전략이 한눈에 보이는 '모바일 마켓 대시보드'를 작성하십시오.
        독자: 출근길 1분 안에 돈이 되는 정보를 찾으려는 트레이더.

        [입력 요약본]:
        {summaries_text}

        [제약 사항]:
        1. **철저한 큐레이션**: 모든 내용을 나열하지 마십시오. 가장 확신(Conviction)이 높은 투자 아이디어만 선별하십시오.
        2. **티커($) 필수 노출**: 입력 데이터에 있는 구체적인 종목명(예: $NVDA, $SOXL)을 반드시 추출하여 'Top Picks' 섹션에 배치하십시오.
        3. **시각적 구조**: 줄글 대신 표(Table)나 짧은 리스트를 사용하여 가독성을 극대화하십시오.

        [출력 양식 (Markdown)]:
        # ☕ 모닝 마켓 브리핑 ({today_kst})

        ## 🚦 시장 심리 미터기 (Market Meter)
        (전반적인 리포트 분위기를 텍스트 게이지로 표현)
        예시: [🔴 공포(Fear) -----⚪ 중립 -----🟢 탐욕(Greed)]
        * **오늘의 한마디**: (예: "저가 매수 기회", "소나기는 피하자")
        * **핵심 이유**: (1문장 요약)

        ---

        ## 🏆 오늘의 Top Picks (주목할 종목)
        (입력된 리포트들의 'Long/Overweight' 의견을 종합하여 테이블로 정리)
        | 종목($) | 포지션 | 핵심 논거 (짧게) |
        | :--- | :--- | :--- |
        | **$티커** | 매수/매도 | (예: AI 수요 폭발 지속) |
        | **$티커** | 매수/매도 | (예: 금리 인하 수혜) |
        *(특정 종목이 없다면 유망 섹터 기재)*

        ---

        ## ⚡ 3분 매크로 요약
        * **🌍 핵심 테마**: (시장을 움직이는 메인 이슈)
        * **⚠️ 리스크 레이더**: (오늘 조심해야 할 하방 요인)
        * **📊 데이터 체크**: (주목해야 할 지표/수치)

        ## 🦄 틈새/역발상 아이디어 (Hidden Gem)
        * (남들이 보지 못한 독특한 인사이트 1가지)
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
                당신은 시니어 퀀트 애널리스트입니다.
                주어진 리포트를 PM이 즉시 활용할 수 있는 '구조화된 데이터 카드'로 변환하십시오.

                [입력 텍스트]:
                {text}

                [분석 지침]:
                1. **Ticker 강제 추출**: 종목명은 반드시 티커 형태(예: $TSLA)로 변환하여 기재하십시오.
                2. **명확한 구분**: 팩트(Fact)와 의견(Opinion)을 구분하고, 수치(Numbers) 위주로 요약하십시오.
                3. **간결함**: 모바일에서 읽기 좋게 문장을 짧게 끊으십시오.

                [출력 양식 (Markdown)]:
                ### 📄 [리포트 제목/주제] 분석
                * **💡 One-Liner**: (핵심 논리 1문장)
                * **🌡️ Sentiment**: [점수 -5 ~ +5]

                #### 🎯 핵심 투자 아이디어 (Key Calls)
                * **🟢 Long (매수/비중확대)**:
                - **$TICKER**: (목표가 혹은 투자 포인트)
                - **$TICKER**: (목표가 혹은 투자 포인트)
                * **🔴 Short (매도/리스크)**:
                - **$TICKER**: (리스크 요인)

                #### 🔢 핵심 데이터 (Key Numbers)
                * (중요 수치 1)
                * (중요 수치 2)
                """
                
                res_ko = model.generate_content(prompt_ko)
                
                prompt_en = f"""
                Role: Senior Quant Analyst.
                Task: Convert the report into a 'Structured Data Card' for immediate PM use.

                [Input Text]:
                {text}

                [Guidelines]:
                1. **Force Tickers**: Always convert company names to Tickers (e.g., $TSLA).
                2. **Conciseness**: Short bullets only. Focus on Numbers (%, $).

                [Output Format (Markdown)]:
                ### 📄 Report Analysis
                * **💡 One-Liner**: (Core thesis in 1 sentence)
                * **🌡️ Sentiment**: [Score -5 to +5]

                #### 🎯 Key Investment Calls
                * **🟢 Long/Overweight**:
                - **$TICKER**: (Target Price / Catalyst)
                * **🔴 Short/Underweight**:
                - **$TICKER**: (Risk Factors)

                #### 🔢 Key Numbers
                * (Critical Metric 1)
                * (Critical Metric 2)
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
