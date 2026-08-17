import os
import io
import asyncio
import random
from typing import Dict, Any, List

import discord
from discord.ext import commands
from discord import app_commands, File
from flask import Flask
from threading import Thread
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
OWNER_ID = "1468988203376578728"

SPOTIPY_CLIENT_ID = "f9409415a62e44a28c2610c526a8b3ec"
SPOTIPY_CLIENT_SECRET = "b0d0bd3c15c84e39a79bf7f32476f630"

# Keep-Alive Web Server setup
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# Spotify API Setup
sp = None
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET and SPOTIPY_CLIENT_ID != "YOUR_SPOTIFY_CLIENT_ID":
    try:
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET
        ))
    except Exception as e:
        print(f"Spotify connection failed: {e}")

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global Music State & Balance Storage
music_queues: Dict[int, List[Dict[str, Any]]] = {}
current_songs: Dict[int, Dict[str, Any]] = {}
loop_modes: Dict[int, str] = {}  # "off", "single", "queue"
balance_store: Dict[str, Any] = {"users": {}}

# yt-dlp Configuration
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
# ==========================================
# HELPER FUNCTIONS
# ==========================================
def search_ytdl(query: str) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False)))

def get_spotify_tracks(url: str) -> List[str]:
    tracks = []
    if not sp:
        return tracks
    try:
        if "track" in url:
            track = sp.track(url)
            tracks.append(f"{track['name']} {track['artists'][0]['name']}")
        elif "playlist" in url:
            results = sp.playlist_items(url)
            for item in results['items']:
                t = item['track']
                if t:
                    tracks.append(f"{t['name']} {t['artists'][0]['name']}")
        elif "album" in url:
            results = sp.album_tracks(url)
            for item in results['items']:
                tracks.append(f"{item['name']} {item['artists'][0]['name']}")
    except Exception as e:
        print(f"Spotify fetch error: {e}")
    return tracks

async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    vc = interaction.guild.voice_client

    if not vc or not vc.is_connected():
        return

    mode = loop_modes.get(guild_id, "off")

    if mode == "single" and guild_id in current_songs:
        pass  # Keep current_song as is
    elif mode == "queue" and guild_id in current_songs:
        music_queues.setdefault(guild_id, []).append(current_songs[guild_id])
        if music_queues[guild_id]:
            current_songs[guild_id] = music_queues[guild_id].pop(0)
        else:
            current_songs.pop(guild_id, None)
    else:
        if music_queues.get(guild_id):
            current_songs[guild_id] = music_queues[guild_id].pop(0)
        else:
            current_songs.pop(guild_id, None)

    if guild_id not in current_songs or not current_songs[guild_id]:
        await interaction.channel.send("🎵 Queue is empty. Leaving the voice channel...")
        await vc.disconnect()
        return

    song = current_songs[guild_id]
    source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)

    def after_playing(error):
        if error:
            print(f"Player error: {error}")
        coro = play_next(interaction)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except Exception as ex:
            print(f"Error in after_playing callback: {ex}")

    vc.play(source, after=after_playing)
    await interaction.channel.send(f"🎶 Now Playing: **{song['title']}**")

# ==========================================
# MUSIC COMMANDS
# ==========================================
@bot.tree.command(name="play", description="Play a song or playlist from YouTube/Spotify")
@app_commands.describe(query="Song name or URL")
async def play(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if not interaction.user.voice:
        return await interaction.followup.send("❌ You need to be in a voice channel to use this command!")

    voice_channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client

    if not vc:
        vc = await voice_channel.connect()

    guild_id = interaction.guild_id
    music_queues.setdefault(guild_id, [])

    if "spotify.com" in query:
        tracks = get_spotify_tracks(query)
        if not tracks:
            return await interaction.followup.send("❌ Could not process the Spotify link or Spotify API credentials are missing.")
        
        await interaction.followup.send(f"🔍 Added **{len(tracks)}** track(s) from Spotify to the queue...")
        for track_query in tracks:
            data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{track_query}", download=False))
            if 'entries' in data and len(data['entries']) > 0:
                info = data['entries'][0]
                song = {'title': info['title'], 'url': info['url']}
                music_queues[guild_id].append(song)

        if not vc.is_playing() and guild_id not in current_songs:
            await play_next(interaction)
        return

    data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(query if query.startswith("http") else f"ytsearch:{query}", download=False))
    if 'entries' in data:
        data = data['entries'][0]

    song = {'title': data['title'], 'url': data['url']}
    music_queues[guild_id].append(song)

    if vc.is_playing() or guild_id in current_songs:
        await interaction.followup.send(f"➕ Added to queue: **{song['title']}**")
    else:
        await play_next(interaction)
        await interaction.followup.send(f"🔍 Searching and playing: **{song['title']}**")

@bot.tree.command(name="skip", description="Skip the current playing song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped current song.")
    else:
        await interaction.response.send_message("❌ Nothing is currently playing.", ephemeral=True)

@bot.tree.command(name="stop", description="Stop music and clear the queue")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    music_queues[guild_id] = []
    current_songs.pop(guild_id, None)
    vc = interaction.guild.voice_client

    if vc:
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Stopped music and cleared the queue.")
    else:
        await interaction.response.send_message("❌ The bot is not connected to a voice channel.", ephemeral=True)

@bot.tree.command(name="queue", description="Display the current music queue")
async def queue_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    q = music_queues.get(guild_id, [])
    curr = current_songs.get(guild_id)

    if not curr and not q:
        return await interaction.response.send_message("📜 Queue is currently empty.")

    embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blue())
    if curr:
        embed.add_field(name="Now Playing", value=curr['title'], inline=False)

    if q:
        queue_list = "\n".join([f"**{i+1}.** {song['title']}" for i, song in enumerate(q[:10])])
        if len(q) > 10:
            queue_list += f"\n*...and {len(q)-10} more songs*"
        embed.add_field(name="Up Next", value=queue_list, inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="loop", description="Set repeat mode (off, single, queue)")
@app_commands.choices(mode=[
    app_commands.Choice(name="Off", value="off"),
    app_commands.Choice(name="Single Song", value="single"),
    app_commands.Choice(name="Entire Queue", value="queue")
])
async def loop_cmd(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    loop_modes[interaction.guild_id] = mode.value
    await interaction.response.send_message(f"🔁 Repeat mode set to: **{mode.name}**")

# ==========================================
# MINI-GAMES & FIHCOIN SYSTEM
# ==========================================
def get_balance(user_id: int) -> int:
    return balance_store["users"].get(str(user_id), 1000)

def set_balance(user_id: int, amount: int):
    balance_store["users"][str(user_id)] = amount

@bot.tree.command(name="balance", description="Check your current Fihcoin balance")
async def balance_cmd(interaction: discord.Interaction):
    bal = get_balance(interaction.user.id)
    await interaction.response.send_message(f"💰 Your balance: **{bal:,} Fihcoins**.")

@bot.tree.command(name="coinflip", description="Flip a coin and bet Fihcoins")
@app_commands.choices(choice=[
    app_commands.Choice(name="Heads", value="heads"),
    app_commands.Choice(name="Tails", value="tails")
])
async def coinflip(interaction: discord.Interaction, choice: app_commands.Choice[str], bet: int):
    if bet <= 0:
        return await interaction.response.send_message("❌ Bet amount must be greater than 0!", ephemeral=True)

    user_id = interaction.user.id
    bal = get_balance(user_id)

    if bet > bal:
        return await interaction.response.send_message(f"❌ Insufficient balance! Current balance: **{bal:,} Fihcoins**.", ephemeral=True)

    outcome = random.choice(["heads", "tails"])
    if choice.value == outcome:
        new_bal = bal + bet
        set_balance(user_id, new_bal)
        await interaction.response.send_message(f"🪙 Result: **{outcome.upper()}**! You won **{bet:,} Fihcoins**! 🎉 New balance: **{new_bal:,} Fihcoins**.")
    else:
        new_bal = bal - bet
        set_balance(user_id, new_bal)
        await interaction.response.send_message(f"🪙 Result: **{outcome.upper()}**! You lost **{bet:,} Fihcoins**. 😢 New balance: **{new_bal:,} Fihcoins**.")

@bot.tree.command(name="set_balance", description="Set Fihcoin balance for a user (Bot Owner only)")
@app_commands.describe(user="Target user", amount="New balance amount")
async def set_balance_cmd(interaction: discord.Interaction, user: discord.User, amount: int):
    if str(interaction.user.id) != OWNER_ID:
        return await interaction.response.send_message("❌ Only the Bot Owner can use this command!", ephemeral=True)

    if amount < 0:
        return await interaction.response.send_message("❌ Balance cannot be negative!", ephemeral=True)

    set_balance(user.id, amount)
    await interaction.response.send_message(f"✅ Set {user.mention}'s balance to **{amount:,} Fihcoins**.")

# ==========================================
# SERVER MANAGEMENT COMMANDS
# ==========================================
@bot.tree.command(name="clear", description="Bulk delete messages in the channel")
@app_commands.describe(amount="Number of messages to delete (1-100)")
async def clear_cmd(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("❌ You lack `Manage Messages` permission to use this command!", ephemeral=True)

    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ Please specify a number between 1 and 100.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Successfully cleared **{len(deleted)}** messages.", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.describe(member="Target member", reason="Reason for kick")
async def kick_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        return await interaction.response.send_message("❌ You lack `Kick Members` permission to use this command!", ephemeral=True)

    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 Kicked **{member.name}**. Reason: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to kick user: {e}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.describe(member="Target member", reason="Reason for ban")
async def ban_cmd(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("❌ You lack `Ban Members` permission to use this command!", ephemeral=True)

    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 Banned **{member.name}**. Reason: {reason}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to ban user: {e}", ephemeral=True)

# ==========================================
# BOT EVENTS & STARTUP
# ==========================================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} application command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

if __name__ == "__main__":
    keep_alive()
    bot.run(BOT_TOKEN)
