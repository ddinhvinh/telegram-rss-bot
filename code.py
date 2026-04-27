import feedparser
import requests
from newspaper import Article, Config
import sys
import time
import re
import os
import threading
from flask import Flask

# ─── CẤU HÌNH ───────────────────────────────────────────────────
# Đọc token từ biến môi trường (an toàn hơn hardcode)
BOT_TOKEN   = os.environ.get('BOT_TOKEN',   '8791542131:AAG7frASpHH-SAAr6URmsjbR_KYcR1Qj1KE')
DEFAULT_CHAT_ID = os.environ.get('CHAT_ID', '5772825825')

# Các nguồn RSS
RSS_URLS = [
    'https://vnexpress.net/rss/tin-moi-nhat.rss',
    'https://tuoitre.vn/rss/tin-moi-nhat.rss',
    'https://feeds.bbci.co.uk/news/rss.xml',
]

# Từ khoá kích hoạt (không phân biệt hoa thường)
TRIGGER_KEYWORDS = ['bắt đầu', 'bat dau', '/start']

# Cấu hình User-Agent cho newspaper
user_agent = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/119.0.0.0 Safari/537.36'
)
np_config = Config()
np_config.browser_user_agent = user_agent
np_config.request_timeout = 20

# ─── FLASK APP (để UptimeRobot / Render giữ process sống) ────────
app = Flask(__name__)

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/')
def index():
    return '🤖 Bot đang chạy tốt!', 200

# ─── HÀM GỬI TIN TELEGRAM ────────────────────────────────────────
def send_message(chat_id, text):
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print(f'[SEND_ERR] {e}')
        return False

# ─── LẤY RSS ─────────────────────────────────────────────────────
def fetch_rss(url):
    try:
        r = requests.get(url, headers={'User-Agent': user_agent}, timeout=15)
        if r.status_code == 200:
            return feedparser.parse(r.content)
    except Exception as e:
        print(f'[RSS_ERR] {url}: {e}')
    return None

# ─── LẤY NỘI DUNG BÀI VIẾT ───────────────────────────────────────
def get_article_text(url):
    try:
        article = Article(url, config=np_config)
        article.download()
        article.parse()
        return article.text.strip()
    except Exception:
        return ''

# ─── TỔNG HỢP TIN VÀ GỬI ────────────────────────────────────────
def get_news_and_send(chat_id):
    """Quét 3 nguồn RSS, lấy 2 tin mỗi nguồn và gửi tóm tắt."""
    total_sent = 0
    print(f'[BOT] Đang quét tin cho chat_id={chat_id}...')

    for rss_url in RSS_URLS:
        feed = fetch_rss(rss_url)
        if feed is None or not feed.entries:
            continue

        source_title = feed.feed.get('title', rss_url)

        for entry in feed.entries[:2]:          # 2 tin mới nhất / nguồn
            try:
                # Lấy nội dung bài đầy đủ, fallback về RSS summary
                text = get_article_text(entry.link)
                if not text:
                    text = entry.get('summary', '') or entry.get('description', '')
                    text = re.sub(r'<[^>]+>', '', text).strip()

                summary = (text[:450].replace('\n', ' ') + '...') if text else 'Không có nội dung tóm tắt.'

                message = (
                    f'📰 <b>{source_title}</b>\n'
                    f'📌 <b>{entry.title}</b>\n\n'
                    f'📝 {summary}\n\n'
                    f'🔗 <a href="{entry.link}">Xem bài gốc →</a>'
                )

                if send_message(chat_id, message):
                    total_sent += 1
                    time.sleep(1)               # tránh Telegram rate-limit
            except Exception as e:
                print(f'[ENTRY_ERR] {e}')

    send_message(chat_id, f'✅ <b>Xong!</b> Đã tổng hợp <b>{total_sent}</b> tin mới nhất cho bạn.')
    print(f'[BOT] Đã gửi {total_sent} tin cho chat_id={chat_id}.')

# ─── VÒNG LẶP POLLING ────────────────────────────────────────────
def polling_loop():
    last_update_id = 0
    print('[BOT] Bắt đầu lắng nghe tin nhắn...')

    # Thông báo bot online
    send_message(DEFAULT_CHAT_ID,
        '🤖 <b>Bot đã sẵn sàng!</b>\n'
        'Nhắn <b>Bắt đầu</b> để nhận tin tức tổng hợp ngay.')

    while True:
        try:
            url = (
                f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates'
                f'?offset={last_update_id + 1}&timeout=30'
            )
            resp = requests.get(url, timeout=35).json()

            if resp.get('ok'):
                for update in resp.get('result', []):
                    last_update_id = update['update_id']

                    msg = update.get('message', {})
                    text = msg.get('text', '').strip()
                    chat_id = msg.get('chat', {}).get('id')

                    if not text or not chat_id:
                        continue

                    # Kiểm tra từ khoá kích hoạt (không phân biệt hoa thường)
                    if any(kw in text.lower() for kw in TRIGGER_KEYWORDS):
                        print(f'[BOT] Nhận lệnh từ {chat_id}: "{text}"')
                        send_message(chat_id,
                            '⌛ <b>Đang tổng hợp tin tức...</b>\n'
                            'Vui lòng đợi khoảng 30-60 giây.')
                        # Chạy trong thread riêng để không block polling
                        threading.Thread(
                            target=get_news_and_send,
                            args=(chat_id,),
                            daemon=True
                        ).start()

            time.sleep(1)

        except KeyboardInterrupt:
            print('[BOT] Đã dừng.')
            break
        except Exception as e:
            print(f'[POLL_ERR] {e}')
            time.sleep(5)

# ─── ENTRY POINT ─────────────────────────────────────────────────
if __name__ == '__main__':
    # Chạy polling trong thread nền
    bot_thread = threading.Thread(target=polling_loop, daemon=True)
    bot_thread.start()

    # Chạy Flask server (cần thiết để Render / UptimeRobot giữ process sống)
    port = int(os.environ.get('PORT', 5000))
    print(f'[WEB] Flask đang chạy trên cổng {port}')
    app.run(host='0.0.0.0', port=port)
