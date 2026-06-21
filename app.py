import os
from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid

app = Flask(__name__)
# すべてのオリジンからのアクセスを許可
socketio = SocketIO(app, cors_allowed_origins="*")

# プレイヤーデータベース
# 構造: { uid: { "uid": str, "name": str, "points": int, "total_damage": int, "online": bool, "sid": str } }
players = {}
sid_to_uid = {}

# アクティブなバトル管理
# 構造: { battle_id: { "p1": uid, "p2": uid, "p1_dmg": 0, "p2_dmg": 0, "status": str } }
battles = {}

@app.route('/')
def index():
    return "Straw Doll Clicker Online Server is Running!"

@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in sid_to_uid:
        uid = sid_to_uid[sid]
        if uid in players:
            players[uid]['online'] = False
            players[uid]['sid'] = None
        del sid_to_uid[sid]
    broadcast_players()

@socketio.on('register_player')
def handle_register(data):
    sid = request.sid
    uid = data.get('uid')
    name = data.get('name', '名無しさん')
    points = data.get('points', 0)
    total_damage = data.get('total_damage', 0)

    # 新規か既存か
    if not uid:
        uid = str(uuid.uuid4())

    sid_to_uid[sid] = uid
    
    players[uid] = {
        'uid': uid,
        'sid': sid,
        'name': name,
        'points': points,
        'total_damage': total_damage,
        'online': True
    }

    emit('registration_success', {'uid': uid})
    broadcast_players()

@socketio.on('update_player_data')
def handle_update(data):
    sid = request.sid
    if sid in sid_to_uid:
        uid = sid_to_uid[sid]
        if uid in players:
            players[uid]['name'] = data.get('name', players[uid]['name'])
            players[uid]['points'] = data.get('points', 0)
            players[uid]['total_damage'] = data.get('total_damage', 0)
            broadcast_players()

@socketio.on('send_challenge')
def handle_challenge(data):
    sid = request.sid
    target_uid = data.get('target_uid')
    if sid in sid_to_uid:
        challenger_uid = sid_to_uid[sid]
        challenger = players.get(challenger_uid)
        target = players.get(target_uid)

        if challenger and target and target['online'] and target['sid']:
            emit('challenge_received', {
                'challenger_uid': challenger_uid,
                'challenger_name': challenger['name']
            }, to=target['sid'])

@socketio.on('respond_challenge')
def handle_response(data):
    sid = request.sid
    challenger_uid = data.get('challenger_uid')
    accepted = data.get('accepted')

    if sid in sid_to_uid:
        target_uid = sid_to_uid[sid]
        target = players.get(target_uid)
        challenger = players.get(challenger_uid)

        if challenger and target:
            if accepted:
                battle_id = f"battle_{challenger_uid}_{target_uid}"
                battles[battle_id] = {
                    'p1': challenger_uid,
                    'p2': target_uid,
                    'p1_dmg': 0,
                    'p2_dmg': 0,
                    'status': 'active'
                }

                # ルームを作成して接続
                join_room(battle_id, sid=challenger['sid'])
                join_room(battle_id, sid=target['sid'])

                emit('battle_start', {
                    'battle_id': battle_id,
                    'opponent_name': target['name'],
                    'role': 'p1'
                }, to=challenger['sid'])

                emit('battle_start', {
                    'battle_id': battle_id,
                    'opponent_name': challenger['name'],
                    'role': 'p2'
                }, to=target['sid'])
            else:
                if challenger['online'] and challenger['sid']:
                    emit('challenge_rejected', {'msg': f"{target['name']}さんに断られました"}, to=challenger['sid'])

@socketio.on('battle_damage')
def handle_battle_damage(data):
    battle_id = data.get('battle_id')
    damage = data.get('damage', 0)
    sid = request.sid

    if battle_id in battles and sid in sid_to_uid:
        uid = sid_to_uid[sid]
        battle = battles[battle_id]

        if battle['status'] == 'active':
            if uid == battle['p1']:
                battle['p1_dmg'] += damage
            elif uid == battle['p2']:
                battle['p2_dmg'] += damage

            emit('battle_update', {
                'p1_dmg': battle['p1_dmg'],
                'p2_dmg': battle['p2_dmg']
            }, to=battle_id)

@socketio.on('battle_timeout')
def handle_battle_timeout(data):
    battle_id = data.get('battle_id')
    sid = request.sid

    if battle_id in battles and sid in sid_to_uid:
        battle = battles[battle_id]
        if battle['status'] == 'active':
            battle['status'] = 'finished'
            
            p1_dmg = battle['p1_dmg']
            p2_dmg = battle['p2_dmg']
            winner = None
            
            if p1_dmg > p2_dmg:
                winner = 'p1'
            elif p2_dmg > p1_dmg:
                winner = 'p2'
            
            emit('battle_result', {
                'p1_dmg': p1_dmg,
                'p2_dmg': p2_dmg,
                'winner': winner
            }, to=battle_id)

            # ルームを解散
            p1_player = players.get(battle['p1'])
            p2_player = players.get(battle['p2'])
            if p1_player and p1_player['sid']:
                leave_room(battle_id, sid=p1_player['sid'])
            if p2_player and p2_player['sid']:
                leave_room(battle_id, sid=p2_player['sid'])

def broadcast_players():
    # 全プレイヤーのリスト（sidなどのプライベートな値は除外）
    serialized = []
    for p in players.values():
        serialized.append({
            'uid': p['uid'],
            'name': p['name'],
            'points': p['points'],
            'total_damage': p['total_damage'],
            'online': p['online']
        })
    emit('update_players', serialized, broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)

