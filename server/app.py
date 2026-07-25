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
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_online DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                player_id INTEGER PRIMARY KEY,
                matches INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                goals_scored INTEGER DEFAULT 0,
                goals_conceded INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                total_rating INTEGER DEFAULT 50,
                base_rating INTEGER DEFAULT 50,
                crystals INTEGER DEFAULT 100,
                tournaments_won INTEGER DEFAULT 0,
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                skin_name TEXT NOT NULL,
                slot_id INTEGER,
                rarity TEXT NOT NULL,
                equipped BOOLEAN DEFAULT 0,
                unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                pack_type TEXT NOT NULL,
                opened BOOLEAN DEFAULT 0,
                bought_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player_id) REFERENCES players(id)
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS skins (
                name TEXT PRIMARY KEY,
                slot_id INTEGER NOT NULL,
                rarity TEXT NOT NULL,
                rating_bonus INTEGER DEFAULT 0,
                speed_bonus INTEGER DEFAULT 0,
                power_bonus INTEGER DEFAULT 0,
                accuracy_bonus INTEGER DEFAULT 0,
                defense_bonus INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        self.init_skins()
    
    def init_skins(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM skins')
        if c.fetchone()[0] == 0:
            skins = [
                ('Повязка', 1, 'common', 0, 1, 0, 0, 0),
                ('Бандана', 1, 'uncommon', 1, 3, 0, 0, 0),
                ('Шлем', 1, 'rare', 2, 5, 0, 0, 2),
                ('Корона', 1, 'epic', 5, 8, 0, 5, 0),
                ('Золотой шлем', 1, 'legendary', 8, 12, 0, 0, 8),
                ('Нимб бога', 1, 'mythic', 10, 20, 0, 10, 0),
                ('Майка', 2, 'common', 0, 0, 1, 0, 0),
                ('Футболка', 2, 'uncommon', 1, 0, 3, 0, 0),
                ('Броня', 2, 'rare', 2, 0, 5, 0, 2),
                ('Латы', 2, 'epic', 5, 0, 8, 0, 5),
                ('Золотая броня', 2, 'legendary', 8, 0, 12, 0, 8),
                ('Доспехи бога', 2, 'mythic', 10, 0, 20, 0, 10),
                ('Шорты', 3, 'common', 0, 0, 0, 1, 0),
                ('Наголенники', 3, 'uncommon', 1, 0, 0, 3, 0),
                ('Щитки', 3, 'rare', 2, 2, 0, 5, 0),
                ('Поножи', 3, 'epic', 5, 0, 0, 8, 0),
                ('Золотые поножи', 3, 'legendary', 8, 0, 0, 12, 0),
                ('Ноги бога', 3, 'mythic', 10, 0, 0, 20, 0),
                ('Кеды', 4, 'common', 0, 1, 0, 0, 0),
                ('Кроссовки', 4, 'uncommon', 1, 3, 0, 1, 0),
                ('Бутсы', 4, 'rare', 2, 5, 0, 3, 0),
                ('Молнии', 4, 'epic', 5, 8, 0, 5, 0),
                ('Золотые бутсы', 4, 'legendary', 8, 12, 0, 8, 0),
                ('Ботинки бога', 4, 'mythic', 10, 20, 0, 10, 0),
                ('Нарукавник', 5, 'common', 0, 0, 0, 0, 1),
                ('Перчатки', 5, 'uncommon', 1, 0, 1, 0, 3),
                ('Напульсник', 5, 'rare', 2, 0, 3, 0, 5),
                ('Амулет', 5, 'epic', 4, 0, 5, 0, 8),
                ('Золотой амулет', 5, 'legendary', 7, 0, 8, 0, 12),
                ('Артефакт бога', 5, 'mythic', 9, 0, 10, 0, 20),
            ]
            for skin in skins:
                c.execute('INSERT INTO skins VALUES (?, ?, ?, ?, ?, ?, ?, ?)', skin)
            conn.commit()
        conn.close()
    
    def create_player(self, player):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO players (name, password_hash) VALUES (?, ?)', (player.name, player.password_hash))
        player_id = c.lastrowid
        c.execute('INSERT INTO stats (player_id) VALUES (?)', (player_id,))
        c.execute('INSERT INTO inventory (player_id, skin_name, rarity, equipped) VALUES (?, "Повязка", "common", 1)', (player_id,))
        conn.commit()
        conn.close()
        player.id = player_id
        return player
    
    def get_player_by_name(self, name):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT id, name, password_hash, created_at FROM players WHERE name = ?', (name,))
        row = c.fetchone()
        conn.close()
        if row:
            return Player(row[0], row[1], row[2], row[3])
        return None
    
    def get_player_stats(self, player_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT matches, wins, losses, draws, goals_scored, goals_conceded, streak, best_streak, total_rating, base_rating, crystals, tournaments_won FROM stats WHERE player_id = ?', (player_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'matches': row[0], 'wins': row[1], 'losses': row[2], 'draws': row[3], 'goals_scored': row[4], 'goals_conceded': row[5], 'streak': row[6], 'best_streak': row[7], 'total_rating': row[8], 'base_rating': row[9], 'crystals': row[10], 'tournaments_won': row[11]}
        return {}
    
    def update_stats(self, player_id, data):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        current = self.get_player_stats(player_id)
        new_matches = current['matches'] + data.get('matches', 0)
        new_wins = current['wins'] + data.get('wins', 0)
        new_losses = current['losses'] + data.get('losses', 0)
        new_draws = current['draws'] + data.get('draws', 0)
        new_goals_scored = current['goals_scored'] + data.get('goals_scored', 0)
        new_goals_conceded = current['goals_conceded'] + data.get('goals_conceded', 0)
        new_crystals = current['crystals'] + data.get('crystals', 0)
        new_rating = current['total_rating'] + data.get('rating', 0)
        if data.get('wins', 0) > 0:
            new_streak = current['streak'] + 1
            new_best_streak = max(current['best_streak'], new_streak)
        elif data.get('losses', 0) > 0:
            new_streak = 0
            new_best_streak = current['best_streak']
        else:
            new_streak = current['streak']
            new_best_streak = current['best_streak']
        c.execute('UPDATE stats SET matches=?, wins=?, losses=?, draws=?, goals_scored=?, goals_conceded=?, streak=?, best_streak=?, crystals=?, total_rating=? WHERE player_id=?', (new_matches, new_wins, new_losses, new_draws, new_goals_scored, new_goals_conceded, new_streak, new_best_streak, new_crystals, new_rating, player_id))
        conn.commit()
        conn.close()
    
    def get_player_inventory(self, player_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT skin_name, slot_id, rarity, equipped, unlocked_at FROM inventory WHERE player_id = ?', (player_id,))
        rows = c.fetchall()
        conn.close()
        return [{'skin_name': r[0], 'slot_id': r[1], 'rarity': r[2], 'equipped': bool(r[3]), 'unlocked_at': r[4]} for r in rows]
    
    def add_skin_to_inventory(self, player_id, skin):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO inventory (player_id, skin_name, slot_id, rarity, equipped) VALUES (?, ?, ?, ?, 0)', (player_id, skin['name'], skin['slot_id'], skin['rarity']))
        conn.commit()
        conn.close()
    
    def equip_skin(self, player_id, slot_id, skin_name):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE inventory SET equipped=0 WHERE player_id=? AND slot_id=?', (player_id, slot_id))
        c.execute('UPDATE inventory SET equipped=1 WHERE player_id=? AND skin_name=?', (player_id, skin_name))
        conn.commit()
        conn.close()
    
    def has_skin(self, player_id, skin_name):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM inventory WHERE player_id=? AND skin_name=?', (player_id, skin_name))
        count = c.fetchone()[0]
        conn.close()
        return count > 0
    
    def calculate_total_rating(self, player_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT base_rating FROM stats WHERE player_id=?', (player_id,))
        base = c.fetchone()[0]
        c.execute('SELECT s.rating_bonus FROM inventory i JOIN skins s ON i.skin_name=s.name WHERE i.player_id=? AND i.equipped=1', (player_id,))
        rows = c.fetchall()
        conn.close()
        total = base + sum(r[0] for r in rows)
        return min(total, 99)
    
    def update_total_rating(self, player_id, total_rating):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE stats SET total_rating=? WHERE player_id=?', (total_rating, player_id))
        conn.commit()
        conn.close()
    
    def update_rating(self, player_id, bonus):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE stats SET total_rating=MIN(total_rating+?, 99) WHERE player_id=?', (bonus, player_id))
        conn.commit()
        conn.close()
    
    def get_leaderboard(self, limit=100):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT p.name, s.total_rating, s.wins, s.matches, s.goals_scored, s.crystals, p.last_online FROM players p JOIN stats s ON p.id=s.player_id ORDER BY s.total_rating DESC, s.wins DESC LIMIT ?', (limit,))
        rows = c.fetchall()
        conn.close()
        return [{'rank': i+1, 'name': r[0], 'rating': r[1], 'wins': r[2], 'matches': r[3], 'goals': r[4], 'crystals': r[5], 'last_online': r[6]} for i, r in enumerate(rows)]
    
    def create_pack(self, pack):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO packs (player_id, pack_type, opened) VALUES (?, ?, 0)', (pack.player_id, pack.pack_type))
        pack.id = c.lastrowid
        conn.commit()
        conn.close()
        return pack
    
    def get_pack(self, pack_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT id, player_id, pack_type, opened, bought_at FROM packs WHERE id=?', (pack_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'id': row[0], 'player_id': row[1], 'pack_type': row[2], 'opened': bool(row[3]), 'bought_at': row[4]}
        return None
    
    def open_pack(self, pack_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE packs SET opened=1 WHERE id=?', (pack_id,))
        conn.commit()
        conn.close()
    
    def update_crystals(self, player_id, amount):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE stats SET crystals=crystals+? WHERE player_id=?', (amount, player_id))
        conn.commit()
        conn.close()
    
    def get_player_achievements(self, player_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT achievement_id, unlocked_at FROM achievements WHERE player_id=?', (player_id,))
        rows = c.fetchall()
        conn.close()
        return [{'achievement_id': r[0], 'unlocked_at': r[1]} for r in rows]


# ============================================================
# ==================== MODELS ================================
# ============================================================

class Player:
    def __init__(self, name, password=None, password_hash=None, created_at=None, id=None):
        self.id = id
        self.name = name
        self.password_hash = password_hash if password_hash else hashlib.md5(password.encode()).hexdigest()
        self.created_at = created_at or datetime.now()
        self.total_rating = 50
        self.crystals = 100
    
    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'created_at': str(self.created_at), 'total_rating': self.total_rating}


class Pack:
    def __init__(self, pack_type, player_id, id=None):
        self.id = id
        self.pack_type = pack_type
        self.player_id = player_id
        self.opened = False
        self.drop_rates = {
            'common': {'common': 60, 'uncommon': 30, 'rare': 10},
            'rare': {'uncommon': 40, 'rare': 35, 'epic': 25},
            'epic': {'rare': 30, 'epic': 45, 'legendary': 25},
            'legendary': {'epic': 30, 'legendary': 50, 'mythic': 20}
        }
    
    def open(self):
        self.opened = True
        rates = self.drop_rates.get(self.pack_type, {})
        total = sum(rates.values())
        r = random.random() * total
        for key, weight in rates.items():
            r -= weight
            if r <= 0:
                rarity = key
                break
        else:
            rarity = 'common'
        
        skins = {
            'common': ['Повязка', 'Майка', 'Шорты', 'Кеды', 'Нарукавник'],
            'uncommon': ['Бандана', 'Футболка', 'Наголенники', 'Кроссовки', 'Перчатки'],
            'rare': ['Шлем', 'Броня', 'Щитки', 'Бутсы', 'Напульсник'],
            'epic': ['Корона', 'Латы', 'Поножи', 'Молнии', 'Амулет'],
            'legendary': ['Золотой шлем', 'Золотая броня', 'Золотые поножи', 'Золотые бутсы', 'Золотой амулет'],
            'mythic': ['Нимб бога', 'Доспехи бога', 'Ноги бога', 'Ботинки бога', 'Артефакт бога']
        }
        skin_name = random.choice(skins.get(rarity, ['Повязка']))
        
        conn = sqlite3.connect('football.db')
        c = conn.cursor()
        c.execute('SELECT name, slot_id, rarity, rating_bonus, speed_bonus, power_bonus, accuracy_bonus, defense_bonus FROM skins WHERE name=?', (skin_name,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return {'name': row[0], 'slot_id': row[1], 'rarity': row[2], 'rating_bonus': row[3], 'speed_bonus': row[4], 'power_bonus': row[5], 'accuracy_bonus': row[6], 'defense_bonus': row[7]}
        return {'name': skin_name, 'rarity': rarity}
    
    def to_dict(self):
        return {'id': self.id, 'pack_type': self.pack_type, 'opened': self.opened}


# ============================================================
# ==================== FLASK APP =============================
# ============================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
CORS(app, origins=['*'])
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

db = Database()

# ============================================================
# ==================== API ROUTES ============================
# ============================================================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'game': 'STREET FOOTBALL LEGENDS',
        'version': '1.0.0',
        'endpoints': [
            '/api/register',
            '/api/login',
            '/api/profile/<name>',
            '/api/update_stats',
            '/api/leaderboard',
            '/api/buy_pack',
            '/api/open_pack',
            '/api/equip_skin',
            '/api/health',
            '/api/lobby/create',
            '/api/lobby/list',
            '/api/lobby/join',
            '/api/lobby/start',
            '/api/lobby/leave'
        ]
    })

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat(), 'database': 'connected'})

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
        if db.get_player_by_name(name):
            return jsonify({'error': 'Игрок уже существует'}), 400
        player = Player(name, password)
        db.create_player(player)
        return jsonify({'success': True, 'player': player.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        name = data.get('name', '').strip()
        password = data.get('password', '').strip()
        player = db.get_player_by_name(name)
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        if player.password_hash != hashlib.md5(password.encode()).hexdigest():
            return jsonify({'error': 'Неверный пароль'}), 401
        return jsonify({'success': True, 'player': player.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile/<name>', methods=['GET'])
def get_profile(name):
    try:
        player = db.get_player_by_name(name)
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        stats = db.get_player_stats(player.id)
        inventory = db.get_player_inventory(player.id)
        achievements = db.get_player_achievements(player.id)
        return jsonify({'player': player.to_dict(), 'stats': stats, 'inventory': inventory, 'achievements': achievements})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/update_stats', methods=['POST'])
def update_stats():
    try:
        data = request.json
        player = db.get_player_by_name(data.get('player_name'))
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        db.update_stats(player.id, {
            'matches': 1,
            'wins': 1 if data.get('match_result') == 'win' else 0,
            'losses': 1 if data.get('match_result') == 'loss' else 0,
            'draws': 1 if data.get('match_result') == 'draw' else 0,
            'goals_scored': data.get('goals_scored', 0),
            'goals_conceded': data.get('goals_conceded', 0),
            'crystals': data.get('crystals_earned', 0),
            'rating': data.get('rating_change', 0)
        })
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    try:
        limit = request.args.get('limit', 100, type=int)
        return jsonify(db.get_leaderboard(limit))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/buy_pack', methods=['POST'])
def buy_pack():
    try:
        data = request.json
        player = db.get_player_by_name(data.get('player_name'))
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        pack_prices = {'common': 100, 'rare': 300, 'epic': 800, 'legendary': 2000}
        price = pack_prices.get(data.get('pack_type'), 0)
        if price == 0:
            return jsonify({'error': 'Неверный тип пака'}), 400
        stats = db.get_player_stats(player.id)
        if stats['crystals'] < price:
            return jsonify({'error': 'Недостаточно кристаллов'}), 400
        pack = Pack(data.get('pack_type'), player.id)
        db.create_pack(pack)
        db.update_crystals(player.id, -price)
        return jsonify({'success': True, 'pack': pack.to_dict(), 'crystals_left': stats['crystals'] - price})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/open_pack', methods=['POST'])
def open_pack():
    try:
        data = request.json
        player = db.get_player_by_name(data.get('player_name'))
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        pack = db.get_pack(data.get('pack_id'))
        if not pack or pack['player_id'] != player.id:
            return jsonify({'error': 'Пак не найден'}), 404
        if pack['opened']:
            return jsonify({'error': 'Пак уже открыт'}), 400
        skin = Pack(pack['pack_type'], player.id).open()
        db.open_pack(pack['id'])
        db.add_skin_to_inventory(player.id, skin)
        if skin.get('rating_bonus', 0) > 0:
            db.update_rating(player.id, skin['rating_bonus'])
        return jsonify({'success': True, 'skin': skin, 'rating_bonus': skin.get('rating_bonus', 0)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/equip_skin', methods=['POST'])
def equip_skin():
    try:
        data = request.json
        player = db.get_player_by_name(data.get('player_name'))
        if not player:
            return jsonify({'error': 'Игрок не найден'}), 404
        if not db.has_skin(player.id, data.get('skin_name')):
            return jsonify({'error': 'Скин не найден'}), 404
        db.equip_skin(player.id, data.get('slot_id'), data.get('skin_name'))
        total_rating = db.calculate_total_rating(player.id)
        db.update_total_rating(player.id, total_rating)
        return jsonify({'success': True, 'total_rating': total_rating})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== ЛОББИ API =============================
# ============================================================

# Хранилище всех лобби (в памяти сервера)
lobbies = {}

# 1. СОЗДАНИЕ ЛОББИ
@app.route('/api/lobby/create', methods=['POST'])
def create_lobby():
    try:
        data = request.json
        if not data.get('host'):
            return jsonify({'error': 'Имя хоста обязательно'}), 400
        
        lobby_id = 'lobby_' + str(uuid.uuid4())[:8]
        lobbies[lobby_id] = {
            'id': lobby_id,
            'name': data.get('name', 'Лобби ' + data['host']),
            'host': data['host'],
            'mode': data.get('mode', '1x1'),
            'players': [data['host']],
            'status': 'waiting',
            'created_at': datetime.now().isoformat()
        }
        return jsonify({'success': True, 'lobby_id': lobby_id, 'lobby': lobbies[lobby_id]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 2. ПОЛУЧЕНИЕ СПИСКА ЛОББИ
@app.route('/api/lobby/list', methods=['GET'])
def list_lobbies():
    try:
        available = [l for l in lobbies.values() if l['status'] == 'waiting' and len(l['players']) < 2]
        return jsonify(available)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 3. ПРИСОЕДИНЕНИЕ К ЛОББИ
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
        if len(lobby['players']) >= 2:
            return jsonify({'error': 'Лобби заполнено'}), 400
        if player in lobby['players']:
            return jsonify({'error': 'Вы уже в лобби'}), 400
        
        lobby['players'].append(player)
        return jsonify({'success': True, 'lobby': lobby})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 4. НАЧАЛО МАТЧА
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
        
        lobby['status'] = 'playing'
        return jsonify({'success': True, 'lobby': lobby})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 5. ВЫХОД ИЗ ЛОББИ
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
        
        return jsonify({'success': True, 'lobby': lobby})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================
# ==================== WEBSOCKET =============================
# ============================================================

@socketio.on('connect')
def handle_connect():
    print(f'Player connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print(f'Player disconnected: {request.sid}')


# ============================================================
# ==================== RUN ===================================
# ============================================================

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
