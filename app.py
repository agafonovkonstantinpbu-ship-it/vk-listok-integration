from flask import Flask, request, jsonify, redirect
import requests
import os
import re
from dotenv import load_dotenv, set_key

load_dotenv()

app = Flask(__name__)

# Конфигурация ListOk
LISTOK_DOMAIN = os.getenv("LISTOK_DOMAIN", "https://an10569.listokcrm.ru")
LISTOK_OFFICE_ID = int(os.getenv("LISTOK_OFFICE_ID", 1))
LISTOK_SOURCE_ID = int(os.getenv("LISTOK_SOURCE_ID", 1))

# OAuth данные (из таблицы интеграций ListOk)
INTEGRATION_ID = os.getenv("CLIENT_ID", "a2030ed7-2ba5-4e11-876e-214104c71b9d")
INTEGRATION_SECRET = os.getenv("CLIENT_SECRET", "A7V1J5YKKmp8oihhBeU7ooztWuWzAR4sEuqLPYbp")
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://expert-fortnight-r4vp54v74pqjcxx4r-5000.app.github.dev/callback")

# Токен (изначально пустой, загрузится из .env после авторизации)
LISTOK_TOKEN = os.getenv("LISTOK_ACCESS_TOKEN", "")

def get_headers():
    """Возвращает заголовки с токеном"""
    global LISTOK_TOKEN
    if not LISTOK_TOKEN:
        LISTOK_TOKEN = os.getenv("LISTOK_ACCESS_TOKEN", "")
    
    return {
        "Authorization": f"Bearer {LISTOK_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest"
    }

# ==================== OAUTH2 АВТОРИЗАЦИЯ ====================

@app.route('/auth')
def auth_start():
    """Перенаправляем на авторизацию ListOk"""
    auth_url = (
        f"{LISTOK_DOMAIN}/oauth/authorize"
        f"?client_id={INTEGRATION_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
    )
    return redirect(auth_url)

@app.route('/callback')
def callback():
    """Получаем код, обмениваем на токен и СОХРАНЯЕМ в .env"""
    code = request.args.get('code')
    if not code:
        return "❌ Код не получен", 400
    
    print(f"📥 Получен код: {code[:50]}...")
    
    token_url = f"{LISTOK_DOMAIN}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": INTEGRATION_ID,
        "client_secret": INTEGRATION_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code
    }
    
    try:
        resp = requests.post(token_url, json=payload)
        print(f"📤 Ответ: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get('access_token')
            
            # СОХРАНЯЕМ ТОКЕН В .env
            global LISTOK_TOKEN
            LISTOK_TOKEN = access_token
            set_key('.env', 'LISTOK_ACCESS_TOKEN', access_token)
            
            print(f"✅✅✅ ТОКЕН ПОЛУЧЕН: {access_token} ✅✅✅")
            
            return f"""
            <h1>✅ Успешно!</h1>
            <p>Токен получен и сохранен в .env</p>
            <p><b>Access Token:</b> {access_token}</p>
            <p>Теперь перезапусти сервер (Ctrl+C → python app.py)</p>
            """
        else:
            return f"❌ Ошибка {resp.status_code}: {resp.text}"
            
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

# ==================== WAPPI WEBHOOK ====================

@app.route('/webhook/wappi', methods=['POST'])
def wappi_webhook():
    """Принимаем сообщения от Wappi"""
    if not LISTOK_TOKEN:
        return jsonify({"error": "Token not set. Go to /auth first"}), 401

    try:
        data = request.json
        print("📱 Wappi webhook received")
        
        messages = data.get('messages', [])
        if not messages:
            return '', 200
            
        msg = messages[0]
        
        # Только входящие
        msg_type = msg.get('wh_type', '') or msg.get('type', '')
        if msg_type not in ['incoming_message', 'incoming']:
            return '', 200
        
        # Извлекаем данные
        sender = msg.get('from', '') or msg.get('senderId', '')
        phone = sender.split('@')[0] if '@' in sender else sender
        text = msg.get('body', '') or msg.get('textMessage', '')
        sender_name = msg.get('senderName', '') or 'Клиент'
        
        print(f"📞 Phone: {phone}, Text: {text}")
        
        if not phone:
            return '', 200

        # Нормализуем телефон
        phone = normalize_phone(phone)
        
        # Ищем или создаем контакт
        contact_id = find_or_create_contact(phone, sender_name)
        
        if contact_id:
            # Создаем заявку
            create_inquiry(contact_id, f"WhatsApp: {text}")
            
        return '', 200
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return '', 500

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def normalize_phone(phone):
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    return digits

def find_or_create_contact(phone, name):
    headers = get_headers()
    
    # Ищем по телефону
    try:
        resp = requests.get(
            f"{LISTOK_DOMAIN}/api/external/v2/contacts",
            headers=headers,
            params={'phone': phone},
            timeout=5
        )
        
        if resp.status_code == 200:
            contacts = resp.json().get('data', [])
            if contacts:
                print(f"✅ Контакт найден: {contacts[0]['contact_id']}")
                return contacts[0]['contact_id']
    except Exception as e:
        print(f"⚠️ Ошибка поиска: {e}")
    
    # Создаем новый
    try:
        resp = requests.post(
            f"{LISTOK_DOMAIN}/api/external/v2/contacts",
            headers=headers,
            json={
                "name": name,
                "phone": phone,
                "email": "",
                "gender": "female",
                "can_sms": True,
                "can_email": True,
                "added_office_id": LISTOK_OFFICE_ID,
                "source_id": LISTOK_SOURCE_ID
            },
            timeout=10
        )
        
        if resp.status_code in [200, 201]:
            contact_id = resp.json().get('contact_id')
            print(f"🆕 Контакт создан: {contact_id}")
            return contact_id
    except Exception as e:
        print(f"❌ Ошибка создания: {e}")
    
    return None

def create_inquiry(contact_id, note):
    headers = get_headers()
    
    try:
        resp = requests.post(
            f"{LISTOK_DOMAIN}/api/external/v2/inquiry",
            headers=headers,
            json={
                "cform_id": 1,
                "contact_id": contact_id,
                "note": note,
                "source": "whatsapp"
            },
            timeout=10
        )
        print(f"📤 Заявка создана: {resp.status_code}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Ошибка заявки: {e}")
        return False

@app.route('/')
def health():
    if not LISTOK_TOKEN:
        return f"""
        <h1>⚠️ Требуется авторизация</h1>
        <p><a href="/auth">Нажать для авторизации в ListOk</a></p>
        """
    return jsonify({"status": "Running", "token": "Active"})

if __name__ == '__main__':
    print("🚀 Запуск сервера...")
    app.run(host='0.0.0.0', port=5000, debug=True)
