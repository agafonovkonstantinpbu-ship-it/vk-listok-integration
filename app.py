import os
import re
import requests
import json
from flask import Flask, request, jsonify, redirect, url_for
from dotenv import load_dotenv, set_key

# Загружаем .env
load_dotenv()

app = Flask(__name__)

# --- КОНФИГУРАЦИЯ ---
LISTOK_BASE_URL = os.getenv('LISTOK_BASE_URL', '').rstrip('/')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI')

# Токен (изначально пустой, загружается из env)
ACCESS_TOKEN = os.getenv('LISTOK_ACCESS_TOKEN')

def get_headers():
    """Возвращает заголовки с токеном"""
    global ACCESS_TOKEN
    # Если токен в переменной пуст, пробуем обновить из env
    if not ACCESS_TOKEN:
        ACCESS_TOKEN = os.getenv('LISTOK_ACCESS_TOKEN')
    
    return {
        'Authorization': f'Bearer {ACCESS_TOKEN}',
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
    }

# --- 1. ЛОГИКА OAUTH2 АВТОРИЗАЦИИ ---

@app.route('/auth')
def auth_start():
    """Шаг 1: Перенаправляем пользователя на страницу входа ListOk"""
    if not CLIENT_ID:
        return "Ошибка: Не указан CLIENT_ID в .env", 500
        
    auth_url = (
        f"{LISTOK_BASE_URL}/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
    )
    return redirect(auth_url)

@app.route('/callback')
def auth_callback():
    """Шаг 2: Получаем код, обмениваем на токен и сохраняем в .env"""
    code = request.args.get('code')
    if not code:
        return "Ошибка авторизации: Нет кода", 400

    try:
        # Запрос на обмен кода на токен
        token_url = f"{LISTOK_BASE_URL}/oauth/token"
        payload = {
            'grant_type': 'authorization_code',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'code': code
        }
        
        # ListOk требует заголовок X-Requested-With даже для получения токена
        headers = {'X-Requested-With': 'XMLHttpRequest'}
        
        resp = requests.post(token_url, json=payload, headers=headers)
        resp.raise_for_status()
        token_data = resp.json()
        
        # Сохраняем токен
        global ACCESS_TOKEN
        ACCESS_TOKEN = token_data.get('access_token')
        
        # Обновляем файл .env, чтобы токен сохранился навсегда
        if ACCESS_TOKEN:
            set_key('.env', 'LISTOK_ACCESS_TOKEN', ACCESS_TOKEN)
            return f"<h1>Успешно!</h1><p>Токен получен и сохранен в .env. Теперь перезапусти сервер (Ctrl+C -> python app.py) и интеграция заработает.</p>"
        else:
            return "Ошибка: Токен не пришел", 500

    except Exception as e:
        return f"Ошибка обмена кода на токен: {str(e)}", 500

# --- 2. ЛОГИКА ИНТЕГРАЦИИ (WAPPI -> LISTOK) ---

@app.route('/webhook/wappi', methods=['POST'])
def wappi_webhook():
    """Принимает сообщения от Wappi"""
    if not ACCESS_TOKEN:
        return jsonify({'error': 'Token not set. Please authorize via /auth'}), 401

    try:
        data = request.json
        print("📱 Wappi webhook received")
        
        messages = data.get('messages', [])
        if not messages:
            return '', 200
            
        msg = messages[0]
        
        # Только входящие сообщения
        msg_type = msg.get('wh_type', '') or msg.get('type', '')
        if msg_type not in ['incoming_message', 'incoming']:
            return '', 200
        
        # Извлекаем данные
        sender = msg.get('from', '') or msg.get('senderId', '')
        phone = sender.split('@')[0] if '@' in sender else sender
        text = msg.get('body', '') or msg.get('textMessage', '')
        sender_name = msg.get('senderName', '') or 'Клиент'
        
        print(f"📞 Phone: {phone}, Text: {text}")
        
        if not phone: return '', 200

        # 1. Ищем контакт в ListOk
        contact_id = find_contact(phone)
        
        # 2. Если нет, создаем
        if not contact_id:
            contact_id = create_contact(phone, sender_name)
        
        # 3. Создаем заявку
        if contact_id:
            create_inquiry(contact_id, f"WhatsApp: {text}")
            
        return '', 200
        
    except Exception as e:
        print(f" Error: {e}")
        return '', 500

@app.route('/', methods=['GET'])
def index():
    """Проверка статуса"""
    if not ACCESS_TOKEN:
        return jsonify({
            'status': 'Auth required',
            'action': f'Go to <a href="/auth">/auth</a> to connect ListOk'
        })
    return jsonify({'status': 'Running', 'token': 'Active'})

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def normalize_phone(phone):
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 11 and digits.startswith('8'): digits = '7' + digits[1:]
    return digits

def find_contact(phone):
    """Ищет контакт по телефону"""
    url = f"{LISTOK_BASE_URL}/api/external/v2/contacts"
    try:
        resp = requests.get(url, headers=get_headers(), params={'phone': normalize_phone(phone)})
        if resp.status_code == 200:
            contacts = resp.json().get('data', [])
            return contacts[0]['contact_id'] if contacts else None
    except: return None

def create_contact(phone, name):
    """Создает контакт"""
    url = f"{LISTOK_BASE_URL}/api/external/v2/contacts"
    try:
        resp = requests.post(url, headers=get_headers(), json={
            'name': name,
            'phone': normalize_phone(phone)
        })
        if resp.status_code in [200, 201]:
            return resp.json().get('contact_id')
    except Exception as e:
        print(f"Create contact error: {e}")
    return None

def create_inquiry(contact_id, note):
    """Создает заявку"""
    url = f"{LISTOK_BASE_URL}/api/external/v2/inquiry"
    try:
        # Получаем список форм, чтобы взять первую cform_id (обычно 1)
        # Но лучше использовать дефолтный, если не знаем ID формы
        resp = requests.post(url, headers=get_headers(), json={
            'cform_id': 1, # Поменяй на ID твоей формы захвата, если нужно
            'contact_id': contact_id,
            'note': note,
            'source': 'whatsapp'
        })
        print(f"Create inquiry: {resp.status_code}")
        return True
    except Exception as e:
        print(f"Create inquiry error: {e}")
    return False

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
