import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import asyncio
from datetime import datetime, date, time, timezone, timedelta
import os
import sqlite3
from collections import Counter
from flask import Flask
from threading import Thread

# JST (日本標準時) の設定
JST = timezone(timedelta(hours=9))

# ==========================================
# 1. データベース設定 (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    # ユーザーデータテーブル（コインと最後におみくじを引いた日付）
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, coins INTEGER, last_omikuji TEXT)''')
    # モンスター所持テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS inventory
                 (user_id INTEGER, monster_name TEXT)''')
    # 煽りターゲット管理テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS aoru_target
                 (id INTEGER PRIMARY KEY, target_user_id INTEGER)''')
    # 今日のラッキーメンバーテーブル【追加】
    c.execute('''CREATE TABLE IF NOT EXISTS lucky_member
                 (id INTEGER PRIMARY KEY, user_id INTEGER, lucky_date TEXT)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT coins, last_omikuji FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0], result[1]  # (コイン数, 日付)
    return 0, None  # 新規ユーザー

def update_user_data(user_id, coins, last_date):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, coins, last_omikuji) VALUES (?, ?, ?)",
              (user_id, coins, last_date))
    conn.commit()
    conn.close()

def add_monster(user_id, monster_name):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT INTO inventory (user_id, monster_name) VALUES (?, ?)", (user_id, monster_name))
    conn.commit()
    conn.close()

def get_inventory(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT monster_name FROM inventory WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

# --- 煽り機能用DB関数 ---
def set_target_id(user_id):
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO aoru_target (id, target_user_id) VALUES (1, ?)", (user_id,))
    conn.commit()
    conn.close()

def get_target_id():
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT target_user_id FROM aoru_target WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# --- 今日のラッキーメンバー用DB処理【追加】 ---
async def get_or_update_lucky_member(guild):
    today = datetime.now(JST).date().isoformat()
    conn = sqlite3.connect('bot_data.db')
    c = conn.cursor()
    c.execute("SELECT user_id, lucky_date FROM lucky_member WHERE id = 1")
    row = c.fetchone()

    # すでに本日のラッキーメンバーが決まっている場合
    if row and row[1] == today:
        conn.close()
        return row[0]

    # 日付が変わっていたら新しく抽選（Bot以外のメンバーから選択）
    members = [m for m in guild.members if not m.bot]
    if not members:
        conn.close()
        return None

    selected_member = random.choice(members)
    c.execute("INSERT OR REPLACE INTO lucky_member (id, user_id, lucky_date) VALUES (1, ?, ?)",
              (selected_member.id, today))
    conn.commit()
    conn.close()
    return selected_member.id

# ==========================================
# 2. スリープ防止用 Web サーバー (Render用)
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
# 3. Discord Bot 基本設定
# ==========================================
OMIKUJI_CH_ID = 1495656809560805377  # おみくじ用チャンネルID
GACHA_CH_ID = 1502210813577138327    # ガチャ・コレクション用チャンネルID
TARGET_GUILD_ID = 1306589891026489425 # コマンドを即時反映させるサーバーID

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        init_db()
        MY_GUILD = discord.Object(id=TARGET_GUILD_ID)
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        print(f"✅ おみくじ＆ガチャ＆煽り＆ラッキーメンバーBot 起動完了")

bot = MyBot()

# ==========================================
# 4. スラッシュコマンド
# ==========================================

# --- 毒舌おみくじコマンド ---
@bot.tree.command(name="omikuji", description="毒舌おみくじを引いてガチャコインをゲット！")
async def omikuji(interaction: discord.Interaction):
    await interaction.response.defer()

    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)
    today = date.today().isoformat()

    if interaction.channel_id != OMIKUJI_CH_ID:
        await interaction.followup.send(
            f"❌ ここはおみくじ会場じゃないぞ！ <#{OMIKUJI_CH_ID}> で引け！", 
            ephemeral=True
        )
        return

    if last_date == today:
        await interaction.followup.send(f"⛩️ おみくじは1日1回までだぞ！また明日来い！", ephemeral=True)
        return

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
        "中吉": {"i": "✨", "c": 0x32cd32, "m": "なんだ中吉かつつまんねー"},
        "小吉": {"i": "⭐", "c": 0x32cd32, "m": "はっｗ吉ｗしょうもないね～"},
        "凶": {"i": "🪦", "c": 0x4b0082, "m": "おいおい！凶かよ！どんだけ運が悪いんだｗ"},
        "大凶": {"i": "👻", "c": 0x000000, "m": "大凶とかｗ 今日は外に出ないほうがいいんじゃねーか？"},
        "首の皮一枚": {"i": "🩻", "c": 0x696969, "m": "首の皮一枚でつながった運勢か．．．お前大丈夫か？"}
    }
    
    data = FORTUNES[key]
    
    new_coins = coins + 3
    update_user_data(user_id, new_coins, today)

    embed = discord.Embed(title=f"⛩️ {interaction.user.display_name}さんの運勢", color=data["c"])
    embed.add_field(name=f"{data['i']} {key}", value=f"**{data['m']}**", inline=False)
    embed.add_field(name="🎁 特典", value="**ガチャコインを3枚** 手に入れました！", inline=False)
    embed.set_footer(text=f"現在の所持コイン: {new_coins}枚 | 明日もまた引かせてやるよ")
    
    await interaction.followup.send(embed=embed)

# --- ガチャコマンド ---
@bot.tree.command(name="gacha", description="コインを1枚使ってモンスターを召喚！")
async def gacha(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if interaction.channel_id != GACHA_CH_ID:
        await interaction.followup.send(
            f"❌ ここではガチャは引けないぞ！ <#{GACHA_CH_ID}> でやってくれ！", 
            ephemeral=True
        )
        return

    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)

    if coins < 1:
        await interaction.followup.send("🪙 コインが足りねーぞ！おみくじを引いて貯めてこい！", ephemeral=True)
        return

    new_coins = coins - 1
    update_user_data(user_id, new_coins, last_date)

    rand = random.random() * 100
    if rand <= 3: rarity = "SSR"
    elif rand <= 20: rarity = "SR"
    elif rand <= 50: rarity = "R"
    else: rarity = "N"

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
    
    add_monster(user_id, f"[{rarity}] {monster_name}")

    embed = discord.Embed(title="🌀 モンスター召喚！", color=0x00ff00)
    embed.add_field(name="召喚結果", value=f"**{monster_name}** ({rarity})", inline=False)
    embed.set_footer(text=f"残りコイン: {new_coins}枚")
    
    if image_url:
        embed.set_image(url=image_url)
    
    await interaction.followup.send(embed=embed)

# --- コレクション確認コマンド ---
@bot.tree.command(name="collection", description="仲間にしたモンスターを確認する")
async def collection(interaction: discord.Interaction):
    if interaction.channel_id != GACHA_CH_ID:
        await interaction.response.send_message(
            f"❌ 自分の仲間は <#{GACHA_CH_ID}> で確認してくれ！", 
            ephemeral=True
        )
        return

    user_id = interaction.user.id
    monsters = get_inventory(user_id)
    
    if not monsters:
        await interaction.response.send_message("まだモンスターを1匹も持ってないな。寂しい奴め！", ephemeral=True)
        return
    
    counts = Counter(monsters)
    msg = "\n".join([f"{m} ×{c}" for m, c in counts.items()])
    
    await interaction.response.send_message(f"👾 **{interaction.user.display_name}のコレクション**\n{msg}")

# --- ターゲット設定コマンド (管理者限定) ---
@bot.tree.command(name="set_target", description="【運営専用】煽りターゲットを設定する")
@app_commands.checks.has_permissions(administrator=True)
async def set_target(interaction: discord.Interaction, target: discord.User):
    set_target_id(target.id)
    await interaction.response.send_message(
        f"🎯 煽りターゲットを <@{target.id}> に設定したぞ！", 
        ephemeral=True
    )

# --- 煽り実行コマンド ---
AORU_MESSAGES = [
    "おい <@{user_id}>、今日もお前は息してるだけか？ｗｗ",
    "ちょっと <@{user_id}> さん、またくだらないこと言ってますね～ｗ",
    "<@{user_id}> が何か言いたそうにこちらを見ている！…が、誰も気にしていない！",
    "なぁ <@{user_id}>、一回冷静になろうか？ｗｗ",
    "【悲報】<@{user_id}>、今日も平常運転で滑る",
    "おっと～？ <@{user_id}> 選手のありがたいお言葉だ～（棒読み）"
]

@bot.tree.command(name="aoru", description="設定されたターゲットをみんなで煽る！")
async def aoru(interaction: discord.Interaction):
    target_id = get_target_id()
    
    if not target_id:
        await interaction.response.send_message("まだターゲットが設定されてねーぞ！運営に `/set_target` させろ！", ephemeral=True)
        return

    msg_template = random.choice(AORU_MESSAGES)
    msg = msg_template.format(user_id=target_id)
    
    await interaction.response.send_message(msg)

# --- 【追加】今日のラッキーメンバー確認コマンド ---
LUCKY_COMMENTS = [
    "✨ 今日のラッキーメンバーは <@{user_id}> だ！…まあ、気休め程度になｗ",
    "🍀 今日の幸運の持ち主は <@{user_id}>！ 何か良いことあるかもな（適当）",
    "🎉 本日のMVP（ラッキー）は <@{user_id}>！ ジュース奢ってもらえよ！",
    "👑 本日のラッキーメンバーは <@{user_id}> だ！ 調子に乗るなよｗ"
]

@bot.tree.command(name="lucky", description="今日のラッキーメンバーを確認する！")
async def lucky(interaction: discord.Interaction):
    lucky_id = await get_or_update_lucky_member(interaction.guild)
    
    if not lucky_id:
        await interaction.response.send_message("メンバーが見つからなかったぞ！", ephemeral=True)
        return

    comment = random.choice(LUCKY_COMMENTS).format(user_id=lucky_id)
    
    embed = discord.Embed(title="🌟 今日のラッキーメンバー", color=0xffd700)
    embed.description = comment
    await interaction.response.send_message(embed=embed)

# ==========================================
# 5. 自動反応イベント
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    target_id = get_target_id()
    
    # ターゲット本人が発言した時、15%の確率で自動で煽りレスをする
    if target_id and message.author.id == target_id:
        if random.random() < 0.15:
            reply_msg = random.choice([
                "うおw",
                "お前はもう死んでいる！",
                "おいおい、急に喋るなよｗｗ",
                "はいはい、ワロスワロスｗｗ",
                "相変わらず香ばしい発言ですね～ｗ",
                "またお前か！！"
            ])
            await message.channel.send(reply_msg, reference=message)

    await bot.process_commands(message)

# ==========================================
# 6. Bot 起動処理
# ==========================================
if __name__ == "__main__":
    keep_alive()
    token = os.getenv('DISCORD_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ ERROR: DISCORD_TOKEN not found.")