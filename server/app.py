import os
import sys
import json
import hashlib
import random
import sqlite3
import uuid
import time
import math
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app, origins=['*'])
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ============================================================
# ==================== ХРАНИЛИЩЕ ==============================
# ============================================================

lobbies = {}
matches = {}
subscriptions = {}

# ============================================================
# ==================== КОНСТАНТЫ МАТЧА =======================
# ============================================================

FIELD_W = 1200
FIELD_H = 700
PLAYER_RADIUS = 18
BALL_RADIUS = 10
GOAL_W = 30
GOAL_H = 180
PLAYER_SPEED = 2.2

# ============================================================
# ==================== КЛАСС МАТЧА ===========================
# ============================================================

class Match:
    def __init__(self, match_id, players, mode='2x2'):
        self.id = match_id
        self.mode = mode
        self.players = players  # dict {name: {'x':, 'y':, 'team':, 'isPlayer':}}
        self.ball = {'x': 600, 'y': 350, 'vx': 0, 'vy': 0}
        self.score = {'home': 0, 'away': 0}
        self.time = 0
        self.status = 'waiting'  # waiting, playing, finished
        self.last_update = time.time()
        self.goal_cooldown = 0
        
        # Инициализация позиций игроков
        self.init_positions()
    
    def init_positions(self):
        """Расстановка игроков на поле"""
        player_names = list(self.players.keys())
        
        if self.mode == '2x2':
            home_positions = [(250, 290), (250, 410)]
            away_positions = [(950, 290), (950, 410)]
        else:
            home_positions = [(220, 250), (220, 350), (220, 450)]
            away_positions = [(980, 250), (980, 350), (980, 450)]
        
        for i, name in enumerate(player_names):
            if i < len(home_positions):
                pos = home_positions[i]
                team = 'home'
            else:
                pos = away_positions[i - len(home_positions)]
                team = 'away'
            
            self.players[name] = {
                'x': pos[0],
                'y': pos[1],
                'team': team,
                'isPlayer': i == 0,  # первый игрок - управляемый
                'hasBall': i == 0,
                'vx': 0,
                'vy': 0,
                'radius': PLAYER_RADIUS,
                'name': name
            }
        
        # Мяч у первого игрока
        first = player_names[0]
        self.ball['x'] = self.players[first]['x'] + 22
        self.ball['y'] = self.players[first]['y']
    
    def update(self, actions):
        """Обновление состояния матча"""
        if self.status != 'playing':
            return
        
        self.time += 1/60
        self.goal_cooldown = max(0, self.goal_cooldown - 1)
        
        # Применяем действия игроков
        for player_name, action in actions.items():
            if player_name in self.players:
                self.apply_action(player_name, action)
        
        # Обновляем мяч
        self.update_ball()
        
        # Проверяем голы
        self.check_goals()
        
        # Обновляем ботов (если есть)
        self.update_bots()
    
    def apply_action(self, player_name, action):
        """Применение действия игрока"""
        if player_name not in self.players:
            return
        
        player = self.players[player_name]
        action_type = action.get('type')
        
        if action_type == 'move':
            dx = action.get('dx', 0)
            dy = action.get('dy', 0)
            
            # Нормализация
            if dx != 0 and dy != 0:
                dx *= 0.707
                dy *= 0.707
            
            new_x = player['x'] + dx * PLAYER_SPEED
            new_y = player['y'] + dy * PLAYER_SPEED
            
            # Границы
            new_x = max(40, min(FIELD_W - 40, new_x))
            new_y = max(40, min(FIELD_H - 40, new_y))
            
            player['x'] = new_x
            player['y'] = new_y
            
            # Если игрок с мячом - мяч следует за ним
            if player['hasBall']:
                self.ball['x'] = player['x'] + 22
                self.ball['y'] = player['y']
                self.ball['vx'] = 0
                self.ball['vy'] = 0
        
        elif action_type == 'shoot':
            if player['hasBall'] and self.goal_cooldown == 0:
                # Удар по воротам
                target_x = action.get('target_x', 1150 if player['team'] == 'home' else 50)
                target_y = action.get('target_y', 350)
                
                dx = target_x - player['x']
                dy = target_y - player['y']
                dist = math.sqrt(dx*dx + dy*dy)
                
                if dist > 0:
                    power = 4 + random.random() * 3
                    angle = math.atan2(dy, dx) + (random.random() - 0.5) * 0.12
                    
                    self.ball['vx'] = power * math.cos(angle)
                    self.ball['vy'] = power * math.sin(angle)
                    player['hasBall'] = False
        
        elif action_type == 'pass':
            if player['hasBall']:
                # Пас ближайшему партнеру
                teammates = [p for p in self.players.values() if p['team'] == player['team'] and p['name'] != player_name]
                if teammates:
                    target = min(teammates, key=lambda p: math.sqrt((p['x']-player['x'])**2 + (p['y']-player['y'])**2))
                    dist = math.sqrt((target['x']-player['x'])**2 + (target['y']-player['y'])**2)
                    if dist < 400:
                        power = min(6, max(1.5, dist / 40))
                        angle = math.atan2(target['y']-player['y'], target['x']-player['x'])
                        angle += (random.random() - 0.5) * 0.06
                        
                        self.ball['vx'] = power * math.cos(angle)
                        self.ball['vy'] = power * math.sin(angle)
                        player['hasBall'] = False
        
        elif action_type == 'tackle':
            # Отбор мяча
            for p in self.players.values():
                if p['team'] != player['team'] and p['hasBall']:
                    if math.sqrt((p['x']-player['x'])**2 + (p['y']-player['y'])**2) < 40:
                        angle = math.atan2(p['y']-player['y'], p['x']-player['x'])
                        power = 1.5
                        self.ball['vx'] = power * math.cos(angle + (random.random()-0.5)*0.4)
                        self.ball['vy'] = power * math.sin(angle + (random.random()-0.5)*0.4)
                        p['hasBall'] = False
                        player['hasBall'] = True
                        break
    
    def update_ball(self):
        """Обновление физики мяча"""
        self.ball['x'] += self.ball['vx']
        self.ball['y'] += self.ball['vy']
        self.ball['vx'] *= 0.98
        self.ball['vy'] *= 0.98
        
        if abs(self.ball['vx']) < 0.02:
            self.ball['vx'] = 0
        if abs(self.ball['vy']) < 0.02:
            self.ball['vy'] = 0
        
        # Границы
        margin = 40
        if self.ball['x'] < margin + BALL_RADIUS:
            self.ball['x'] = margin + BALL_RADIUS
            self.ball['vx'] = abs(self.ball['vx']) * 0.3
        if self.ball['x'] > FIELD_W - margin - BALL_RADIUS:
            self.ball['x'] = FIELD_W - margin - BALL_RADIUS
            self.ball['vx'] = -abs(self.ball['vx']) * 0.3
        if self.ball['y'] < margin + BALL_RADIUS:
            self.ball['y'] = margin + BALL_RADIUS
            self.ball['vy'] = abs(self.ball['vy']) * 0.3
        if self.ball['y'] > FIELD_H - margin - BALL_RADIUS:
            self.ball['y'] = FIELD_H - margin - BALL_RADIUS
            self.ball['vy'] = -abs(self.ball['vy']) * 0.3
        
        # Столкновения с игроками
        for player in self.players.values():
            if not player['hasBall']:
                dist = math.sqrt((self.ball['x']-player['x'])**2 + (self.ball['y']-player['y'])**2)
                if dist < player['radius'] + BALL_RADIUS + 2:
                    angle = math.atan2(self.ball['y']-player['y'], self.ball['x']-player['x'])
                    power = 0.4 + random.random() * 0.4
                    self.ball['vx'] = power * math.cos(angle)
                    self.ball['vy'] = power * math.sin(angle)
                    for p in self.players.values():
                        p['hasBall'] = False
                    player['hasBall'] = True
    
    def check_goals(self):
        """Проверка голов"""
        if self.goal_cooldown > 0:
            return
        
        # Левые ворота (home)
        if self.ball['x'] < 35 and self.ball['y'] > 350 - GOAL_H/2 and self.ball['y'] < 350 + GOAL_H/2:
            if self.ball['vx'] < -0.2:
                self.score['away'] += 1
                self.goal_cooldown = 80
                self.reset_ball()
                return
        
        # Правые ворота (away)
        if self.ball['x'] > FIELD_W - 35 and self.ball['y'] > 350 - GOAL_H/2 and self.ball['y'] < 350 + GOAL_H/2:
            if self.ball['vx'] > 0.2:
                self.score['home'] += 1
                self.goal_cooldown = 80
                self.reset_ball()
                return
    
    def reset_ball(self):
        """Сброс мяча"""
        self.ball['x'] = 600
        self.ball['y'] = 350
        self.ball['vx'] = (random.random() - 0.5) * 0.8
        self.ball['vy'] = (random.random() - 0.5) * 0.8
        for p in self.players.values():
            p['hasBall'] = False
        first = list(self.players.keys())[0]
        self.players[first]['hasBall'] = True
    
    def update_bots(self):
        """Обновление ботов (всех кроме первого игрока)"""
        player_names = list(self.players.keys())
        if len(player_names) < 2:
            return
        
        for i, name in enumerate(player_names):
            if i == 0:
                continue  # Это игрок
            
            player = self.players[name]
            # Бот преследует мяч или занимает позицию
            if player['team'] == 'home':
                target_x = self.ball['x'] + 30 if self.ball['x'] < 700 else 950
                target_y = self.ball['y']
            else:
                target_x = self.ball['x'] - 30 if self.ball['x'] > 500 else 250
                target_y = self.ball['y']
            
            dx = target_x - player['x']
            dy = target_y - player['y']
            dist = math.sqrt(dx*dx + dy*dy)
            
            if dist > 3:
                speed = 1.8
                player['x'] += (dx / dist) * speed
                player['y'] += (dy / dist) * speed
    
    def get_state(self):
        """Получение текущего состояния матча"""
        return {
            'id': self.id,
            'mode': self.mode,
            'status': self.status,
            'players': self.players,
            'ball': self.ball,
            'score': self.score,
            'time': self.time
        }


# ============================================================
# ==================== API ЛОББИ ==============================
# ============================================================

@app.route('/api/lobby/create', methods=['POST'])
def create_lobby():
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
            'status': 'waiting',
            'created_at': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'lobby_id': lobby_id,
            'lobby': lobbies[lobby_id]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/list', methods=['GET'])
def list_lobbies():
    try:
        available = []
        for lobby_id, lobby in lobbies.items():
            if lobby['status'] == 'waiting' and len(lobby['players']) < 2:
                available.append(lobby)
        return jsonify(available)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/join', methods=['POST'])
def join_lobby():
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
        
        notify_lobby_update(lobby_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/start', methods=['POST'])
def start_lobby():
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
        
        # Создаём матч
        match_id = 'match_' + str(uuid.uuid4())[:8]
        players_dict = {}
        for p in lobby['players']:
            players_dict[p] = {'name': p}
        
        match = Match(match_id, players_dict, lobby['mode'])
        match.status = 'playing'
        matches[match_id] = match
        
        lobby['match_id'] = match_id
        
        notify_lobby_update(lobby_id)
        
        # Запускаем поток для обновления матча
        start_match_thread(match_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby,
            'match_id': match_id
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/leave', methods=['POST'])
def leave_lobby():
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
            return jsonify({'success': True, 'deleted': True})
        
        if lobby['host'] == player and len(lobby['players']) > 0:
            lobby['host'] = lobby['players'][0]
        
        notify_lobby_update(lobby_id)
        
        return jsonify({
            'success': True,
            'lobby': lobby
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/lobby/get/<lobby_id>', methods=['GET'])
def get_lobby(lobby_id):
    try:
        if lobby_id not in lobbies:
            return jsonify({'error': 'Лобби не найдено'}), 404
        return jsonify(lobbies[lobby_id])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== API МАТЧА =============================
# ============================================================

@app.route('/api/match/state/<match_id>', methods=['GET'])
def get_match_state(match_id):
    try:
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        state = match.get_state()
        
        # Отправляем только нужные данные клиенту
        players_data = {}
        for name, data in state['players'].items():
            players_data[name] = {
                'x': data['x'],
                'y': data['y'],
                'team': data['team'],
                'hasBall': data.get('hasBall', False),
                'name': name
            }
        
        return jsonify({
            'players': players_data,
            'ball': state['ball'],
            'score': state['score'],
            'time': state['time'],
            'status': state['status']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/action', methods=['POST'])
def match_action():
    try:
        data = request.json
        match_id = data.get('match_id')
        player_name = data.get('player_name')
        action = data.get('action')
        
        if not match_id or not player_name or not action:
            return jsonify({'error': 'Недостаточно данных'}), 400
        
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        
        if match.status != 'playing':
            return jsonify({'error': 'Матч не активен'}), 400
        
        # Применяем действие
        match.apply_action(player_name, action)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== ПОТОКИ ОБНОВЛЕНИЙ =====================
# ============================================================

match_threads = {}

def start_match_thread(match_id):
    """Запуск потока для обновления матча"""
    if match_id in match_threads:
        return
    
    def match_loop():
        while match_id in matches:
            match = matches[match_id]
            if match.status == 'playing':
                # Обновляем матч
                match.update({})
                
                # Отправляем состояние всем подписанным клиентам
                state = match.get_state()
                socketio.emit('match_update', {
                    'match_id': match_id,
                    'state': state
                }, room='match_' + match_id)
            
            time.sleep(1/30)  # 30 FPS
    
    thread = Thread(target=match_loop, daemon=True)
    thread.start()
    match_threads[match_id] = thread


# ============================================================
# ==================== WEBSOCKET ==============================
# ============================================================

def notify_lobby_update(lobby_id):
    """Отправка обновления лобби"""
    if lobby_id not in lobbies:
        return
    
    lobby = lobbies[lobby_id]
    
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
    if request.sid in subscriptions:
        del subscriptions[request.sid]
    print(f'🔌 Клиент отключен: {request.sid}')


@socketio.on('subscribe_lobby')
def handle_subscribe(data):
    lobby_id = data.get('lobby_id')
    if lobby_id:
        subscriptions[request.sid] = lobby_id
        if lobby_id in lobbies:
            emit('lobby_update', {
                'lobby_id': lobby_id,
                'lobby': lobbies[lobby_id]
            })


@socketio.on('unsubscribe_lobby')
def handle_unsubscribe():
    if request.sid in subscriptions:
        del subscriptions[request.sid]


@socketio.on('subscribe_match')
def handle_subscribe_match(data):
    match_id = data.get('match_id')
    if match_id:
        join_room('match_' + match_id)
        if match_id in matches:
            state = matches[match_id].get_state()
            emit('match_update', {
                'match_id': match_id,
                'state': state
            })


@socketio.on('unsubscribe_match')
def handle_unsubscribe_match(data):
    match_id = data.get('match_id')
    if match_id:
        leave_room('match_' + match_id)


# ============================================================
# ==================== DATABASE ==============================
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


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'lobbies': len(lobbies),
        'matches': len(matches)
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
            '/api/lobby/get/<lobby_id>',
            '/api/match/state/<match_id>',
            '/api/match/action'
        ]
    })


# ============================================================
# ==================== RUN ====================================
# ============================================================

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
