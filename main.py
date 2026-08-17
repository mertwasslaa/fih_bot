import os
import asyncio
from flask import Flask
from threading import Thread

import discord
from discord.ext import commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# ==================== KULLANICI AYARLARI ====================
BOT_TOKEN = "BURAYA_BOT_TOKENINI_YAZ"
METIN_KANAL_ID = 123456789012345678  # Metin kanalı ID'si (Varsa)
SES_KANAL_ID = 123456789012345678    # Ses kanalı ID'si (Varsa)
# ============================================================

app = Flask('')

@app.route('/')
def home():
    return "FihBot 24/7 Active!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web, daemon=True).start()

# Spotify İstemcisi
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIPY_CLIENT_ID", "5ef970630e104111a43a05187766b57d"),
    client_secret=os.getenv("SPOTIPY_CLIENT_SECRET", "643e2f5b404d495dbbf77a0ef7394d13")
))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Şarkı Kuyruğu Yapısı {guild_id: [ {'title': ..., 'url': ...}, ... ]}
queues = {}

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

def get_spotify_query(url):
    try:
        if "track" in url:
            track = sp.track(url)
            artist = track['artists'][0]['name']
            song_name = track['name']
            return f"{artist} - {song_name}"
    except Exception as e:
        print(f"Spotify error: {e}")
    return None

def play_next(ctx):
    """Sıradaki şarkıyı otomatik çalma fonksiyonu"""
    guild_id = ctx.guild.id
    if guild_id in queues and len(queues[guild_id]) > 0:
        next_song = queues[guild_id].pop(0)
        source = discord.FFmpegPCMAudio(next_song['url'], **FFMPEG_OPTIONS)
        
        ctx.voice_client.play(
            source, 
            after=lambda e: (print(f"Playback error: {e}") if e else None, play_next(ctx))
        )
        
        asyncio.run_coroutine_threadsafe(
            ctx.send(f"🎵 **{next_song['title']}** - good taste of music 🔥"),
            bot.loop
        )
    else:
        # Sıra bittiğinde listeyi temizle
        if guild_id in queues:
            del queues[guild_id]

@bot.event
async def on_ready():
    print(f"Bot logged in as: {bot.user.name}")
    if SES_KANAL_ID:
        try:
            channel = bot.get_channel(SES_KANAL_ID)
            if channel and isinstance(channel, discord.VoiceChannel):
                await channel.connect()
                print(f"Auto-connected to voice channel: {channel.name}")
        except Exception as e:
            print(f"Voice connection error: {e}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if METIN_KANAL_ID and message.channel.id != METIN_KANAL_ID:
        return
    await bot.process_commands(message)

@bot.command(name="katil", aliases=["join"])
async def katil(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await channel.connect()
            await ctx.send("hi guyyyss 👋")
        else:
            await ctx.voice_client.move_to(channel)
            await ctx.send("hi guyyyss 👋")
    else:
        await ctx.send("❌ You gotta join a voice channel first!")

@bot.command(name="ayril", aliases=["leave"])
async def ayril(ctx):
    if ctx.voice_client:
        guild_id = ctx.guild.id
        if guild_id in queues:
            del queues[guild_id]
        await ctx.voice_client.disconnect()
        await ctx.send("maan realy 🙄")
    else:
        await ctx.send("❌ I'm not even in a voice channel bro.")

@bot.command(name="cal", aliases=["play"])
async def cal(ctx, *, url_veya_arama: str):
    target_voice = ctx.voice_client

    if not target_voice:
        if ctx.author.voice:
            target_voice = await ctx.author.voice.channel.connect()
        elif SES_KANAL_ID:
            channel = bot.get_channel(SES_KANAL_ID)
            if channel:
                target_voice = await channel.connect()

    if not target_voice:
        return await ctx.send("❌ Bot is not in any voice channel!")

    async with ctx.typing():
        try:
            query = url_veya_arama.strip()

            if "spotify.com" in query:
                await ctx.send("💚 Fetching from Spotify...")
                spotify_search = get_spotify_query(query)
                if spotify_search:
                    query = spotify_search
                else:
                    return await ctx.send("❌ Couldn't parse Spotify link.")

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
            
            if 'entries' in data and len(data['entries']) > 0:
                data = data['entries'][0]

            song_url = data.get('url')
            title = data.get('title', 'Unknown Track')

            if not song_url:
                return await ctx.send("❌ Couldn't fetch audio link.")

            guild_id = ctx.guild.id

            # Eğer şu an bir şarkı çalıyorsa yeni geleni sıraya ekle
            if target_voice.is_playing() or target_voice.is_paused():
                if guild_id not in queues:
                    queues[guild_id] = []
                queues[guild_id].append({'title': title, 'url': song_url})
                await ctx.send(f"📋 Added to queue (#{len(queues[guild_id])}): **{title}**")
            else:
                # Çalan bişey yoksa direkt başlat
                source = discord.FFmpegPCMAudio(song_url, **FFMPEG_OPTIONS)
                target_voice.play(
                    source, 
                    after=lambda e: (print(f"Playback error: {e}") if e else None, play_next(ctx))
                )
                await ctx.send(f"🎵 **{title}** - good taste of music 🔥")

        except Exception as e:
            print(f"Error: {e}")
            await ctx.send(f"❌ Failed to play: `{e}`")

@bot.command(name="gec", aliases=["skip"])
async def gec(ctx):
    """Mevcut şarkıyı atlar ve sıradakine geçer"""
    if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
        ctx.voice_client.stop() # stop çarıldığında after parametresi sayesinde otomatik play_next çalışır
        await ctx.send("next one then ⏭️")
    else:
        await ctx.send("❌ Nothing is playing to skip bro.")

@bot.command(name="sira", aliases=["queue"])
async def sira(ctx):
    """Sıradaki şarkıları listeler"""
    guild_id = ctx.guild.id
    if guild_id in queues and len(queues[guild_id]) > 0:
        queue_list = "\n".join([f"**{i+1}.** {song['title']}" for i, song in enumerate(queues[guild_id])])
        await ctx.send(f"📜 **Current Queue:**\n{queue_list}")
    else:
        await ctx.send("📜 Queue is empty right now.")

@bot.command(name="dur", aliases=["stop"])
async def dur(ctx):
    guild_id = ctx.guild.id
    if guild_id in queues:
        queues[guild_id].clear() # Sırayı da temizle
        
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("k? 🤨")
    else:
        await ctx.send("❌ Nothing is playing right now.")

FINAL_TOKEN = os.getenv("TOKEN") or BOT_TOKEN

if __name__ == "__main__":
    if FINAL_TOKEN and FINAL_TOKEN != "BURAYA_BOT_TOKENINI_YAZ":
        bot.run(FINAL_TOKEN)
    else:
        print("ERROR: Bot Token not found!")
