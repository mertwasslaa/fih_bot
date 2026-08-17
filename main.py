import os
import json
import asyncio
import random
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ==================== KULLANICI AYARLARI ====================
BOT_TOKEN = "BURAYA_BOT_TOKENINI_YAZ"
CONFIG_FILE = "config.json"
BALANCES_FILE = "balances.json"

GUILD_ID_ENV = os.getenv("GUILD_ID") 
# Kendi Discord ID'ni buraya yaz (Tırnak içinde):
OWNER_ID = "1468988203376578728"

STARTING_BALANCE = 10000  # Yeni kullanıcılar 10.000 coin ile başlar
# ============================================================

app = Flask('')

@app.route('/')
def home():
    return "FihBot 24/7 Active!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web, daemon=True).start()

# Config Okuma / Yazma
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"text_channel_id": None, "voice_channel_id": None}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)

config_data = load_config()

# Bakiye & Cooldown Okuma / Yazma
def load_balances():
    if os.path.exists(BALANCES_FILE):
        with open(BALANCES_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "daily_cooldowns": {}}

def save_balances(data):
    with open(BALANCES_FILE, "w") as f:
        json.dump(data, f, indent=4)

balance_store = load_balances()
if "users" not in balance_store:
    balance_store = {"users": balance_store, "daily_cooldowns": {}}

def get_balance(user_id: int) -> int:
    uid = str(user_id)
    if uid not in balance_store["users"]:
        balance_store["users"][uid] = STARTING_BALANCE
        save_balances(balance_store)
    return balance_store["users"][uid]

def update_balance(user_id: int, amount: int):
    uid = str(user_id)
    current = get_balance(user_id)
    balance_store["users"][uid] = max(0, current + amount)
    save_balances(balance_store)

# Spotify İstemcisi
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIPY_CLIENT_ID", "5ef970630e104111a43a05187766b57d"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET", "643e2f5b404d495dbbf77a0ef7394d13")
))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

queues = {}
loop_state = {}
volumes = {}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractflat': False,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'scsearch',
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'cachedir': False,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

def get_spotify_tracks(url):
    queries = []
    try:
        if "track" in url:
            track = sp.track(url)
            queries.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif "playlist" in url:
            results = sp.playlist_tracks(url)
            tracks = results['items']
            while results['next']:
                results = sp.next(results)
                tracks.extend(results['items'])
            for item in tracks:
                track = item.get('track')
                if track:
                    queries.append(f"{track['artists'][0]['name']} - {track['name']}")
    except Exception as e:
        print(f"Spotify error: {e}")
    return queries

def play_next(interaction_or_ctx, current_song=None):
    guild_id = interaction_or_ctx.guild.id
    voice_client = interaction_or_ctx.guild.voice_client

    if not voice_client:
        return

    if loop_state.get(guild_id, False) and current_song:
        next_song = current_song
    elif guild_id in queues and len(queues[guild_id]) > 0:
        next_song = queues[guild_id].pop(0)
    else:
        if guild_id in queues:
            del queues[guild_id]
        return

    vol = volumes.get(guild_id, 0.5)
    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(next_song['url'], **FFMPEG_OPTIONS),
        volume=vol
    )
    
    voice_client.play(
        source, 
        after=lambda e: (print(f"Playback error: {e}") if e else None, play_next(interaction_or_ctx, next_song))
    )
    
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**{next_song['title']}**",
        color=discord.Color.green()
    )
    if next_song.get('thumbnail'):
        embed.set_thumbnail(url=next_song['thumbnail'])
    embed.add_field(name="Requested By", value=next_song['requested_by'], inline=True)
    embed.add_field(name="Loop Status", value="🔂 Enabled" if loop_state.get(guild_id) else "❌ Disabled", inline=True)
    embed.set_footer(text="good taste of music 🔥")

    asyncio.run_coroutine_threadsafe(interaction_or_ctx.channel.send(embed=embed), bot.loop)

@bot.event
async def on_ready():
    print(f"Bot logged in as: {bot.user.name}")
    try:
        if GUILD_ID_ENV:
            guild = discord.Object(id=int(GUILD_ID_ENV))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} slash commands directly to GUILD ID: {GUILD_ID_ENV}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash commands globally.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    voice_id = config_data.get("voice_channel_id")
    if voice_id:
        try:
            channel = bot.get_channel(int(voice_id))
            if channel and isinstance(channel, discord.VoiceChannel):
                await channel.connect()
                print(f"Auto-connected to voice channel: {channel.name}")
        except Exception as e:
            print(f"Voice connection error: {e}")

# ==================== MÜZİK SLASH KOMUTLARI ====================

@bot.tree.command(name="play", description="Play a song or playlist from SoundCloud/Spotify")
@app_commands.describe(query="Song name or link")
async def play(interaction: discord.Interaction, query: str):
    text_id = config_data.get("text_channel_id")
    if text_id and interaction.channel_id != int(text_id):
        return await interaction.response.send_message("❌ You can't use music commands in this channel!", ephemeral=True)

    await interaction.response.defer()
    guild_id = interaction.guild.id
    target_voice = interaction.guild.voice_client

    if not target_voice:
        if interaction.user.voice:
            target_voice = await interaction.user.voice.channel.connect()
        elif config_data.get("voice_channel_id"):
            channel = bot.get_channel(int(config_data["voice_channel_id"]))
            if channel:
                target_voice = await channel.connect()

    if not target_voice:
        return await interaction.followup.send("❌ Join a voice channel first or set a default voice channel via `/config`!")

    try:
        search_queries = []
        if "spotify.com" in query:
            search_queries = get_spotify_tracks(query)
            if not search_queries:
                return await interaction.followup.send("❌ Couldn't parse Spotify link.")
        else:
            search_queries.append(query)

        if guild_id not in queues:
            queues[guild_id] = []

        loop = asyncio.get_event_loop()

        for q in search_queries:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(q, download=False))
            if 'entries' in data and len(data['entries']) > 0:
                data = data['entries'][0]

            song_url = data.get('url')
            title = data.get('title', 'Unknown Track')
            thumbnail = data.get('thumbnail')

            if song_url:
                queues[guild_id].append({
                    'title': title,
                    'url': song_url,
                    'requested_by': interaction.user.mention,
                    'thumbnail': thumbnail
                })

        if len(search_queries) > 1:
            await interaction.followup.send(f"📚 Added **{len(search_queries)}** tracks to queue!")
        elif target_voice.is_playing() or target_voice.is_paused():
            last_added = queues[guild_id][-1]
            await interaction.followup.send(f"📋 Added to queue (#{len(queues[guild_id])}): **{last_added['title']}**")

        if not target_voice.is_playing() and not target_voice.is_paused():
            await interaction.followup.send("▶️ Processing track...")
            play_next(interaction)

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send(f"❌ Failed to play: `{e}`")

@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = interaction.guild.voice_client
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        loop_state[guild_id] = False
        voice_client.stop()
        await interaction.response.send_message("next one then ⏭️")
    else:
        await interaction.response.send_message("❌ Nothing is playing to skip bro.", ephemeral=True)

@bot.tree.command(name="pause", description="Pause the music")
async def pause(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        await interaction.response.send_message("⏸️ Paused.")
    else:
        await interaction.response.send_message("❌ Nothing is playing to pause.", ephemeral=True)

@bot.tree.command(name="resume", description="Resume paused music")
async def resume(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_paused():
        voice_client.resume()
        await interaction.response.send_message("▶️ Resumed.")
    else:
        await interaction.response.send_message("❌ Music is not paused.", ephemeral=True)

@bot.tree.command(name="loop", description="Toggle loop mode for current song")
async def loop_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    loop_state[guild_id] = not loop_state.get(guild_id, False)
    status = "🔂 Loop ENABLED!" if loop_state[guild_id] else "➡️ Loop DISABLED!"
    await interaction.response.send_message(status)

@bot.tree.command(name="shuffle", description="Shuffle the current queue")
async def shuffle(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in queues and len(queues[guild_id]) > 0:
        random.shuffle(queues[guild_id])
        await interaction.response.send_message("🔀 Queue shuffled!")
    else:
        await interaction.response.send_message("❌ Queue is empty to shuffle.", ephemeral=True)

@bot.tree.command(name="volume", description="Set volume (0-100)")
@app_commands.describe(level="Volume level percentage")
async def volume(interaction: discord.Interaction, level: int):
    if 0 <= level <= 100:
        guild_id = interaction.guild.id
        vol_float = level / 100.0
        volumes[guild_id] = vol_float
        if interaction.guild.voice_client and interaction.guild.voice_client.source:
            interaction.guild.voice_client.source.volume = vol_float
        await interaction.response.send_message(f"🔊 Volume set to **%{level}**")
    else:
        await interaction.response.send_message("❌ Enter a value between 0 and 100!", ephemeral=True)

@bot.tree.command(name="queue", description="Show upcoming songs")
async def queue_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in queues and len(queues[guild_id]) > 0:
        embed = discord.Embed(title="📜 Current Queue", color=discord.Color.blue())
        desc = "\n".join([f"**{i+1}.** {s['title']} | {s['requested_by']}" for i, s in enumerate(queues[guild_id][:10])])
        if len(queues[guild_id]) > 10:
            desc += f"\n\n*...and {len(queues[guild_id]) - 10} more tracks.*"
        embed.description = desc
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message("📜 Queue is empty right now.", ephemeral=True)

@bot.tree.command(name="stop", description="Stop music and clear queue")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in queues:
        queues[guild_id].clear()
    loop_state[guild_id] = False
    if interaction.guild.voice_client and (interaction.guild.voice_client.is_playing() or interaction.guild.voice_client.is_paused()):
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("k? 🤨")
    else:
        await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)
        # ==================== EKONOMİ & OYUN KOMUTLARI ====================

@bot.tree.command(name="balance", description="Check your or another user's coin balance")
@app_commands.describe(user="Target user (Optional)")
async def balance_cmd(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    bal = get_balance(target.id)
    embed = discord.Embed(
        title="💰 Wallet Status",
        description=f"{target.mention} has **{bal:,}** coins.",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="daily", description="Claim your daily free coins (Every 24h)")
async def daily_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    now = datetime.now()
    last_claim_str = balance_store.get("daily_cooldowns", {}).get(uid)

    if last_claim_str:
        last_claim = datetime.fromisoformat(last_claim_str)
        if now - last_claim < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last_claim)
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return await interaction.response.send_message(f"⏳ You already claimed today! Come back in **{hours}h {minutes}m**.", ephemeral=True)

    reward = random.randint(2000, 5000)
    update_balance(interaction.user.id, reward)

    if "daily_cooldowns" not in balance_store:
        balance_store["daily_cooldowns"] = {}
    balance_store["daily_cooldowns"][uid] = now.isoformat()
    save_balances(balance_store)

    embed = discord.Embed(
        title="🎁 Daily Reward Claimed!",
        description=f"You received **+{reward:,}** coins!\nNew Balance: **{get_balance(interaction.user.id):,}**",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="coinflip", description="Flip a coin and bet your coins (Win 2x!)")
@app_commands.describe(choice="Choose Heads or Tails", bet="Amount of coins to bet")
@app_commands.choices(choice=[
    app_commands.Choice(name="Yazı (Heads)", value="heads"),
    app_commands.Choice(name="Tura (Tails)", value="tails")
])
async def coinflip_cmd(interaction: discord.Interaction, choice: str, bet: int):
    if bet <= 0:
        return await interaction.response.send_message("❌ Bet amount must be greater than 0!", ephemeral=True)

    user_bal = get_balance(interaction.user.id)
    if bet > user_bal:
        return await interaction.response.send_message(f"❌ You don't have enough coins! Balance: **{user_bal:,}**", ephemeral=True)

    outcome = random.choice(["heads", "tails"])
    choice_str = "Yazı 🪙" if choice == "heads" else "Tura 🪙"
    outcome_str = "Yazı 🪙" if outcome == "heads" else "Tura 🪙"

    if choice == outcome:
        win_amount = bet * 2
        update_balance(interaction.user.id, win_amount)
        new_bal = get_balance(interaction.user.id)
        embed = discord.Embed(
            title="🎉 You Won (2X)! ",
            description=f"Coin landed on **{choice_str}**!\nYou won **+{win_amount:,}** coins.\nNew Balance: **{new_bal:,}**",
            color=discord.Color.green()
        )
    else:
        update_balance(interaction.user.id, -bet)
        new_bal = get_balance(interaction.user.id)
        embed = discord.Embed(
            title="💥 You Lost!",
            description=f"Coin landed on **{outcome_str}**.\nYou lost **-{bet:,}** coins.\nNew Balance: **{new_bal:,}**",
            color=discord.Color.red()
        )

    await interaction.response.send_message(embed=embed)

# --- BLACKJACK SİSTEMİ (BUTONLU & EMOJİLİ) ---
SUITS = ['♠️', '♥️', '♦️', '♣️']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

def draw_card():
    rank = random.choice(RANKS)
    suit = random.choice(SUITS)
    val = 10 if rank in ['J', 'Q', 'K'] else (11 if rank == 'A' else int(rank))
    return {'rank': rank, 'suit': suit, 'val': val, 'str': f"`{rank}{suit}`"}

def calculate_hand(hand):
    val = sum(c['val'] for c in hand)
    aces = sum(1 for c in hand if c['rank'] == 'A')
    while val > 21 and aces > 0:
        val -= 10
        aces -= 1
    return val

class BlackjackView(discord.ui.View):
    def __init__(self, user_id, bet, player_hand, dealer_hand):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.bet = bet
        self.player_hand = player_hand
        self.dealer_hand = dealer_hand

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Kart Çek (Hit) 🃏", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.player_hand.append(draw_card())
        p_val = calculate_hand(self.player_hand)

        if p_val > 21:
            update_balance(self.user_id, -self.bet)
            self.stop_buttons()
            embed = discord.Embed(title="💥 BUST! (21'i Geçtin)", color=discord.Color.red())
            embed.add_field(name="Kartların", value=" ".join(c['str'] for c in self.player_hand) + f" (Toplam: {p_val})")
            embed.add_field(name="Kurpiyer", value=" ".join(c['str'] for c in self.dealer_hand))
            embed.add_field(name="Sonuç", value=f"**-{self.bet:,}** coin kaybettin.\nYeni Bakiye: **{get_balance(self.user_id):,}**", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
            embed.add_field(name="Kartların", value=" ".join(c['str'] for c in self.player_hand) + f" (Toplam: {p_val})")
            embed.add_field(name="Kurpiyerin Açık Kartı", value=self.dealer_hand[0]['str'])
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Kal (Stand) ✋", style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        p_val = calculate_hand(self.player_hand)
        d_val = calculate_hand(self.dealer_hand)

        while d_val < 17:
            self.dealer_hand.append(draw_card())
            d_val = calculate_hand(self.dealer_hand)

        self.stop_buttons()

        if d_val > 21 or p_val > d_val:
            win_amt = self.bet * 2
            update_balance(self.user_id, win_amt)
            status = f"🎉 **Kazandın!** (+{win_amt:,} coin)"
            color = discord.Color.green()
        elif p_val < d_val:
            update_balance(self.user_id, -self.bet)
            status = f"💥 **Kaybettin!** (-{self.bet:,} coin)"
            color = discord.Color.red()
        else:
            status = "🤝 **Berabere!** Bahsin iade edildi."
            color = discord.Color.gold()

        embed = discord.Embed(title="🃏 Blackjack Sonucu", color=color)
        embed.add_field(name="Kartların", value=" ".join(c['str'] for c in self.player_hand) + f" (Toplam: {p_val})")
        embed.add_field(name="Kurpiyerin Kartları", value=" ".join(c['str'] for c in self.dealer_hand) + f" (Toplam: {d_val})")
        embed.add_field(name="Durum", value=f"{status}\nYeni Bakiye: **{get_balance(self.user_id):,}**", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    def stop_buttons(self):
        for child in self.children:
            child.disabled = True

@bot.tree.command(name="blackjack", description="Play a game of Blackjack against the dealer")
@app_commands.describe(bet="Amount of coins to bet")
async def blackjack_cmd(interaction: discord.Interaction, bet: int):
    if bet <= 0:
        return await interaction.response.send_message("❌ Bet amount must be greater than 0!", ephemeral=True)

    user_bal = get_balance(interaction.user.id)
    if bet > user_bal:
        return await interaction.response.send_message(f"❌ You don't have enough coins! Balance: **{user_bal:,}**", ephemeral=True)

    p_hand = [draw_card(), draw_card()]
    d_hand = [draw_card(), draw_card()]

    p_val = calculate_hand(p_hand)

    if p_val == 21:
        win_amt = int(bet * 2.5)
        update_balance(interaction.user.id, win_amt)
        embed = discord.Embed(title="🔥 BLACKJACK!", description=f"Doğal 21 yaptın ve **+{win_amt:,}** coin kazandın!", color=discord.Color.green())
        return await interaction.response.send_message(embed=embed)

    embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
    embed.add_field(name="Kartların", value=" ".join(c['str'] for c in p_hand) + f" (Toplam: {p_val})")
    embed.add_field(name="Kurpiyerin Açık Kartı", value=d_hand[0]['str'])

    view = BlackjackView(interaction.user.id, bet, p_hand, d_hand)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="leaderboard", description="Show server rich list with custom badges")
async def leaderboard_cmd(interaction: discord.Interaction):
    sorted_users = sorted(balance_store["users"].items(), key=lambda x: x[1], reverse=True)
    
    if not sorted_users:
        return await interaction.response.send_message("❌ No balance data found.", ephemeral=True)

    badges = ["💎", "🥇", "🥈", "🥈", "🥉", "🥉", "🥉", "🥉"]
    desc = ""

    for idx, (uid, bal) in enumerate(sorted_users[:8]):
        badge = badges[idx] if idx < len(badges) else "🥉"
        user_obj = interaction.guild.get_member(int(uid))
        name = user_obj.mention if user_obj else f"User ({uid})"
        desc += f"{badge} **#{idx+1}** {name} ➔ **{bal:,}** coins\n"

    embed = discord.Embed(title="🏆 Zenginler Sıralaması", description=desc, color=discord.Color.purple())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="pay", description="Send coins to another user")
@app_commands.describe(target="The user to receive coins", amount="Amount of coins to send")
async def pay_cmd(interaction: discord.Interaction, target: discord.User, amount: int):
    if target.id == interaction.user.id:
        return await interaction.response.send_message("❌ You cannot send coins to yourself!", ephemeral=True)
    if amount <= 0:
        return await interaction.response.send_message("❌ Amount must be greater than 0!", ephemeral=True)

    sender_bal = get_balance(interaction.user.id)
    if amount > sender_bal:
        return await interaction.response.send_message(f"❌ You don't have enough coins! Balance: **{sender_bal:,}**", ephemeral=True)

    update_balance(interaction.user.id, -amount)
    update_balance(target.id, amount)
    await interaction.response.send_message(f"💸 {interaction.user.mention} sent **{amount:,}** coins to {target.mention}!")

@bot.tree.command(name="set_balance", description="Set balance for a user (Bot Owner only)")
@app_commands.describe(user="Target user", amount="New balance amount")
async def set_balance_cmd(interaction: discord.Interaction, user: discord.User, amount: int):
    if str(interaction.user.id) != OWNER_ID:
        return await interaction.response.send_message("❌ Only the Bot Owner can use this command!", ephemeral=True)

    if amount < 0:
        return await interaction.response.send_message("❌ Balance cannot be negative!", ephemeral=True)

    balance_store["users"][str(user.id)] = amount
    save_balances(balance_store)
    await interaction.response.send_message(f"✅ Set {user.mention}'s balance to **{amount:,}** coins.")

# ==================== ROL MAĞAZASI KOMUTLARI ====================

SHOP_ITEMS = {
    "1": {"name": "VIP", "price": 50000},
    "2": {"name": "Milyoner 💎", "price": 100000},
    "3": {"name": "Sunucu Ağası 👑", "price": 250000}
}

@bot.tree.command(name="shop", description="Show server role shop")
async def shop_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="🛒 Unvan & Rol Mağazası", description="Coin biriktirerek Discord'da görünen özel roller satın alabilirsin!", color=discord.Color.gold())
    for item_id, data in SHOP_ITEMS.items():
        embed.add_field(name=f"ID `{item_id}` ➔ {data['name']}", value=f"Fiyat: **{data['price']:,}** coins", inline=False)
    embed.set_footer(text="Satın almak için: /buy [id] | İade/Takas için: /trade [id]")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buy", description="Buy a role from the shop")
@app_commands.describe(item_id="Role ID to buy (1, 2, 3)")
async def buy_cmd(interaction: discord.Interaction, item_id: str):
    if item_id not in SHOP_ITEMS:
        return await interaction.response.send_message("❌ Invalid item ID! Use `/shop` to view available items.", ephemeral=True)

    item = SHOP_ITEMS[item_id]
    price = item["price"]
    role_name = item["name"]
    user_bal = get_balance(interaction.user.id)

    if user_bal < price:
        return await interaction.response.send_message(f"❌ You don't have enough coins! Needed: **{price:,}**", ephemeral=True)

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
        try:
            role = await interaction.guild.create_role(name=role_name, color=discord.Color.random(), reason="Shop Role Created")
        except Exception as e:
            return await interaction.response.send_message(f"❌ Failed to create role on server: {e}", ephemeral=True)

    if role in interaction.user.roles:
        return await interaction.response.send_message("❌ You already have this role!", ephemeral=True)

    update_balance(interaction.user.id, -price)
    await interaction.user.add_roles(role)
    await interaction.response.send_message(f"🎉 Congratulations! You bought and equipped the **{role_name}** role!")

@bot.tree.command(name="trade", description="Satın aldığın bir unvanı/rolü iade edip coin geri al")
@app_commands.describe(item_id="İade etmek istediğin rolün Mağaza ID'si (1, 2, 3)")
async def trade_cmd(interaction: discord.Interaction, item_id: str):
    if item_id not in SHOP_ITEMS:
        return await interaction.response.send_message("❌ Geçersiz ürün ID'si! `/shop` yazarak ID'lere bakabilirsin.", ephemeral=True)

    item = SHOP_ITEMS[item_id]
    original_price = item["price"]
    role_name = item["name"]
    refund_amount = int(original_price * 0.8) # %80 geri iade oranı

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role or role not in interaction.user.roles:
        return await interaction.response.send_message(f"❌ Sende **{role_name}** rolü bulunmuyor!", ephemeral=True)

    try:
        await interaction.user.remove_roles(role)
    except Exception as e:
        return await interaction.response.send_message(f"❌ Rol senden alınırken bir hata oluştu: {e}", ephemeral=True)

    update_balance(interaction.user.id, refund_amount)
    await interaction.response.send_message(f"🔄 **{role_name}** unvanını başarıyla takas ettin/iade ettin! Hesabına **+{refund_amount:,}** coin eklendi (%80 İade).")
    # ==================== YÖNETİM & SES MODERASYON KOMUTLARI ====================

@bot.tree.command(name="move", description="Move user to another voice channel")
@app_commands.describe(user="Target user", channel="Destination voice channel")
@app_commands.checks.has_permissions(move_members=True)
async def move_cmd(interaction: discord.Interaction, user: discord.Member, channel: discord.VoiceChannel):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.move_to(channel)
    await interaction.response.send_message(f"🚚 Moved {user.mention} to **{channel.name}**!")

@bot.tree.command(name="mute", description="Mute user in voice channel")
@app_commands.describe(user="Target user")
@app_commands.checks.has_permissions(mute_members=True)
async def mute_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.edit(mute=True)
    await interaction.response.send_message(f"🤐 Muted {user.mention} in voice!")

@bot.tree.command(name="unmute", description="Unmute user in voice channel")
@app_commands.describe(user="Target user")
@app_commands.checks.has_permissions(mute_members=True)
async def unmute_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.edit(mute=False)
    await interaction.response.send_message(f"🎙️ Unmuted {user.mention} in voice!")

@bot.tree.command(name="deafen", description="Deafen user in voice channel")
@app_commands.describe(user="Target user")
@app_commands.checks.has_permissions(deafen_members=True)
async def deafen_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.edit(deafen=True)
    await interaction.response.send_message(f"🔇 Deafened {user.mention} in voice!")

@bot.tree.command(name="undeafen", description="Undeafen user in voice channel")
@app_commands.describe(user="Target user")
@app_commands.checks.has_permissions(deafen_members=True)
async def undeafen_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.edit(deafen=False)
    await interaction.response.send_message(f"🔊 Undeafened {user.mention} in voice!")

@bot.tree.command(name="disconnect", description="Disconnect user from voice channel")
@app_commands.describe(user="Target user")
@app_commands.checks.has_permissions(move_members=True)
async def disconnect_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice:
        return await interaction.response.send_message("❌ User is not in any voice channel!", ephemeral=True)
    await user.move_to(None)
    await interaction.response.send_message(f"🚪 Disconnected {user.mention} from voice!")

@bot.tree.command(name="clear", description="Clear text messages in current channel")
@app_commands.describe(amount="Number of messages to delete (1-100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear_cmd(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ Amount must be between 1 and 100!", ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Cleared **{len(deleted)}** messages!", ephemeral=True)

# ==================== CONFIG KOMUTLARI ====================

config_group = app_commands.Group(name="config", description="Bot configuration settings")

@config_group.command(name="voice_channel", description="Set default voice channel ID")
@app_commands.describe(channel_id="Voice channel ID (Numbers only)")
async def config_voice(interaction: discord.Interaction, channel_id: str):
    config_data["voice_channel_id"] = channel_id
    save_config(config_data)
    await interaction.response.send_message(f"🔊 Voice channel set to: `{channel_id}`")

@config_group.command(name="notification_channel", description="Set bot text channel ID")
@app_commands.describe(channel_id="Text channel ID (Numbers only)")
async def config_text(interaction: discord.Interaction, channel_id: str):
    config_data["text_channel_id"] = channel_id
    save_config(config_data)
    await interaction.response.send_message(f"💬 Notification text channel set to: `{channel_id}`")

@config_group.command(name="show", description="Show current bot configurations")
async def config_show(interaction: discord.Interaction):
    embed = discord.Embed(title="⚙️ Bot Configurations", color=discord.Color.gold())
    embed.add_field(name="Voice Channel ID", value=f"`{config_data.get('voice_channel_id') or 'Not Set'}`", inline=False)
    embed.add_field(name="Notification Text Channel ID", value=f"`{config_data.get('text_channel_id') or 'Not Set'}`", inline=False)
    embed.set_footer(text="made by TeKyla")
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(config_group)

FINAL_TOKEN = os.getenv("TOKEN") or BOT_TOKEN

if __name__ == "__main__":
    if FINAL_TOKEN and FINAL_TOKEN != "BURAYA_BOT_TOKENINI_YAZ":
        bot.run(FINAL_TOKEN)
    else:
        print("ERROR: Bot Token not found!")
