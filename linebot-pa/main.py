import os, json, datetime, pytz
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, PushMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from googleapiclient.discovery import build
from google.oauth2 import service_account
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
BKK = pytz.timezone('Asia/Bangkok')

# ดึง config จาก environment variables
LINE_TOKEN   = os.environ['LINE_TOKEN']
LINE_SECRET  = os.environ['LINE_SECRET']
MY_USER_ID   = os.environ['MY_USER_ID']   # LINE User ID ของคุณ
CALENDAR_ID  = os.environ['CALENDAR_ID']  # email ของ Google Calendar

configuration = Configuration(access_token=LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

# ─── Google Calendar ───────────────────────────────────────
def get_calendar_service():
    creds_json = json.loads(os.environ['GOOGLE_CREDS_JSON'])
    creds = service_account.Credentials.from_service_account_info(
        creds_json, scopes=['https://www.googleapis.com/auth/calendar.readonly'])
    return build('calendar', 'v3', credentials=creds)

def get_today_events():
    service = get_calendar_service()
    now_bkk = datetime.datetime.now(BKK)
    start = now_bkk.replace(hour=0, minute=0, second=0).isoformat()
    end   = now_bkk.replace(hour=23, minute=59, second=59).isoformat()
    result = service.events().list(
        calendarId=CALENDAR_ID, timeMin=start, timeMax=end,
        singleEvents=True, orderBy='startTime').execute()
    return result.get('items', [])

def format_events(events):
    if not events:
        return "📅 วันนี้ไม่มีนัดหมายครับ"
    lines = ["📅 *ตารางวันนี้*"]
    for e in events:
        start = e['start'].get('dateTime', e['start'].get('date', ''))
        if 'T' in start:
            t = datetime.datetime.fromisoformat(start).astimezone(BKK).strftime('%H:%M')
        else:
            t = 'ทั้งวัน'
        lines.append(f"• {t} — {e.get('summary','(ไม่มีชื่อ)')}")
    return '\n'.join(lines)

# ─── ส่งข้อความหา LINE ────────────────────────────────────
def push(text):
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.push_message(PushMessageRequest(
            to=MY_USER_ID,
            messages=[TextMessage(text=text)]))

# ─── Scheduler: reminder อัตโนมัติ ────────────────────────
def check_upcoming_events():
    """เตือนนัดที่จะถึงใน 30 นาที"""
    service = get_calendar_service()
    now = datetime.datetime.now(BKK)
    soon = (now + datetime.timedelta(minutes=30)).isoformat()
    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now.isoformat(), timeMax=soon,
        singleEvents=True, orderBy='startTime').execute()
    for e in result.get('items', []):
        start_str = e['start'].get('dateTime', '')
        if not start_str:
            continue
        t = datetime.datetime.fromisoformat(start_str).astimezone(BKK).strftime('%H:%M')
        name = e.get('summary', '(ไม่มีชื่อ)')
        push(f"⏰ อีก 30 นาที — {name} เวลา {t} น.\nเตรียมตัวได้เลยครับ!")

def remind_if_start():
    push("🍽️ IF 16:8 — ถึงเวลากินได้แล้วครับ (Eating window เริ่ม)\nกินให้เสร็จก่อน 20:00 น.")

def remind_if_stop():
    push("🚫 IF 16:8 — หยุดกินได้แล้วครับ (Fasting เริ่ม)\nดื่มน้ำเปล่าได้ตลอดคืน 💧")

def morning_brief():
    """สรุปตารางเช้า 07:00"""
    events = get_today_events()
    msg = f"☀️ Good morning Prach!\n\n{format_events(events)}\n\n💪 วันนี้ดีแน่นอนครับ"
    push(msg)

# เริ่ม scheduler
scheduler = BackgroundScheduler(timezone=BKK)
scheduler.add_job(check_upcoming_events, 'interval', minutes=5)
scheduler.add_job(morning_brief,    'cron', hour=7,  minute=0)
scheduler.start()

# ─── Webhook รับคำสั่งจาก LINE ────────────────────────────
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    uid  = event.source.user_id

    if "วันนี้" in text or "ตาราง" in text:
        reply = format_events(get_today_events())
    elif "if" in text.lower() or "กิน" in text:
        reply = "🕛 เริ่มกิน 12:00 — หยุดกิน 20:00\nIF 16:8 ครับ 💪"
    elif "user id" in text.lower():
        reply = f"User ID ของคุณ:\n{uid}"
    else:
        reply = "สวัสดีครับ! พิมพ์ได้เลย:\n• 'วันนี้' — ดูตารางวันนี้\n• 'IF' — เช็คเวลากิน"

    with ApiClient(configuration) as api_client:
        from linebot.v3.messaging import ReplyMessageRequest
        MessagingApi(api_client).reply_message(ReplyMessageRequest(
            replyToken=event.reply_token,
            messages=[TextMessage(text=reply)]))

@app.route("/")
def index():
    return "LINE Bot PA is running ✅"

if __name__ == "__main__":
    app.run(port=8080)
