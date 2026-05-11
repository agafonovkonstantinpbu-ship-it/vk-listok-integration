import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Загружаем настройки из файла .env
load_dotenv()

app = Flask(__name__)

# Читаем данные из .env
LISTOK_URL = os.getenv('LISTOK_BASE_URL')
API_TOKEN = os.getenv('LISTOK_API_TOKEN')
CFORM_ID = os.getenv('CFORM_ID')

# Заголовки для запросов к ListOk
HEADERS = {
    'Authorization': f'Bearer {API_TOKEN}',
    'Content-Type': 'application/json'
}

@app.route('/webhook/vk', methods=['POST'])
def webhook():
    # 1. Получаем данные от ВК
    data = request.json
    print("📥 Получены данные от ВК:", data)

    # ВРЕМЕННАЯ ЗАГЛУШКА: просто выводим данные в консоль, чтобы проверить связь
    # Полный код отправки в CRM добавим на следующем шаге
    
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)