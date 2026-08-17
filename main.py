import os
import json
import asyncio
import random
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
# GUILD_ID artık doğrudan çevre değişkeninden (Secret) çekiliyor:
GUILD_ID_ENV = os.getenv("GUILD_ID") 
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

# Spotify İstemcisi
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIPY_CLIENT_ID", "5ef970630e104111a43a05187766b57d"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET", "643e2f5b404d495dbbf77a0ef7394d13")
))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

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

# ==================== SUNUCUYA İLK KATILMA MESAJI ====================

@bot.event
async def on_guild_join(guild):
    """Bot yeni bir sunucuya katıldığında karşılama kartı gönderir."""
    target_channel = guild.system_channel
    if not target_channel:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                target_channel = channel
                break

    if target_channel:
        embed = discord.Embed(
            title="👋 Thanks for adding me!",
            description="Use `/play` to start listening to music or `/config` to setup default channels.",
            color=discord.Color.purple()
        )
        embed.set_footer(text="made by TeKyla")
        await target_channel.send(embed=embed)

# ==================== SLASH KOMUTLARI ====================

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
