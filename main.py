import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from datetime import datetime, date
import os
from flask import Flask
from threading import Thread

# ==========================================
# 1. スリープ防止用のWebサーバー設定 (Render用)
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ==========================================
# 2. Discord Botの基本設定
# ==========================================
TEXT_CH_ID = 1495652835143057408
MAIN_VC_ID = 1495652876184457286
DEAD_VC_ID = 1495652903636041849

intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.voice_states = True 

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
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
@bot.tree.command(name="omikuji", description="今日のおみくじを引く（1日1回）")
async def omikuji(interaction: discord.Interaction):
    user_id = interaction.user.id
    today = date.today()

    if user_id in game.omikuji_history:
        if game.omikuji_history[user_id] == today:
            await interaction.response.send_message(f"⛩️ おみくじは1日1回までだぞ！また明日来い！", ephemeral=True)
            return

    await interaction.response.defer()
    
    # --- 確率による振り分け ---
    rand = random.random() * 100
    
    if rand <= 0.3:
        key = "隠吉"         # 0.3% (0.0 ～ 0.3)
    elif rand <= 3.3:
        key = "地の底"       # 3.0% (0.3 ～ 3.3)
    elif rand <= 10.0:
        key = "極大吉"       # 6.7% (3.3 ～ 10.0)
    elif rand <= 25.0:
        key = "超大吉"       # 15.0% (10.0 ～ 25.0)
    elif rand <= 45.0:
        key = "大吉"         # 20.0% (25.0 ～ 45.0)
    elif rand <= 65.0:
        key = "中吉"         # 20.0% (45.0 ～ 65.0)
    elif rand <= 80.0:
        key = "小吉"         # 15.0% (65.0 ～ 80.0)
    elif rand <= 90.0:
        key = "凶"           # 10.0% (80.0 ～ 90.0)
    elif rand <= 97.0:
        key = "大凶"         # 7.0% (90.0 ～ 97.0)
    else:
        key = "首の皮一枚"   # 3.0% (97.0 ～ 100.0)
    
    FORTUNES = {
        "隠吉": {"i": "㊗️", "c": 0xff00ff, "m": "今日のお前は運気が神ってるぞ！！！羨ましい..."},
        "極大吉": {"i": "🎇", "c": 0xff8c00, "m": "今日のお前、かなりイケてる運気だな！"},
        "超大吉": {"i": "🎆", "c": 0xffd700, "m": "今日のお前はまあまあ運気があるじゃないか！"},
        "大吉": {"i": "🌟", "c": 0xffd700, "m": "ヘッツ！大吉かよ！まあ運はあるんじゃないか？"},
        "中吉": {"i": "✨", "c": 0x32cd32, "m": "なんだ中吉かつまんねー"},
        "小吉": {"i": "⭐", "c": 0x32cd32, "m": "はっｗ吉ｗしょうもないね～"},
        "凶":   {"i": "❌", "c": 0x4b0082, "m": "おいおい！凶かよ！どんだけ運が悪いんだｗ"},
        "大凶": {"i": "🚫", "c": 0x000000, "m": "大凶とかｗ 今日は外に出ないほうがいいんじゃねーか？"},
        "首の皮一枚": {"i": "👻", "c": 0x696969, "m": "首の皮一枚でつながった運勢か．．．お前大丈夫か？"},
        "地の底": {"i": "💀", "c": 0x000000, "m": "地の底．．．可哀そうに．．，"}
    }
    
    data = FORTUNES[key]
    game.omikuji_history[user_id] = today

    embed = discord.Embed(title=f"⛩️ {interaction.user.display_name}さんの運勢", color=data["c"])
    embed.add_field(name=f"{data['i']} {key}", value=f"**{data['m']}**")
    embed.set_footer(text="明日もまた引かせてやるよ")
    
    await interaction.followup.send(embed=embed)

# --- 人狼コマンド ---
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