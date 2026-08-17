import os
import asyncio
from flask import Flask
from threading import Thread

import discord
from discord.ext import commands
import yt_dlp

# ==================== KULLANICI AYARLARI ====================
BOT_TOKEN = "MTUzODY0MDgwNzI4Mjg2ODMwNA.Gu54R0.tNAodBqDwUmN4c3XcaK4IKwUfBy_UIATzt-uq4"
METIN_KANAL_ID = 1538636940230926507  # Metin kanalı ID'si (Varsa)
SES_KANAL_ID = 1516142852814540923    # Ses kanalı ID'si (Varsa)
# ============================================================

app = Flask('')

@app.route('/')
def home():
    return "FihBot 24/7 Active!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web, daemon=True).start()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# YouTube bot engelini asmak icin iOS/mweb istemci taklidi yapan konfigurasyon
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractflat': False,
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'cachedir': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'mweb']
        }
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

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
            clean_url = url_veya_arama.split("?si=")[0] if "?si=" in url_veya_arama else url_veya_arama

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(clean_url, download=False))
            
            if 'entries' in data and len(data['entries']) > 0:
                data = data['entries'][0]

            song_url = data.get('url')
            title = data.get('title', 'Unknown Track')

            if not song_url:
                return await ctx.send("❌ Couldn't fetch song link.")

            source = discord.FFmpegPCMAudio(song_url, **FFMPEG_OPTIONS)
            
            if target_voice.is_playing():
                target_voice.stop()

            target_voice.play(source, after=lambda e: print(f"Playback error: {e}") if e else None)
            await ctx.send(f"🎵 **{title}** - good taste of music 🔥")

        except Exception as e:
            print(f"Error: {e}")
            await ctx.send(f"❌ Failed to play: `{e}`")

@bot.command(name="dur", aliases=["stop"])
async def dur(ctx):
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
