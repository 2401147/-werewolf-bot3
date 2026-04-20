import discord
from discord import app_commands
from discord.ext import commands
import random
import asyncio
from datetime import datetime
import os
from flask import Flask
from threading import Thread

# ==========================================
# 1. スリープ防止用のWebサーバー設定
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    # Renderは8080ポートを期待することが多いです
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ==========================================
# 2. Discord Botの設定
# ==========================================
# ※IDは自分の環境のものに書き換えてください
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
        print(f"✅ GM完全自動化システム(Web対応版) 起動")

bot = MyBot()

# --- ゲーム管理 ---
class GameState:
    def __init__(self):
        self.is_active = False
        self.players = {}
        self.alive_ids = []
        self.night_actions = {"kill": {}, "divine": None}
        self.votes = {}

game = GameState()

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

# --- UI (ボタン) ---
class ActionView(discord.ui.View):
    def __init__(self, targets, action_type):
        super().__init__(timeout=60)
        self.action_type = action_type
        for t in targets:
            style = discord.ButtonStyle.danger if action_type == "kill" else discord.ButtonStyle.primary
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

# --- コマンド ---
@bot.tree.command(name="omikuji", description="あそみくじを引く")
async def omikuji(interaction: discord.Interaction):
    await interaction.response.defer()
    FORTUNES = {
        "大吉": {"i": "🌟", "c": 0xffd700, "m": "最高の一日！ハッカソンで優勝できそう！"},
        "中吉": {"i": "✨", "c": 0x32cd32, "m": "良いことありそう。コードがバグなしで動くかも。"},
        "吉":   {"i": "✅", "c": 0xe0e0e0, "m": "平穏無事。エラーメッセージを読めば解決する日。"},
        "凶":   {"i": "👻", "c": 0x4b0082, "m": "油断大敵。セミコロン忘れに注意して。"}
    }
    key = random.choice(list(FORTUNES.keys()))
    data = FORTUNES[key]
    embed = discord.Embed(title=f"⛩️ {interaction.user.display_name}さんの運勢", color=data["c"])
    embed.add_field(name=f"{data['i']} {key}", value=f"**{data['m']}**")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="play_werewolf", description="人狼ゲームをフルオートで開始")
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
    
    # 役職配布
    roles_pool = ["人狼", "占い師", "狩人", "狂人", "人狼", "村人", "村人"]
    roles = random.sample(roles_pool[:len(members)], len(members)) if len(members) <= 7 else roles_pool + ["村人"]*(len(members)-7)
    random.shuffle(roles)
    
    game.players = {m.id: r for m, r in zip(members, roles)}
    game.alive_ids = [m.id for m in members]
    game.is_active = True
    wolves = [m.display_name for m in members if game.players[m.id] == "人狼"]

    for m in members:
        role = game.players[m.id]
        msg = f"あなたの役職: **【{role}】**"
        if role == "人狼": msg += f"\n仲間の人狼: {', '.join(wolves)}"
        await m.send(msg)

    await interaction.followup.send("🎮 **ゲーム開始！**")

    while game.is_active:
        # 夜
        await interaction.channel.send("🌙 **夜が来ました。役職者はDMを確認してください。**")
        await set_vc_mute(MAIN_VC_ID, True)
        
        game.night_actions = {"kill": {}, "divine": None}
        targets = [m for m in members if m.id in game.alive_ids]
        for pid in game.alive_ids:
            p = interaction.guild.get_member(pid)
            if not p: continue
            if game.players[pid] == "人狼":
                await p.send("🔪 襲撃先を選択：", view=ActionView(targets, "kill"))
            elif game.players[pid] == "占い師":
                await p.send("🔮 占う相手を選択：", view=ActionView(targets, "divine"))
        
        await asyncio.sleep(30)

        # 朝
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

        # 議論・投票
        await interaction.channel.send(f"📢 議論（{discussion_sec}秒）")
        await asyncio.sleep(discussion_sec)

        await interaction.channel.send("🗳️ **投票の時間です。追放する人を選んでください。**")
        await set_vc_mute(MAIN_VC_ID, True)
        game.votes = {}
        view = ActionView([interaction.guild.get_member(pid) for pid in game.alive_ids], "vote")
        await interaction.channel.send("ボタンを押して投票：", view=view)
        
        await asyncio.sleep(20)
        
        if game.votes:
            ex_id = max(set(game.votes.values()), key=list(game.votes.values()).count)
            game.alive_ids.remove(ex_id)
            ex_u = interaction.guild.get_member(ex_id)
            await interaction.channel.send(f"🪦 投票の結果、{ex_u.mention} さんが追放されました。")
            await move_to_graveyard(ex_id)
        
        if await check_victory(interaction.channel): break
        await interaction.channel.send("🔄 次の夜へ...")
        await asyncio.sleep(3)

# ==========================================
# 3. 起動
# ==========================================
if __name__ == "__main__":
    keep_alive()  # Webサーバー起動
    token = os.getenv('DISCORD_TOKEN')
    if token:
        bot.run(token)
    else:
        print("❌ エラー: DISCORD_TOKEN が設定されていません。")
