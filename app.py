```python
import os
from flask import Flask
from flask_socketio import SocketIO, emit

app = Flask(__name__)
# すべてのオリジンからの接続を許可
socketio = SocketIO(app, cors_allowed_origins="*")

# 接続中のプレイヤー情報を保持する辞書
# { sid: { "name": name, "points": points, "totalDamage": totalDamage, "status": "idle" } }
players = {}

# アクティブな決闘情報
# { duel_id: { "challenger": sid, "target": sid, "challenger_score": 0, "target_score": 0, "timeout": ... } }
duels = {}

@app.route('/')
def index():
    return "Straw Doll Game Online Server is Running!"

@socketio.on('connect')
def handle_connect():
    # 接続直後はまだ名前未登録状態
    pass

@socketio.on('join_game')
def handle_join(data):
    sid = data.get('sid') or ""
    # Socket.ioの実際のセッションIDを使用するか、クライアントから送られた一意のIDを使用
    user_sid = data.get('userId') or ""
    
    players[user_sid] = {
        "sid": user_sid,
        "name": data.get("name", "名無し"),
        "points": data.get("points", 0),
        "totalDamage": data.get("totalDamage", 0),
        "status": "idle",
        "socket_id": data.get('socketId')
    }
    # 全員に最新のプレイヤーリストを送信
    broadcast_players()

@socketio.on('update_status')
def handle_update(data):
    user_sid = data.get('userId')
    if user_sid in players:
        players[user_sid]["points"] = data.get("points", players[user_sid]["points"])
        players[user_sid]["totalDamage"] = data.get("totalDamage", players[user_sid]["totalDamage"])
        broadcast_players()

@socketio.on('disconnect_player')
def handle_disconnect_player(data):
    user_sid = data.get('userId')
    if user_sid in players:
        del players[user_sid]
        broadcast_players()

@socketio.on('disconnect')
def handle_disconnect():
    # 実際の切断時はsocket.idに紐づくプレイヤーを削除
    target_uid = None
    for uid, p in list(players.items()):
        # クライアント側の定期的な生存確認や切断処理で補完
        pass

# 決闘リクエスト
@socketio.on('challenge_request')
def handle_challenge(data):
    challenger_id = data.get('challengerId')
    target_id = data.get('targetId')
    
    if challenger_id in players and target_id in players:
        # 相手が戦闘中ではないか確認
        if players[target_id]["status"] != "idle":
            emit('challenge_rejected', {"reason": "相手は現在戦闘中、または退席中です。"}, to=data.get('socketId'))
            return
            
        players[challenger_id]["status"] = "challenging"
        
        # ターゲットに対戦要請を送信
        # シンプルに全員にブロードキャストして、宛先IDが合致するクライアントでモーダルを出す
        emit('receive_challenge', {
            "challengerId": challenger_id,
            "challengerName": players[challenger_id]["name"],
            "targetId": target_id
        }, broadcast=True)

# 決闘承諾
@socketio.on('challenge_accept')
def handle_accept(data):
    challenger_id = data.get('challengerId')
    target_id = data.get('targetId')
    
    if challenger_id in players and target_id in players:
        players[challenger_id]["status"] = "fighting"
        players[target_id]["status"] = "fighting"
        
        duel_id = f"duel_{challenger_id}_{target_id}"
        duels[duel_id] = {
            "challenger": challenger_id,
            "target": target_id,
            "challenger_score": 0,
            "target_score": 0
        }
        
        # 決闘開始を両者に通知
        emit('duel_start', {
            "duelId": duel_id,
            "challengerId": challenger_id,
            "targetId": target_id,
            "challengerName": players[challenger_id]["name"],
            "targetName": players[target_id]["name"]
        }, broadcast=True)
        broadcast_players()

# 決闘拒否
@socketio.on('challenge_decline')
def handle_decline(data):
    challenger_id = data.get('challengerId')
    if challenger_id in players:
        players[challenger_id]["status"] = "idle"
    emit('duel_declined', {"challengerId": challenger_id}, broadcast=True)
    broadcast_players()

# 決闘中のダメージ同期
@socketio.on('duel_progress')
def handle_duel_progress(data):
    duel_id = data.get('duelId')
    player_id = data.get('userId')
    dmg = data.get('damage', 0)
    
    if duel_id in duels:
        duel = duels[duel_id]
        if duel["challenger"] == player_id:
            duel["challenger_score"] += dmg
        elif duel["target"] == player_id:
            duel["target_score"] += dmg
            
        # リアルタイムスコアを同期
        emit('duel_score_update', {
            "duelId": duel_id,
            "challengerScore": duel["challenger_score"],
            "targetScore": duel["target_score"]
        }, broadcast=True)

# 決闘終了
@socketio.on('duel_end')
def handle_duel_end(data):
    duel_id = data.get('duelId')
    if duel_id in duels:
        duel = duels[duel_id]
        c_id = duel["challenger"]
        t_id = duel["target"]
        
        if c_id in players: players[c_id]["status"] = "idle"
        if t_id in players: players[t_id]["status"] = "idle"
        
        # 結果判定
        c_score = duel["challenger_score"]
        t_score = duel["target_score"]
        
        winner_id = None
        loser_id = None
        if c_score > t_score:
            winner_id = c_id
            loser_id = t_id
        elif t_score > c_score:
            winner_id = t_id
            loser_id = c_id
            
        # 勝敗に応じたポイント移動処理（例: 敗者からポイントの10%または最低100ptを勝者に移動）
        point_transfer = 0
        if winner_id and loser_id:
            if loser_id in players and winner_id in players:
                loser_points = players[loser_id]["points"]
                point_transfer = int(loser_points * 0.1)
                if point_transfer < 100:
                    point_transfer = 100
                if point_transfer > loser_points:
                    point_transfer = int(loser_points)
                
                players[winner_id]["points"] += point_transfer
                players[loser_id]["points"] -= point_transfer
                
        emit('duel_result', {
            "duelId": duel_id,
            "winnerId": winner_id,
            "loserId": loser_id,
            "transfer": point_transfer,
            "challengerScore": c_score,
            "targetScore": t_score
        }, broadcast=True)
        
        if duel_id in duels:
            del duels[duel_id]
        broadcast_players()

def broadcast_players():
    # 全クライアントに現在のオンラインプレイヤー情報を配る
    emit('update_players', list(players.values()), broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)

```
