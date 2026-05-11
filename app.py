import os
import re
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

LISTOK_URL = os.getenv('LISTOK_BASE_URL')
API_TOKEN = os.getenv('LISTOK_API_TOKEN')
CFORM_ID = os.getenv('CFORM_ID')

HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

def normalize_phone(phone):
    """Нормализация телефона"""
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    if not digits.startswith('7') and len(digits) == 11:
        digits = '7' + digits
    return f"+{digits}"

def find_or_create_contact(phone, name="", email=""):
    """Ищем или создаём контакт в ListOk"""
    # 1. Пробуем найти по телефону
    search_url = f"{LISTOK_URL}/api/contacts"
    try:
        resp = requests.get(search_url, headers=HEADERS, params={'phone': phone}, timeout=10)
        if resp.status_code == 200:
            contacts = resp.json().get('contacts', [])
            if contacts:
                print(f"✅ Контакт найден: {contacts[0].get('id')}")
                return contacts[0].get('id')
    except:
        pass
    
    # 2. Если не нашли — создаём
    try:
        resp = requests.post(search_url, headers=HEADERS, json={
            'name': name,
            'phone': phone,
            'email': email
        }, timeout=10)
        if resp.status_code in [200, 201]:
            contact_id = resp.json().get('id') or resp.json().get('contact', {}).get('id')
            print(f"🆕 Контакт создан: {contact_id}")
            return contact_id
    except Exception as e:
        print(f"❌ Ошибка создания контакта: {e}")
    
    return None

def create_inquiry(contact_id, note=""):
    """Создаём заявку"""
    url = f"{LISTOK_URL}/api/external/v2/inquiry"
    try:
        resp = requests.post(url, headers=HEADERS, json={
            'cform_id': int(CFORM_ID),
            'contact_id': contact_id,
            'note': note,
            'source': 'vk_ads'
        }, timeout=10)
        print(f"📝 Заявка создана! Статус: {resp.status_code}")
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"❌ Ошибка создания заявки: {e}")
        return False

@app.route('/webhook/vk', methods=['POST'])
def webhook():
    try:
        data = request.json
        print("📥 Получены данные от ВК:", data)
        
        # Извлекаем данные из вебхука ВК
        fields = data.get('fields', {})
        phone = fields.get('phone', '')
        name = fields.get('name', 'Не указано')
        email = fields.get('email', '')
        lead_id = data.get('lead_id', 'unknown')
        
        if not phone:
            print("⚠️ Нет телефона, пропускаем")
            return jsonify({'status': 'skipped'}), 200
        
        # Нормализуем телефон
        phone = normalize_phone(phone)
        print(f"📱 Телефон: {phone}")
        
        # Ищем или создаём контакт
        contact_id = find_or_create_contact(phone, name, email)
        if not contact_id:
            return jsonify({'error': 'contact_not_created'}), 500
        
        # Создаём заявку
        success = create_inquiry(contact_id, f"VK Lead #{lead_id}")
        
        if success:
            return jsonify({'status': 'ok', 'contact_id': contact_id}), 200
        else:
            return jsonify({'error': 'inquiry_not_created'}), 500
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    return jsonify({'status': 'VK-ListOk integration is running!'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
