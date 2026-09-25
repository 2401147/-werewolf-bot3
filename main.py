from collections import Counter
from datetime import date, datetime, timedelta, timezone
from flask import Flask
import os, random, sqlite3, time
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands

JST = timezone(timedelta(hours=9))
DB_NAME = 'bot_data.db'

# ==========================================
# 1. データベース処理 (SQLite)
# ==========================================
def db_exec(query, params=(), fetchone=False, fetchall=False, commit=False):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute(query, params)
        if commit: conn.commit()
        if fetchone: return c.fetchone()
        if fetchall: return c.fetchall()

def init_db():
    queries = [
        '''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, coins INTEGER, last_omikuji TEXT)''',
        '''CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, monster_name TEXT)''',
        '''CREATE TABLE IF NOT EXISTS aoru_target (id INTEGER PRIMARY KEY, target_user_id INTEGER)''',
        '''CREATE TABLE IF NOT EXISTS lucky_member (id INTEGER PRIMARY KEY, user_id INTEGER, lucky_date TEXT)'''
    ]
    for q in queries:
        db_exec(q, commit=True)

def get_user_data(user_id):
    res = db_exec('SELECT coins, last_omikuji FROM users WHERE user_id = ?', (user_id,), fetchone=True)
    return res if res else (0, None)

def update_user_data(user_id, coins, last_date):
    db_exec('INSERT OR REPLACE INTO users (user_id, coins, last_omikuji) VALUES (?, ?, ?)', (user_id, coins, last_date), commit=True)

def add_monster(user_id, monster_name):
    db_exec('INSERT INTO inventory (user_id, monster_name) VALUES (?, ?)', (user_id, monster_name), commit=True)

def get_inventory(user_id):
    rows = db_exec('SELECT monster_name FROM inventory WHERE user_id = ?', (user_id,), fetchall=True)
    return [row[0] for row in rows]

def set_target_id(user_id):
    db_exec('INSERT OR REPLACE INTO aoru_target (id, target_user_id) VALUES (1, ?)', (user_id,), commit=True)

def get_target_id():
    res = db_exec('SELECT target_user_id FROM aoru_target WHERE id = 1', fetchone=True)
    return res[0] if res else None

async def get_or_update_lucky_member(guild):
    today = datetime.now(JST).date().isoformat()
    row = db_exec('SELECT user_id, lucky_date FROM lucky_member WHERE id = 1', fetchone=True)
    if row and row[1] == today:
        return row[0]
    
    members = [m for m in guild.members if not m.bot]
    if not members:
        return None
    
    selected = random.choice(members)
    db_exec('INSERT OR REPLACE INTO lucky_member (id, user_id, lucky_date) VALUES (1, ?, ?)', (selected.id, today), commit=True)
    return selected.id

# ==========================================
# 2. スリープ防止 Web サーバー (Flask)
# ==========================================
app = Flask('')
@app.route('/')
def home(): return 'Bot is running!'

def keep_alive():
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))).start()

# ==========================================
# 3. Discord Bot 設定 & データ定数
# ==========================================
OMIKUJI_CH_ID = 1495656809560805377
GACHA_CH_ID = 1502210813577138327
TARGET_GUILD_ID = 1306589891026489425

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
    async def setup_hook(self):
        init_db()
        print('✅ Bot 起動準備完了')

bot = MyBot()

FORTUNES = [
    (0.3,  '隠吉',     '㊗️', 0xFF00FF, '今日のお前は運気が神ってるぞ！！！羨ましい...'),
    (3.3,  '地の底',   '💀', 0x000000, '地の底．．．可哀そうに．．，'),
    (10.0, '極大吉',   '🎇', 0xFF8C00, '今日のお前、かなりイケてる運気だな！'),
    (25.0, '超大吉',   '🎆', 0xFFD700, '今日のお前はまあまあ運気があるじゃないか！'),
    (45.0, '大吉',     '🌟', 0xFFD700, 'ヘッツ！大吉かよ！まあ運はあるんじゃないか？'),
    (65.0, '中吉',     '✨', 0x32CD32, 'なんだ中吉かつつまんねー'),
    (80.0, '小吉',     '⭐', 0x32CD32, 'はっｗ吉ｗしょうもないね～'),
    (90.0, '凶',       '🪦', 0x4B0082, 'おいおい！凶かよ！どんだけ運が悪いんだｗ'),
    (97.0, '大凶',     '👻', 0x000000, '大凶とかｗ 今日は外に出ないほうがいいんじゃねーか？'),
    (100.0,'首の皮一枚','🩻', 0x696969, '首の皮一枚でつながった運勢か．．．お前大丈夫か？')
]

MONSTERS = {
    'SSR': [('✨ 伝説のたいが神', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/a.png'),
            ('👑 島さんの弟', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/d.png')],
    'SR':  [('🔥 ゆずの皮', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/c.png'),
            ('⚡ みかんの皮', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/b.png')],
    'R':   [('🐼 パンダ顔のおっさん', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/e.png'),
            ('🐈 猫舌男', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/h.png')],
    'N':   [('💧 ニート', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/f.png'),
            ('🦾 ただのおっさん', 'https://raw.githubusercontent.com/2401147/-werewolf-bot3/main/g.png')]
}

AORU_MESSAGES = [
    'おい <@{user_id}>、今日もお前は息してるだけか？ｗｗ',
    'ちょっと <@{user_id}> さん、またくだらないこと言ってますね～ｗ',
    '<@{user_id}> が何か言いたそうにこちらを見ている！…が、誰も気にしていない！',
    'なぁ <@{user_id}>、一回冷静になろうか？ｗｗ',
    '【悲報】<@{user_id}>、今日も平常運転で滑る',
    'おっと～？ <@{user_id}> 選手のありがたいお言葉だ～（棒読み）'
]

LUCKY_COMMENTS = [
    '✨ 今日のラッキーメンバーは <@{user_id}> だ！…まあ、気休め程度になｗ',
    '🍀 今日の幸運の持ち主は <@{user_id}>！ 何か良いことあるかもな（適当）',
    '🎉 本日のMVP（ラッキー）は <@{user_id}>！ ジュース奢ってもらえよ！',
    '👑 本日のラッキーメンバーは <@{user_id}> だ！ 調子に乗るなよｗ'
]

# ==========================================
# 4. スラッシュコマンド処理
# ==========================================
@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync(ctx):
    guild = discord.Object(id=TARGET_GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    await ctx.send(f'✅ {len(synced)} 個のスラッシュコマンドを同期しました！')

@bot.tree.command(name='omikuji', description='毒舌おみくじを引いてガチャコインをゲット！')
async def omikuji(interaction: discord.Interaction):
    await interaction.response.defer()
    if interaction.channel_id != OMIKUJI_CH_ID:
        return await interaction.followup.send(f'❌ ここはおみくじ会場じゃないぞ！ <#{OMIKUJI_CH_ID}> で引け！', ephemeral=True)

    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)
    today = date.today().isoformat()

    if last_date == today:
        return await interaction.followup.send('⛩️ おみくじは1日1回までだぞ！また明日来い！', ephemeral=True)

    rand = random.random() * 100
    key, icon, color, msg = next((k, i, c, m) for threshold, k, i, c, m in FORTUNES if rand <= threshold)

    new_coins = coins + 3
    update_user_data(user_id, new_coins, today)

    embed = discord.Embed(title=f'⛩️ {interaction.user.display_name}さんの運勢', color=color)
    embed.add_field(name=f"{icon} {key}", value=f"**{msg}**", inline=False)
    embed.add_field(name='🎁 特典', value='**ガチャコインを3枚** 手に入れました！', inline=False)
    embed.set_footer(text=f'現在の所持コイン: {new_coins}枚 | 明日もまた引かせてやるよ')
    await interaction.followup.send(embed=embed)

@bot.tree.command(name='gacha', description='コインを1枚使ってモンスターを召喚！')
async def gacha(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if interaction.channel_id != GACHA_CH_ID:
        return await interaction.followup.send(f'❌ ここではガチャは引けないぞ！ <#{GACHA_CH_ID}> でやってくれ！', ephemeral=True)

    user_id = interaction.user.id
    coins, last_date = get_user_data(user_id)

    if coins < 1:
        return await interaction.followup.send('🪙 コインが足りねーぞ！おみくじを引いて貯めてこい！', ephemeral=True)

    new_coins = coins - 1
    update_user_data(user_id, new_coins, last_date)

    rand = random.random() * 100
    rarity = 'SSR' if rand <= 3 else 'SR' if rand <= 20 else 'R' if rand <= 50 else 'N'
    monster_name, image_url = random.choice(MONSTERS[rarity])

    add_monster(user_id, f'[{rarity}] {monster_name}')

    embed = discord.Embed(title='🌀 モンスター召喚！', color=0x00FF00)
    embed.add_field(name='召喚結果', value=f'**{monster_name}** ({rarity})', inline=False)
    embed.set_footer(text=f'残りコイン: {new_coins}枚')
    if image_url: embed.set_image(url=image_url)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name='collection', description='仲間にしたモンスターを確認する')
async def collection(interaction: discord.Interaction):
    if interaction.channel_id != GACHA_CH_ID:
        return await interaction.response.send_message(f'❌ 自分の仲間は <#{GACHA_CH_ID}> で確認してくれ！', ephemeral=True)

    monsters = get_inventory(interaction.user.id)
    if not monsters:
        return await interaction.response.send_message('まだモンスターを1匹も持ってないな。寂しい奴め！', ephemeral=True)

    counts = Counter(monsters)
    msg = '\n'.join([f'{m} ×{c}' for m, c in counts.items()])
    await interaction.response.send_message(f'👾 **{interaction.user.display_name}のコレクション**\n{msg}')

@bot.tree.command(name='set_target', description='【運営専用】煽りターゲットを設定する')
@app_commands.checks.has_permissions(administrator=True)
async def set_target(interaction: discord.Interaction, target: discord.User):
    set_target_id(target.id)
    await interaction.response.send_message(f'🎯 煽りターゲットを <@{target.id}> に設定したぞ！', ephemeral=True)

@bot.tree.command(name='aoru', description='設定されたターゲットをみんなで煽る！')
async def aoru(interaction: discord.Interaction):
    target_id = get_target_id()
    if not target_id:
        return await interaction.response.send_message('まだターゲットが設定されてねーぞ！運営に `/set_target` させろ！', ephemeral=True)
    await interaction.response.send_message(random.choice(AORU_MESSAGES).format(user_id=target_id))

@bot.tree.command(name='lucky', description='今日のラッキーメンバーを確認する！')
async def lucky(interaction: discord.Interaction):
    lucky_id = await get_or_update_lucky_member(interaction.guild)
    if not lucky_id:
        return await interaction.response.send_message('メンバーが見つからなかったぞ！', ephemeral=True)

    embed = discord.Embed(title='🌟 今日のラッキーメンバー', color=0xFFD700)
    embed.description = random.choice(LUCKY_COMMENTS).format(user_id=lucky_id)
    await interaction.response.send_message(embed=embed)

# ==========================================
# 5. 自動反応イベント
# ==========================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return

    target_id = get_target_id()
    if target_id and message.author.id == target_id and random.random() < 0.003:
        reply_msg = random.choice(['うおw', 'お前はもう死んでいる！', 'おいおい、急に喋るなよｗｗ', 'はいはい、ワロスワロスｗｗ', '相変わらず香ばしい発言ですね～ｗ', 'またお前か！！'])
        await message.channel.send(reply_msg, reference=message)

    await bot.process_commands(message)

# ==========================================
# 6. Bot 起動処理（レート制限・エラー対策追加）
# ==========================================
if __name__ == '__main__':
    keep_alive()
    token = os.getenv('DISCORD_TOKEN')
    if token:
        while True:
            try:
                bot.run(token)
            except discord.errors.HTTPException as e:
                if e.status in (429, 1015):
                    print("⚠️ レート制限を検出。60秒待機後に再接続します...")
                    time.sleep(60)
                else:
                    print(f"❌ HTTP Error: {e}")
                    time.sleep(10)
            except Exception as e:
                print(f"❌ 予期せぬエラー: {e}")
                time.sleep(10)
    else:
        print('❌ ERROR: DISCORD_TOKEN not found.')