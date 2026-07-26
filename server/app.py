import os
import sys
import json
import hashlib
import random
import sqlite3
import uuid
import time
import math
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app, origins=['*'])

# ============================================================
# ==================== ХРАНИЛИЩЕ ==============================
# ============================================================

lobbies = {}
matches = {}
match_clients = {}

# ============================================================
# ==================== КОНСТАНТЫ ==============================
# ============================================================

FIELD_W = 1200
FIELD_H = 700
PLAYER_RADIUS = 18
BALL_RADIUS = 10
GOAL_W = 30
GOAL_H = 180
PLAYER_SPEED = 3.5

# ============================================================
# ==================== КЛАСС МАТЧА ===========================
# ============================================================

class Match:
    def __init__(self, match_id, players_list, mode='1x1'):
        self.id = match_id
        self.mode = mode
        self.players = {}
        self.ball = {'x': 600, 'y': 350, 'vx': 0, 'vy': 0}
        self.score = {'home': 0, 'away': 0}
        self.time = 0
        self.status = 'playing'
        self.goal_cooldown = 0
        self.last_update = time.time()
        
        self.init_players(players_list)
    
    def init_players(self, players_list):
        home_positions = [(250, 350)]
        away_positions = [(950, 350)]
        
        if len(players_list) > 2:
            home_positions = [(250, 290), (250, 410)]
            away_positions = [(950, 290), (950, 410)]
        if len(players_list) > 4:
            home_positions = [(220, 250), (220, 350), (220, 450)]
            away_positions = [(980, 250), (980, 350), (980, 450)]
        
        for i, name in enumerate(players_list):
            if i < len(home_positions):
                pos = home_positions[i]
                team = 'home'
            else:
                pos = away_positions[i - len(home_positions)]
                team = 'away'
            
            self.players[name] = {
                'x': pos[0],
                'y': pos[1],
                'vx': 0,
                'vy': 0,
                'team': team,
                'hasBall': i == 0,
                'name': name,
                'moving': False,
                'radius': PLAYER_RADIUS
            }
        
        if players_list:
            first = players_list[0]
            self.ball['x'] = self.players[first]['x'] + 22
            self.ball['y'] = self.players[first]['y']
    
    def start_move(self, player_name, direction):
        if player_name not in self.players:
            return False
        
        player = self.players[player_name]
        dx = direction.get('dx', 0)
        dy = direction.get('dy', 0)
        
        if dx != 0 and dy != 0:
            dx *= 0.707
            dy *= 0.707
        
        player['vx'] = dx * PLAYER_SPEED
        player['vy'] = dy * PLAYER_SPEED
        player['moving'] = True
        
        if player['hasBall']:
            self.ball['vx'] = player['vx']
            self.ball['vy'] = player['vy']
        
        return True
    
    def stop_move(self, player_name):
        if player_name not in self.players:
            return False
        
        player = self.players[player_name]
        player['vx'] = 0
        player['vy'] = 0
        player['moving'] = False
        
        if player['hasBall']:
            self.ball['vx'] = 0
            self.ball['vy'] = 0
        
        return True
    
    def shoot(self, player_name, target_x, target_y):
        if player_name not in self.players:
            return None
        
        player = self.players[player_name]
        if not player['hasBall']:
            return None
        
        if self.goal_cooldown > 0:
            return None
        
        dx = target_x - player['x']
        dy = target_y - player['y']
        dist = math.sqrt(dx*dx + dy*dy)
        
        if dist > 0:
            power = 5 + random.random() * 3
            angle = math.atan2(dy, dx) + (random.random() - 0.5) * 0.12
            
            self.ball['vx'] = power * math.cos(angle)
            self.ball['vy'] = power * math.sin(angle)
            player['hasBall'] = False
            
            return {
                'ball_vx': self.ball['vx'],
                'ball_vy': self.ball['vy'],
                'player': player_name
            }
        
        return None
    
    def tackle(self, player_name):
        if player_name not in self.players:
            return {'success': False}
        
        player = self.players[player_name]
        
        for p in self.players.values():
            if p['team'] != player['team'] and p['hasBall']:
                dist = math.sqrt((p['x']-player['x'])**2 + (p['y']-player['y'])**2)
                if dist < 50:
                    p['hasBall'] = False
                    player['hasBall'] = True
                    self.ball['x'] = player['x'] + 22
                    self.ball['y'] = player['y']
                    self.ball['vx'] = 0
                    self.ball['vy'] = 0
                    return {'success': True, 'new_owner': player_name}
        
        return {'success': False}
    
    def update(self):
        if self.status != 'playing':
            return
        
        self.time += 1/30
        self.goal_cooldown = max(0, self.goal_cooldown - 1)
        
        for name, player in self.players.items():
            if player['moving']:
                player['x'] += player['vx']
                player['y'] += player['vy']
                
                player['x'] = max(40, min(1160, player['x']))
                player['y'] = max(40, min(660, player['y']))
                
                if player['hasBall']:
                    self.ball['x'] = player['x'] + 22
                    self.ball['y'] = player['y']
                    self.ball['vx'] = 0
                    self.ball['vy'] = 0
        
        if self.ball['vx'] != 0 or self.ball['vy'] != 0:
            self.ball['x'] += self.ball['vx']
            self.ball['y'] += self.ball['vy']
            self.ball['vx'] *= 0.98
            self.ball['vy'] *= 0.98
            
            if abs(self.ball['vx']) < 0.05:
                self.ball['vx'] = 0
            if abs(self.ball['vy']) < 0.05:
                self.ball['vy'] = 0
            
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
        
        self.check_goals()
    
    def check_goals(self):
        if self.goal_cooldown > 0:
            return
        
        if self.ball['x'] < 35 and self.ball['y'] > 260 and self.ball['y'] < 440:
            if self.ball['vx'] < -0.2:
                self.score['away'] += 1
                self.goal_cooldown = 60
                self.reset_ball()
                return
        
        if self.ball['x'] > 1165 and self.ball['y'] > 260 and self.ball['y'] < 440:
            if self.ball['vx'] > 0.2:
                self.score['home'] += 1
                self.goal_cooldown = 60
                self.reset_ball()
                return
    
    def reset_ball(self):
        self.ball['x'] = 600
        self.ball['y'] = 350
        self.ball['vx'] = (random.random() - 0.5) * 0.8
        self.ball['vy'] = (random.random() - 0.5) * 0.8
        for p in self.players.values():
            p['hasBall'] = False
        first = list(self.players.keys())[0]
        self.players[first]['hasBall'] = True
    
    def get_state(self):
        players_data = {}
        for name, p in self.players.items():
            players_data[name] = {
                'x': p['x'],
                'y': p['y'],
                'team': p['team'],
                'hasBall': p['hasBall'],
                'moving': p['moving']
            }
        
        return {
            'players': players_data,
            'ball': self.ball,
            'score': self.score,
            'time': self.time,
            'status': self.status
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
        
        match_id = 'match_' + str(uuid.uuid4())[:8]
        match = Match(match_id, lobby['players'], lobby['mode'])
        matches[match_id] = match
        
        lobby['match_id'] = match_id
        match_clients[match_id] = lobby['players']
        
        # Запускаем поток обновления
        def match_loop():
            while match_id in matches:
                match = matches[match_id]
                if match.status == 'playing':
                    match.update()
                time.sleep(1/30)
        
        thread = threading.Thread(target=match_loop, daemon=True)
        thread.start()
        
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


@app.route('/api/match/state/<match_id>', methods=['GET'])
def get_match_state(match_id):
    try:
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        return jsonify(match.get_state())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/move', methods=['POST'])
def match_move():
    try:
        data = request.json
        match_id = data.get('match_id')
        player_name = data.get('player_name')
        direction = data.get('direction', {})
        
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        match.start_move(player_name, direction)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/stop', methods=['POST'])
def match_stop():
    try:
        data = request.json
        match_id = data.get('match_id')
        player_name = data.get('player_name')
        
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        match.stop_move(player_name)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/shoot', methods=['POST'])
def match_shoot():
    try:
        data = request.json
        match_id = data.get('match_id')
        player_name = data.get('player_name')
        target_x = data.get('target_x', 1150)
        target_y = data.get('target_y', 350)
        
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        result = match.shoot(player_name, target_x, target_y)
        
        return jsonify({'success': True if result else False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/tackle', methods=['POST'])
def match_tackle():
    try:
        data = request.json
        match_id = data.get('match_id')
        player_name = data.get('player_name')
        
        if match_id not in matches:
            return jsonify({'error': 'Матч не найден'}), 404
        
        match = matches[match_id]
        result = match.tackle(player_name)
        
        return jsonify({'success': result['success']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/leave', methods=['POST'])
def match_leave():
    try:
        data = request.json
        match_id = data.get('match_id')
        
        if match_id in matches:
            match = matches[match_id]
            match.status = 'finished'
            
            def delete_match():
                time.sleep(5)
                if match_id in matches:
                    del matches[match_id]
                    if match_id in match_clients:
                        del match_clients[match_id]
            
            threading.Thread(target=delete_match, daemon=True).start()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
            '/api/match/move',
            '/api/match/stop',
            '/api/match/shoot',
            '/api/match/tackle',
            '/api/match/leave'
        ]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
