import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from datetime import datetime, date
import os
import sqlite3  # ← これが必要！
from flask import Flask
from threading import Thread


def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    # ユーザーデータテーブル（コインと日付）
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, coins INTEGER, last_omikuji TEXT)''')
    # モンスター所持テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS inventory
                 (user_id INTEGER, monster_name TEXT)''')
    conn.commit()
    conn.close()

# 2. データを読み込む
def get_user_data(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT coins, last_omikuji FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0], result[1] # (コイン数, 日付)
    return 0, None # 初めての人

# 3. データを書き込む（更新）
def update_user_data(user_id, coins, last_date):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, coins, last_omikuji) VALUES (?, ?, ?)",
              (user_id, coins, last_date))
    conn.commit()
    conn.close()

# 4. モンスターを保存する
def add_monster(user_id, monster_name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO inventory (user_id, monster_name) VALUES (?, ?)", (user_id, monster_name))
    conn.commit()
    conn.close()

# 5. 所持リストを読み込む
def get_inventory(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT monster_name FROM inventory WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# ==========================================
# 1. スリープ防止用のWebサーバー設定 (Render用)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()


# ==========================================
# 2. Discord Botの基本設定
# ==========================================
TEXT_CH_ID = 1495652835143057408
MAIN_VC_ID = 1495652876184457286
DEAD_VC_ID = 1495652903636041849

OMIKUJI_CH_ID = 1495656809560805377  # おみくじ用
GACHA_CH_ID = 1502210813577138327    # ガチャ・コレクション用

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.voice_states = True 

class MyBot(commands.Bot):
    def __init__(self):
        # ここでは基本設定だけを行う
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        init_db()
        # 🌟 特定のサーバーIDをここに指定すると、反映が爆速（一瞬）になります
        MY_GUILD = discord.Object(id=1306589891026489425) # TEXT_CH_IDがあるサーバーのID
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        
        print(f"✅ GM完全自動化システム 起動完了")

bot = MyBot()

# --- データ管理 ---
class GameState:
    def __init__(self):
        self.is_active = False
        self.players = {}
        self.alive_ids = []
        self.night_actions = {"kill": {}, "divine": None}
        self.votes = {}
        self.omikuji_history = {}  # {user_id: last_date}
        self.user_coins = {}
        self.user_monsters = {}

game = GameState()

# --- 役職配布ロジック ---
def get_roles(count):
    if count <= 6:
        base = ["人狼", "占い師", "狂人", "村人", "村人", "村人"]
    elif count == 7:
        base = ["人狼", "人狼", "占い師", "狂人", "村人", "村人", "村人"]
    else:
        base = ["人狼", "人狼", "占い師", "狩人", "狂人", "村人", "村人", "村人"]
    
    selected = random.sample(base[:count] if count <= len(base) else base + ["村人"]*(count-len(base)), count)
    return selected

# --- 便利関数 ---
async def set_vc_mute(vc_id: int, mute_status: bool):
    channel = bot.get_channel(vc_id)
    if channel:
        for m in channel.members:
            if not m.bot:
                try: await m.edit(mute=mute_status)
                except: pass

async def move_to_graveyard(user_id):
    guild = bot.get_guild(bot.get_channel(TEXT_CH_ID).guild.id)
    member = guild.get_member(user_id)
    dead_vc = bot.get_channel(DEAD_VC_ID)
    if member and dead_vc and member.voice:
        try: await member.edit(voice_channel=dead_vc, mute=False)
        except: pass

async def check_victory(channel):
    wolves = [pid for pid, role in game.players.items() if role == "人狼" and pid in game.alive_ids]
    villagers = [pid for pid in game.alive_ids if pid not in wolves]
    
    if not wolves:
        await channel.send("🎉 **【村人陣営の勝利！】** 人狼を全滅させました！")
        game.is_active = False
        await set_vc_mute(MAIN_VC_ID, False)
        return True
    if len(wolves) >= len(villagers):
        await channel.send("🐺 **【人狼陣営の勝利！】** 村は人狼に支配されました。")
        game.is_active = False
        await set_vc_mute(MAIN_VC_ID, False)
        return True
    return False

# --- UI ---
class ActionView(discord.ui.View):
    def __init__(self, targets, action_type):
        super().__init__(timeout=60)
        self.action_type = action_type
        for t in targets:
            style = discord.ButtonStyle.danger if action_type == "kill" else discord.ButtonStyle.primary
            if action_type == "vote": style = discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=t.display_name, style=style, custom_id=str(t.id))
            btn.callback = self.create_callback(t)
            self.add_item(btn)

    def create_callback(self, target):
        async def callback(interaction: discord.Interaction):
            if self.action_type == "kill":
                game.night_actions["kill"][interaction.user.id] = target.id
                await interaction.response.send_message(f"🔪 {target.display_name} を襲撃先に選びました。", ephemeral=True)
            elif self.action_type == "divine":
                role = game.players.get(target.id)
                res = "人狼" if role == "人狼" else "人間"
                await interaction.response.send_message(f"🔮 占い結果: {target.display_name} は **【{res}】** です。", ephemeral=True)
            elif self.action_type == "vote":
                game.votes[interaction.user.id] = target.id
                await interaction.response.send_message(f"✅ {target.display_name} に投票しました。", ephemeral=True)
        return callback

# --- 【修正版】日常おみくじコマンド ---
@bot.tree.command(name="omikuji", description="毒舌おみくじを引いてガチャコインを3枚ゲット！")
async def omikuji(interaction: discord.Interaction):
    # 🌟 まず最初に「考え中...」にする（これで3秒ルールを突破！）
    await interaction.response.defer()

    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)
    today = date.today().isoformat()

    # --- 1. 場所（チャンネル）のチェック ---
    if interaction.channel_id != OMIKUJI_CH_ID:
        # 🌟 deferの後なので followup.send を使う
        await interaction.followup.send(
            f"❌ ここはおみくじ会場じゃないぞ！ <#{OMIKUJI_CH_ID}> で引け！", 
            ephemeral=True
        )
        return

    # --- 2. デイリーチェック ---
    if last_date == today:
        # 🌟 deferの後なので followup.send を使う
        await interaction.followup.send(f"⛩️ おみくじは1日1回までだぞ！また明日来い！", ephemeral=True)
        return

    # --- 3. 確率による振り分け (ここからは今のコードと同じ) ---
    rand = random.random() * 100
    if rand <= 0.3: key = "隠吉"
    elif rand <= 3.3: key = "地の底"
    elif rand <= 10.0: key = "極大吉"
    elif rand <= 25.0: key = "超大吉"
    elif rand <= 45.0: key = "大吉"
    elif rand <= 65.0: key = "中吉"
    elif rand <= 80.0: key = "小吉"
    elif rand <= 90.0: key = "凶"
    elif rand <= 97.0: key = "大凶"
    else: key = "首の皮一枚"
    
    FORTUNES = {
        "隠吉": {"i": "㊗️", "c": 0xff00ff, "m": "今日のお前は運気が神ってるぞ！！！羨ましい..."},
        "地の底": {"i": "💀", "c": 0x000000, "m": "地の底．．．可哀そうに．．，"},
        "極大吉": {"i": "🎇", "c": 0xff8c00, "m": "今日のお前、かなりイケてる運気だな！"},
        "超大吉": {"i": "🎆", "c": 0xffd700, "m": "今日のお前はまあまあ運気があるじゃないか！"},
        "大吉": {"i": "🌟", "c": 0xffd700, "m": "ヘッツ！大吉かよ！まあ運はあるんじゃないか？"},
        "中吉": {"i": "✨", "c": 0x32cd32, "m": "なんだ中吉かつまんねー"},
        "小吉": {"i": "⭐", "c": 0x32cd32, "m": "はっｗ吉ｗしょうもないね～"},
        "凶": {"i": "🪦", "c": 0x4b0082, "m": "おいおい！凶かよ！どんだけ運が悪いんだｗ"},
        "大凶": {"i": "👻", "c": 0x000000, "m": "大凶とかｗ 今日は外に出ないほうがいいんじゃねーか？"},
        "首の皮一枚": {"i": "🩻", "c": 0x696969, "m": "首の皮一枚でつながった運勢か．．．お前大丈夫か？"}
    }
    
    data = FORTUNES[key]
    
    # 履歴保存 & コイン付与
    new_coins = coins + 3
    update_user_data(user_id, new_coins, today)

    # 結果の送信
    embed = discord.Embed(title=f"⛩️ {interaction.user.display_name}さんの運勢", color=data["c"])
    embed.add_field(name=f"{data['i']} {key}", value=f"**{data['m']}**", inline=False)
    embed.add_field(name="🎁 特典", value="**ガチャコインを3枚** 手に入れました！", inline=False)
    embed.set_footer(text=f"現在の所持コイン: {new_coins}枚 | 明日もまた引かせてやるよ")
    
    # 🌟 最後に followup.send で送信！
    await interaction.followup.send(embed=embed)

# --- ガチャコマンド ---
@bot.tree.command(name="gacha", description="コインを1枚使ってモンスターを召喚！")
async def gacha(interaction: discord.Interaction):
    # 🌟 最初にdefer（考え中）を入れる
    await interaction.response.defer(ephemeral=True)

    # 1. チャンネルチェック
    if interaction.channel_id != GACHA_CH_ID:
        await interaction.followup.send(
            f"❌ ここではガチャは引けないぞ！ <#{GACHA_CH_ID}> でやってくれ！", 
            ephemeral=True
        )
        return

    # 2. データベースから現在のコイン枚数を取得
    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)

    # 3. コイン枚数のチェック
    if coins < 1:
        await interaction.followup.send("🪙 コインが足りねーぞ！おみくじを引いて貯めてこい！", ephemeral=True)
        return

    # --- ガチャ処理 ---
    new_coins = coins - 1
    update_user_data(user_id, new_coins, last_date)

    # レア度決定
    rand = random.random() * 100
    if rand <= 3: rarity = "SSR"
    elif rand <= 20: rarity = "SR"
    elif rand <= 50: rarity = "R"
    else: rarity = "N"

    # データ（ここもインデントに注意！）
    MONSTER_DATA = {
        "✨ 伝説のたいが神": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/a.png",
        "👑 島さんの弟": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/d.png",
        "🔥 ゆずの皮": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/c.png",
        "⚡ みかんの皮": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/b.png",
        "🐼 パンダ顔のおっさん": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/e.png",
        "🐈 猫舌男": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/h.png",
        "💧 ニート": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/f.png",
        "🦾 ただのおっさん": "https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/g.png",
    }

    MONSTERS = {
        "SSR": ["✨ 伝説のたいが神", "👑 島さんの弟"],
        "SR": ["🔥 ゆずの皮", "⚡ みかんの皮"],
        "R": ["🐼 パンダ顔のおっさん", "🐈 猫舌男"],
        "N": ["💧 ニート", "🦾 ただのおっさん"]
    }

    monster_name = random.choice(MONSTERS[rarity])
    image_url = MONSTER_DATA.get(monster_name)
    
    # データベースに追加
    add_monster(user_id, f"[{rarity}] {monster_name}")

    # --- 結果表示 ---
    embed = discord.Embed(title="🌀 モンスター召喚！", color=0x00ff00)
    embed.add_field(name="召喚結果", value=f"**{monster_name}** ({rarity})", inline=False)
    embed.set_footer(text=f"残りコイン: {new_coins}枚")
    
    # 🌟 画像をセット！
    if image_url:
        embed.set_image(url=image_url)
    
    # 🌟 followup.send にするのを忘れずに！
    await interaction.followup.send(embed=embed)

# --- コレクション確認コマンド ---
@bot.tree.command(name="collection", description="仲間にしたモンスターを確認する")
async def collection(interaction: discord.Interaction):
    # --- 1. まず場所をチェック！ ---
    if interaction.channel_id != GACHA_CH_ID:
        await interaction.response.send_message(
            f"❌ 自分の仲間は <#{GACHA_CH_ID}> で確認してくれ！", 
            ephemeral=True
        )
        return

    # --- 2. ここからメインの処理 ---
    user_id = interaction.user.id
    
    # データベース（保存機能）を使う場合はこっち
    monsters = get_inventory(user_id)
    
    # もし一時保存（game.user_monsters）を使っているならこれ
    # monsters = game.user_monsters.get(user_id, [])
    
    if not monsters:
        await interaction.response.send_message("まだモンスターを1匹も持ってないな。寂しい奴め！", ephemeral=True)
        return
    
    # 重複を数えて表示を見やすくする
    from collections import Counter
    counts = Counter(monsters)
    msg = "\n".join([f"{m} ×{c}" for m, c in counts.items()])
    
    await interaction.response.send_message(f"👾 **{interaction.user.display_name}のコレクション**\n{msg}")

# 人狼コマンド

@bot.tree.command(name="play_werewolf", description="人狼ゲームを開始")
async def play_werewolf(interaction: discord.Interaction, discussion_sec: int = 180):
    if interaction.channel_id != TEXT_CH_ID:
        await interaction.response.send_message("進行用チャンネルで使用してください。", ephemeral=True)
        return
    
    main_vc = bot.get_channel(MAIN_VC_ID)
    members = [m for m in main_vc.members if not m.bot]
    if len(members) < 3:
        await interaction.response.send_message("3人以上集まってから開始してください。", ephemeral=True)
        return

    await interaction.response.defer()
    
    roles = get_roles(len(members))
    game.players = {m.id: r for m, r in zip(members, roles)}
    game.alive_ids = [m.id for m in members]
    game.is_active = True
    wolves_names = [m.display_name for m in members if game.players[m.id] == "人狼"]

    for m in members:
        role = game.players[m.id]
        msg = f"あなたの役職: **【{role}】**"
        if role == "人狼" and len(wolves_names) > 1:
            msg += f"\n仲間の人狼: {', '.join(wolves_names)}"
        try: await m.send(msg)
        except: pass

    await interaction.followup.send("🎮 **ゲーム開始！役職をDMしました。**")

    while game.is_active:
        await interaction.channel.send("🌙 **夜が来ました。役職者はDMを確認してください。**")
        await set_vc_mute(MAIN_VC_ID, True)
        game.night_actions = {"kill": {}, "divine": None}
        targets = [interaction.guild.get_member(pid) for pid in game.alive_ids]
        for pid in game.alive_ids:
            p = interaction.guild.get_member(pid)
            if not p: continue
            role = game.players[pid]
            if role == "人狼":
                k_targets = [t for t in targets if game.players[t.id] != "人狼"]
                await p.send("🔪 **襲撃先を選択してください：**", view=ActionView(k_targets, "kill"))
            elif role == "占い師":
                d_targets = [t for t in targets if t.id != pid]
                await p.send("🔮 **占う相手を選択してください：**", view=ActionView(d_targets, "divine"))
        await asyncio.sleep(40)
        await set_vc_mute(MAIN_VC_ID, False)
        killed_id = None
        if game.night_actions["kill"]:
            killed_id = max(set(game.night_actions["kill"].values()), key=list(game.night_actions["kill"].values()).count)
        if killed_id and killed_id in game.alive_ids:
            game.alive_ids.remove(killed_id)
            dead_u = interaction.guild.get_member(killed_id)
            await interaction.channel.send(f"☀️ **朝です。昨夜の犠牲者は {dead_u.mention} さんでした。**")
            await move_to_graveyard(killed_id)
        else:
            await interaction.channel.send("☀️ **朝です。昨夜の犠牲者はいませんでした。**")
        if await check_victory(interaction.channel): break

        await interaction.channel.send(f"📢 **議論開始！制限時間は {discussion_sec}秒 です。**")
        remaining = discussion_sec
        while remaining > 0:
            if remaining > 60:
                await asyncio.sleep(60); remaining -= 60
                await interaction.channel.send(f"⏱️ **議論終了まで残り {remaining}秒 です。**")
            elif remaining > 30:
                await asyncio.sleep(remaining - 30); remaining = 30
                await interaction.channel.send(f"⚠️ **あと30秒で議論終了です！**")
            else:
                await asyncio.sleep(remaining - 10)
                await interaction.channel.send(f"⏳ **まもなく投票です！ 10... 5... 3...**")
                await asyncio.sleep(10); remaining = 0

        await interaction.channel.send("🗳️ **投票の時間です。全員のDMにボタンを送信しました。**")
        game.votes = {}
        for pid in game.alive_ids:
            p = interaction.guild.get_member(pid)
            if p:
                v_targets = [interaction.guild.get_member(tid) for tid in game.alive_ids if tid != pid]
                try: await p.send("🗳️ **追放する人を選んでください（匿名投票）**", view=ActionView(v_targets, "vote"))
                except: pass
        await asyncio.sleep(30)
        if game.votes:
            ex_id = max(set(game.votes.values()), key=list(game.votes.values()).count)
            game.alive_ids.remove(ex_id)
            ex_u = interaction.guild.get_member(ex_id)
            await interaction.channel.send(f"🪦 投票の結果、{ex_u.mention} さんが追放されました。")
            await move_to_graveyard(ex_id)
        if await check_victory(interaction.channel): break
        await interaction.channel.send("🔄 次の夜へ...")
        await asyncio.sleep(3)

# --- 起動 ---
if __name__ == "__main__":
    keep_alive()
    token = os.getenv('DISCORD_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_TOKEN not found.")