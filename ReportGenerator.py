# report_generator.py
import os
import time
import requests
import google.generativeai as genai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pypdf import PdfReader
from datetime import datetime

# 환경 변수 로드 (GitHub Secrets에서 가져옴)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY")
SEARCH_ENGINE_ID = os.environ.get("SEARCH_ENGINE_ID")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD")

# 수신자 목록 (본인 이메일 등)
RECEIVER_EMAILS = ["ksmsk0701@gmail.com"] 

genai.configure(api_key=GEMINI_API_KEY)
AVAILABLE_MODELS = ["models/gemini-1.5-flash"] # 최신 모델명으로 고정 추천

TARGET_SITES = ["blackrock.com", "jpmorgan.com", "morganstanley.com", "mckinsey.com", "worldbank.org"]
SEARCH_KEYWORD = "Infrastructure Outlook"

def search_and_extract():
    # (기존 검색 로직 유지하되 간소화)
    site_query = " OR ".join([f"site:{site}" for site in TARGET_SITES])
    final_query = f"{SEARCH_KEYWORD} filetype:pdf after:2024-01-01 ({site_query})" # 날짜 필터 강화
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOGLE_SEARCH_API_KEY, 'cx': SEARCH_ENGINE_ID, 'q': final_query, 'num': 3}
    
    try:
        response = requests.get(url, params=params).json()
        items = response.get('items', [])
        return items
    except Exception as e:
        print(f"Error: {e}")
        return []

def extract_text_from_pdf(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        
        # 임시 파일 저장 후 읽기 (메모리 부족 방지)
        with open("temp.pdf", "wb") as f:
            f.write(response.content)
            
        reader = PdfReader("temp.pdf")
        text = ""
        for page in reader.pages[:5]: # 앞 5페이지만 (요약 속도 향상)
            text += page.extract_text()
        return text
    except:
        return None

def generate_summary(text_list):
    if not text_list: return "새로운 리포트를 찾지 못했습니다."
    
    combined_text = "\n\n".join(text_list)
    model = genai.GenerativeModel("models/gemini-1.5-flash")
    
    prompt = f"""
    당신은 퀀트 투자자 승규를 위한 AI 비서입니다. 
    다음 금융 리포트 내용들을 통합하여 '오늘의 인사이트'를 작성하세요.
    
    [분석 대상]
    {combined_text[:10000]} (토큰 제한으로 일부 생략)
    
    [출력 형식 - Markdown]
    ## 🌍 글로벌 인프라 & 시장 동향 ({datetime.now().strftime('%Y-%m-%d')})
    
    ### 1. 🚨 핵심 변화 (Key Shift)
    * (내용)
    
    ### 2. 💰 유망 섹터 (Top Picks)
    * (내용)
    
    ### 3. ⚠️ 리스크 요인
    * (내용)
    """
    response = model.generate_content(prompt)
    return response.text

def save_to_markdown(content):
    # data 폴더가 없으면 생성
    if not os.path.exists('data'):
        os.makedirs('data')
        
    with open("data/daily_report.md", "w", encoding="utf-8") as f:
        f.write(content)
    print("✅ 리포트 파일 저장 완료 (data/daily_report.md)")

def send_email(content):
    if not GMAIL_USER: return
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = ", ".join(RECEIVER_EMAILS)
    msg['Subject'] = f"[승규AI] 오늘의 금융 리포트 요약 ({datetime.now().strftime('%m/%d')})"
    msg.attach(MIMEText(content, 'plain')) # Markdown 원문 전송
    
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(GMAIL_USER, GMAIL_APP_PWD)
    server.send_message(msg)
    server.quit()

if __name__ == "__main__":
    items = search_and_extract()
    texts = []
    for item in items:
        txt = extract_text_from_pdf(item['link'])
        if txt: texts.append(f"Title: {item['title']}\n{txt}")
    
    final_report = generate_summary(texts)
    
    # 1. 파일로 저장 (웹사이트 게시용)
    save_to_markdown(final_report)
    
    # 2. 이메일 전송 (알림용)
    send_email(final_report)