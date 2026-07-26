import os
import sys
import json
import hashlib
import random
import sqlite3
import uuid
import time
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app, origins=['*'])
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ============================================================
# ==================== ХРАНИЛИЩЕ ЛОББИ ========================
# ============================================================

# Все лобби хранятся в памяти сервера
lobbies = {}
# Подписки на лобби (socket_id -> lobby_id)
subscriptions = {}

# ============================================================
# ==================== API ЛОББИ ==============================
# ============================================================

@app.route('/api/lobby/create', methods=['POST'])
def create_lobby():
    """Создание лобби"""
    try:
        data = request.json
        host = data.get('host')
        name = data.get('name', 'Лобби ' + host)
        mode = data.get('mode', '1x1')
        
        if not host:
            return jsonify({'error': 'Имя хоста обязательно'}), 400
        
        lobby_id = 'lobby_' + str(uuid.uuid4())[:8]
        
        lobbies[lobby_id] = {
            'id': lobby_id,
            'name': name,
            'host': host,
            'mode': mode,
            'players': [host],
            'status': 'waiting',  # waiting | playing | finished
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        print(f'✅ Лобби создано: {lobby_id} ({host})')
        
        return jsonify({
            'success': True,
            'lobby_id': lobby_id,
            'lobby': lobbies[lobby_id]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/list', methods=['GET'])
def list_lobbies():
    """Получение всех доступных лобби"""
    try:
        # Возвращаем только ожидающие лобби с местом
        available = []
        for lobby_id, lobby in lobbies.items():
            if lobby['status'] == 'waiting' and len(lobby['players']) < 2:
                available.append(lobby)
        
        return jsonify(available)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/join', methods=['POST'])
def join_lobby():
    """Присоединение к лобби"""
    try:
        data = request.json
        lobby_id = data.get('lobby_id')
        player = data.get('player')
        
        if not lobby_id or not player:
            return jsonify({'error': 'lobby_id и player обязательны'}), 400
        
        if lobby_id not in lobbies:
            return jsonify({'error': 'Лобби не найдено'}), 404
        
        lobby = lobbies[lobby_id]
        
        if lobby['status'] == 'playing':
            return jsonify({'error': 'Матч уже идёт'}), 400
        
        if len(lobby['players']) >= 2:
            return jsonify({'error': 'Лобби заполнено'}), 400
        
        if player in lobby['players']:
            return jsonify({'error': 'Вы уже в лобби'}), 400
        
        lobby['players'].append(player)
        lobby['updated_at'] = datetime.now().isoformat()
        
        print(f'🔗 {player} присоединился к {lobby_id}')
        
        # Отправляем обновление всем подписчикам
        notify_lobby_update(lobby_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/start', methods=['POST'])
def start_lobby():
    """Начало матча (только хост)"""
    try:
        data = request.json
        lobby_id = data.get('lobby_id')
        
        if not lobby_id:
            return jsonify({'error': 'lobby_id обязателен'}), 400
        
        if lobby_id not in lobbies:
            return jsonify({'error': 'Лобби не найдено'}), 404
        
        lobby = lobbies[lobby_id]
        
        if len(lobby['players']) < 2:
            return jsonify({'error': 'Нужно минимум 2 игрока'}), 400
        
        if lobby['status'] == 'playing':
            return jsonify({'error': 'Матч уже идёт'}), 400
        
        lobby['status'] = 'playing'
        lobby['updated_at'] = datetime.now().isoformat()
        
        print(f'⚽ Матч начался в {lobby_id}')
        
        # Отправляем обновление всем подписчикам
        notify_lobby_update(lobby_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/leave', methods=['POST'])
def leave_lobby():
    """Выход из лобби"""
    try:
        data = request.json
        lobby_id = data.get('lobby_id')
        player = data.get('player')
        
        if not lobby_id or not player:
            return jsonify({'error': 'lobby_id и player обязательны'}), 400
        
        if lobby_id not in lobbies:
            return jsonify({'error': 'Лобби не найдено'}), 404
        
        lobby = lobbies[lobby_id]
        lobby['players'] = [p for p in lobby['players'] if p != player]
        
        if len(lobby['players']) == 0:
            del lobbies[lobby_id]
            print(f'🗑️ Лобби {lobby_id} удалено (пусто)')
            return jsonify({'success': True, 'deleted': True})
        
        if lobby['host'] == player and len(lobby['players']) > 0:
            lobby['host'] = lobby['players'][0]
        
        lobby['updated_at'] = datetime.now().isoformat()
        
        print(f'🚪 {player} вышел из {lobby_id}')
        
        notify_lobby_update(lobby_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/get/<lobby_id>', methods=['GET'])
def get_lobby(lobby_id):
    """Получение данных конкретного лобби"""
    try:
        if lobby_id not in lobbies:
            return jsonify({'error': 'Лобби не найдено'}), 404
        
        return jsonify(lobbies[lobby_id])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== WEBSOCKET ==============================
# ============================================================

def notify_lobby_update(lobby_id):
    """Отправка обновления всем подписчикам лобби"""
    if lobby_id not in lobbies:
        return
    
    lobby = lobbies[lobby_id]
    
    # Отправляем всем, кто подписан на это лобби
    for sid, sub_lobby_id in subscriptions.items():
        if sub_lobby_id == lobby_id:
            socketio.emit('lobby_update', {
                'lobby_id': lobby_id,
                'lobby': lobby
            }, room=sid)


@socketio.on('connect')
def handle_connect():
    print(f'🔌 Клиент подключен: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    # Удаляем подписку
    if request.sid in subscriptions:
        del subscriptions[request.sid]
    print(f'🔌 Клиент отключен: {request.sid}')


@socketio.on('subscribe_lobby')
def handle_subscribe(data):
    """Подписка на обновления лобби"""
    lobby_id = data.get('lobby_id')
    if lobby_id:
        subscriptions[request.sid] = lobby_id
        print(f'📡 {request.sid} подписался на {lobby_id}')
        
        # Отправляем текущее состояние
        if lobby_id in lobbies:
            emit('lobby_update', {
                'lobby_id': lobby_id,
                'lobby': lobbies[lobby_id]
            })


@socketio.on('unsubscribe_lobby')
def handle_unsubscribe():
    """Отписка от обновлений лобби"""
    if request.sid in subscriptions:
        del subscriptions[request.sid]
        print(f'📡 {request.sid} отписался')


# ============================================================
# ==================== DATABASE (ДЛЯ ИГРОКОВ) ================
# ============================================================

class Database:
    def __init__(self, db_path='football.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                player_id INTEGER PRIMARY KEY,
                rating INTEGER DEFAULT 50,
                crystals INTEGER DEFAULT 100,
                wins INTEGER DEFAULT 0,
                matches INTEGER DEFAULT 0,
                goals INTEGER DEFAULT 0,
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def create_player(self, name, password_hash):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO players (name, password_hash) VALUES (?, ?)', (name, password_hash))
        player_id = c.lastrowid
        c.execute('INSERT INTO stats (player_id) VALUES (?)', (player_id,))
        conn.commit()
        conn.close()
        return player_id
    
    def get_player(self, name):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT id, name, password_hash FROM players WHERE name = ?', (name,))
        row = c.fetchone()
        conn.close()
        return row
    
    def get_stats(self, player_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT rating, crystals, wins, matches, goals FROM stats WHERE player_id = ?', (player_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'rating': row[0], 'crystals': row[1], 'wins': row[2], 'matches': row[3], 'goals': row[4]}
        return {'rating': 50, 'crystals': 100, 'wins': 0, 'matches': 0, 'goals': 0}


db = Database()


# ============================================================
# ==================== API ИГРОКОВ ============================
# ============================================================

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        name = data.get('name', '').strip()
        password = data.get('password', '').strip()
        
        if not name or not password:
            return jsonify({'error': 'Имя и пароль обязательны'}), 400
        
        if len(name) < 2:
            return jsonify({'error': 'Имя минимум 2 символа'}), 400
        
        if len(password) < 4:
            return jsonify({'error': 'Пароль минимум 4 символа'}), 400
        
        existing = db.get_player(name)
        if existing:
            return jsonify({'error': 'Игрок уже существует'}), 400
        
        password_hash = hashlib.md5(password.encode()).hexdigest()
        player_id = db.create_player(name, password_hash)
        
        return jsonify({
            'success': True,
            'player': {'name': name, 'id': player_id}
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        name = data.get('name', '').strip()
        password = data.get('password', '').strip()
        
        player = db.get_player(name)
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        
        if player[2] != hashlib.md5(password.encode()).hexdigest():
            return jsonify({'error': 'Неверный пароль'}), 401
        
        stats = db.get_stats(player[0])
        
        return jsonify({
            'success': True,
            'player': {
                'name': player[1],
                'id': player[0],
                'rating': stats['rating'],
                'crystals': stats['crystals'],
                'wins': stats['wins'],
                'matches': stats['matches'],
                'goals': stats['goals']
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    try:
        conn = sqlite3.connect('football.db')
        c = conn.cursor()
        c.execute('''
            SELECT p.name, s.rating, s.wins, s.matches, s.goals
            FROM players p
            JOIN stats s ON p.id = s.player_id
            ORDER BY s.rating DESC
            LIMIT 100
        ''')
        rows = c.fetchall()
        conn.close()
        
        result = []
        for i, row in enumerate(rows, 1):
            result.append({
                'rank': i,
                'name': row[0],
                'rating': row[1],
                'wins': row[2],
                'matches': row[3],
                'goals': row[4]
            })
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== HEALTH CHECK ===========================
# ============================================================

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'lobbies': len(lobbies)
    })


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'game': 'STREET FOOTBALL LEGENDS',
        'version': '1.0.0',
        'endpoints': [
            '/api/health',
            '/api/register',
            '/api/login',
            '/api/leaderboard',
            '/api/lobby/create',
            '/api/lobby/list',
            '/api/lobby/join',
            '/api/lobby/start',
            '/api/lobby/leave',
            '/api/lobby/get/<lobby_id>'
        ]
    })


# ============================================================
# ==================== RUN ====================================
# ============================================================

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
