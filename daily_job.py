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
        Task: Create a comprehensive "Daily Market Intelligence Brief" based on the provided summaries.
        Structure: The report must have two distinct parts: 
                1. A "Mobile Dashboard" (Executive Summary & Top Picks) at the top.
                2. A "Deep Dive Analysis" (Detailed Macro & Strategy) at the bottom.

        [Input Summaries]:
        {summaries_text}

        [Constraints]:
        1. **Top Picks Verification**: For the 'Top Picks' table, ONLY include tickers that have specific reasoning or data support in the text. Cite the evidence briefly.
        2. **Structure**: Use a horizontal rule (---) to clearly separate the Dashboard from the Deep Dive.
        3. **Tone**: The Dashboard should be punchy and visual. The Deep Dive should be analytical and professional.

        [Output Format (Markdown)]:
        # ☕ Morning Market Brief ({today_kst})

        ## ⚡ Executive Dashboard (Mobile View)
        
        ### 🚦 Market Sentiment
        [🔴 Fear -----⚪ Neutral -----🟢 Greed]
        * **Verdict**: (Bullish/Bearish/Mixed)
        * **Key Driver**: (1 sentence summary)

        ### 🏆 Top High-Conviction Picks
        (List the most strongly recommended assets. Verify evidence.)
        | Ticker | Action | Logic | Evidence/Source |
        | :--- | :--- | :--- | :--- |
        | **$TICKER** | Buy/Sell | (Why?) | (e.g., "OPM +20%", "Analyst Upgrade") |
        | **$TICKER** | Buy/Sell | (Why?) | (e.g., "RSI Oversold") |

        ### 🦄 Today's Hidden Gem
        * (The most unique/contrarian idea found in the reports)

        ---
        
        ## 🔍 Deep Dive Analysis (Professional View)

        ### 🔭 Macro View & Market Regime
        (Synthesize the overall market direction. Risk-On vs Risk-Off. Are the reports generally aligned or conflicting? Explain the narrative.)

        ### 🚀 Strategic Alpha Opportunities
        * **Consensus Trades**: (Where is the smart money flocking? e.g., "Long AI", "Short Bonds")
        * **Sector Rotation**: (Which sectors are heating up or cooling down?)
        * **Detailed Rationale**: (Expand on the logic behind the Top Picks mentioned above)

        ### ⚠️ Risk Radar (Tail Risks)
        * (Specific macro risks, geopolitical tensions, or monetary policy shifts to watch)
        * **Watch Levels**: (Key technical support/resistance levels if mentioned)
        """
    else:
        prompt = f"""
        역할: 글로벌 매크로 헤지펀드 CIO.
        임무: 제공된 리포트 요약본을 바탕으로 '일일 마켓 인텔리전스 브리핑'을 작성하십시오.
        구조: 리포트는 두 부분으로 명확히 나뉩니다.
            1. **상단**: 바쁜 출근길에 보는 '모바일 대시보드' (요약 및 종목 추천)
            2. **하단**: 상세한 투자 논리를 담은 '심층 마켓 분석' (Deep Dive)

        [입력 요약본]:
        {summaries_text}

        [제약 사항]:
        1. **Top Picks 검증(Evidence Check)**: 'Top Picks' 테이블에는 단순히 언급된 종목이 아니라, 확실한 근거(실적, 수급, 모멘텀 등)가 있는 종목만 포함하십시오. '근거'란에 그 이유를 명시하십시오.
        2. **구조 분리**: 대시보드와 심층 분석 사이에는 반드시 구분선(---)을 넣어 시각적으로 분리하십시오.
        3. **틈새 아이디어**: 남들이 보지 못한 역발상(Contrarian) 아이디어를 대시보드에 꼭 포함하십시오.

        [출력 양식 (Markdown)]:
        # ☕ 모닝 마켓 브리핑 ({today_kst})

        ## ⚡ 3분 요약 대시보드 (Mobile View)

        ### 🚦 시장 심리 미터기
        [🔴 공포 -----⚪ 중립 -----🟢 탐욕]
        * **한줄 평**: (예: 저가 매수세 유입 중)
        * **핵심 동인**: (시장을 움직이는 메인 재료 1가지)

        ### 🏆 오늘의 Top Picks 
        | 종목($) | 포지션 | 핵심 논거 | 근거/데이터 체크 |
        | :--- | :--- | :--- | :--- |
        | **$티커** | 매수/매도 | (예: AI 수요 지속) | (예: "영업이익률 50% 상회") |
        | **$티커** | 매수/매도 | (예: 낙폭 과대) | (예: "RSI 30 하회") |

        ### 🦄 틈새/역발상 아이디어 
        * (대중의 생각과 다르거나, 놓치기 쉬운 독특한 투자 기회 1가지)

        ---
        
        ## 🔍 심층 마켓 분석

        ### 🔭 매크로 뷰 & 시장 국면
        (전반적인 시장의 큰 흐름을 서술하십시오. Risk-On인지 Off인지, 리포트들 간에 뷰가 일치하는지 엇갈리는지 '서사(Narrative)'를 중심으로 자세히 분석하십시오.)

        ### 🚀 세부 알파 전략 
        * **컨센서스 트레이드**: (다수의 리포트가 동의하는 메가 트렌드. 예: "빅테크 쏠림", "채권 금리 하락 베팅")
        * **섹터 로테이션**: (자금이 어디서 빠져나가 어디로 이동하고 있는지)
        * **Top Picks 상세 분석**: (상단 표에서 언급한 종목들의 구체적인 투자 포인트 심화 설명)

        ### ⚠️ 리스크 레이더
        * **매크로 리스크**: (금리, 환율, 유가 등 거시경제 위협 요인)
        * **지정학/이벤트**: (선거, 전쟁, 실적 발표 등)
        * **주요 레벨**: (코스피 2500선, 나스닥 15000선 등 지지/저항 라인)
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
