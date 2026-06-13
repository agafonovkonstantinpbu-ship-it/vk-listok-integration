import os
import re
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Конфигурация ListOk CRM
LISTOK_URL = os.getenv('LISTOK_BASE_URL', 'https://an10569.listokcrm.ru').rstrip('/')
API_TOKEN = os.getenv('LISTOK_API_TOKEN')
CFORM_ID = os.getenv('CFORM_ID', '1')

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json',
    'X-Requested-With': 'XMLHttpRequest'
}

def normalize_phone(phone):
    """Нормализация телефона"""
    if not phone:
        return ''
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    if len(digits) == 11 and not digits.startswith('7'):
        digits = '7' + digits
    return f"+{digits}" if not digits.startswith('+') else digits

def find_or_create_contact(phone, name="", email=""):
    """Ищем или создаём контакт в ListOk"""
    print(f"🔍 Поиск контакта: {phone}")
    
    # 1. Пробуем найти по телефону
    search_url = f"{LISTOK_URL}/api/external/v2/contacts"
    try:
        resp = requests.get(
            search_url, 
            headers=HEADERS, 
            params={'phone': phone}, 
            timeout=10
        )
        print(f"📋 Ответ поиска: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            contacts = data.get('data', [])
            if contacts:
                contact_id = contacts[0].get('contact_id')
                print(f"✅ Контакт найден: {contact_id}")
                return contact_id
    except Exception as e:
        print(f"⚠️ Ошибка поиска: {e}")
    
    # 2. Если не нашли — создаём
    try:
        print(f"➕ Создание нового контакта: {name}, {phone}")
        resp = requests.post(
            search_url, 
            headers=HEADERS, 
            json={
                'name': name or 'Клиент из WhatsApp',
                'phone': phone.lstrip('+'),
                'email': email
            }, 
            timeout=10
        )
        print(f"📝 Ответ создания: {resp.status_code}")
        
        if resp.status_code in [200, 201]:
            data = resp.json()
            contact_id = data.get('contact_id')
            print(f"🆕 Контакт создан: {contact_id}")
            return contact_id
        else:
            print(f"❌ Ошибка создания: {resp.text}")
    except Exception as e:
        print(f"❌ Ошибка создания контакта: {e}")
    
    return None

def create_inquiry(contact_id, note=""):
    """Создаём заявку"""
    url = f"{LISTOK_URL}/api/external/v2/inquiry"
    print(f"📤 Создание заявки для контакта {contact_id}")
    
    try:
        resp = requests.post(
            url, 
            headers=HEADERS, 
            json={
                'cform_id': int(CFORM_ID),
                'contact_id': contact_id,
                'note': note,
                'source': 'whatsapp'
            }, 
            timeout=10
        )
        print(f"📥 Ответ заявки: {resp.status_code} - {resp.text}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Ошибка создания заявки: {e}")
        return False

@app.route('/webhook/vk', methods=['POST'])
def vk_webhook():
    """Вебхук для VK Ads"""
    try:
        data = request.json
        print("📥 Получены данные от VK:", data)
        
        fields = data.get('fields', {})
        phone = fields.get('phone', '')
        name = fields.get('name', 'Не указано')
        email = fields.get('email', '')
        lead_id = data.get('lead_id', 'unknown')
        
        if not phone:
            print("⚠️ Нет телефона, пропускаем")
            return jsonify({'status': 'skipped'}), 200
        
        phone = normalize_phone(phone)
        print(f"📱 Телефон: {phone}")
        
        contact_id = find_or_create_contact(phone, name, email)
        if not contact_id:
            return jsonify({'error': 'contact_not_created'}), 500
        
        success = create_inquiry(contact_id, f"VK Lead #{lead_id}")
        
        if success:
            return jsonify({'status': 'ok', 'contact_id': contact_id}), 200
        else:
            return jsonify({'error': 'inquiry_not_created'}), 500
            
    except Exception as e:
        print(f"❌ Ошибка VK webhook: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/webhook/wappi', methods=['POST'])
def wappi_webhook():
    """Вебхук для Wappi (WhatsApp)"""
    try:
        data = request.json
        print("📱 Wappi webhook received")
        
        # Wappi присылает массив messages
        messages = data.get('messages', [])
        if not messages:
            print("⚠️ Нет сообщений в webhook")
            return '', 200
            
        msg = messages[0]  # Берём первое сообщение
        
        # Проверяем тип сообщения (только входящие)
        msg_type = msg.get('wh_type', '') or msg.get('type', '')
        if msg_type not in ['incoming_message', 'incoming']:
            print(f"⚠️ Пропускаем сообщение типа: {msg_type}")
            return '', 200
        
        # Извлекаем телефон (убираем @c.us)
        sender = msg.get('from', '') or msg.get('senderId', '')
        phone = sender.split('@')[0] if '@' in sender else sender
        
        # Извлекаем текст сообщения
        text = msg.get('body', '') or msg.get('textMessage', '') or msg.get('textMessageData', {}).get('textMessage', '')
        
        # Извлекаем имя отправителя
        sender_name = msg.get('senderName', '') or msg.get('pushName', '') or 'Клиент из WhatsApp'
        
        print(f"📞 Phone: {phone}, Name: {sender_name}, Text: {text}")
        
        if not phone or phone == '0':
            print("⚠️ Неверный телефон")
            return '', 200

        # Нормализуем телефон
        phone = normalize_phone(phone)
        
        # Ищем или создаем контакт
        contact_id = find_or_create_contact(phone, sender_name)
        
        if contact_id:
            # Создаем заявку с текстом сообщения
            success = create_inquiry(contact_id, f"WhatsApp: {text}")
            print(f"✅ Заявка создана: {success}")
        else:
            print("❌ Не удалось создать контакт")
            
        return '', 200
        
    except Exception as e:
        print(f"❌ Error in wappi webhook: {e}")
        import traceback
        traceback.print_exc()
        return '', 500

@app.route('/', methods=['GET'])
def index():
    """Главная страница"""
    return jsonify({
        'status': 'VK-ListOk-Wappi integration is running!',
        'endpoints': {
            'vk_webhook': '/webhook/vk',
            'wappi_webhook': '/webhook/wappi'
        }
    }), 200

if __name__ == '__main__':
    print("🚀 Запуск сервера интеграции...")
    print(f"📍 ListOk URL: {LISTOK_URL}")
    print(f"🔑 Token: {'***' + API_TOKEN[-5:] if API_TOKEN else 'NOT SET'}")
    app.run(host='0.0.0.0', port=5000, debug=True)
