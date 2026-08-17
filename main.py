import os
import asyncio
from flask import Flask
from threading import Thread

import discord
from discord.ext import commands
import yt_dlp

# ==================== KULLANICI AYARLARI ====================
# Buradaki alanlara kendi ID ve Token bilgilerini yazabilirsin:
BOT_TOKEN = "MTUzODY0MDgwNzI4Mjg2ODMwNA.Gu54R0.tNAodBqDwUmN4c3XcaK4IKwUfBy_UIATzt-uq4"
METIN_KANAL_ID = 1538636940230926507  # Botun bakacağı metin kanalı ID'si
SES_KANAL_ID = 1516142852814540923    # Botun otomatik gireceği ses kanalı ID'si
# ============================================================

# --- RENDER ÜCRETSİZ WEB SERVİSİ İÇİN MİNİ SUNUCU ---
app = Flask('')

@app.route('/')
def home():
    return "FihBot 7/24 Aktif!"

def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web, daemon=True).start()

# --- DISCORD BOT AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractflat': False,
    'noplaylist': True,
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

@bot.event
async def on_ready():
    print(f"Bot başarıyla giriş yaptı: {bot.user.name}")
    
    # Belirtilen ses kanalına otomatik bağlanma
    if SES_KANAL_ID:
        channel = bot.get_channel(SES_KANAL_ID)
        if channel and isinstance(channel, discord.VoiceChannel):
            await channel.connect()
            print(f"Ses kanalına otomatik bağlandı: {channel.name}")

@bot.event
async def on_message(message):
    # Botun kendi mesajlarını görmezden gel
    if message.author == bot.user:
        return

    # Eğer metin kanalı ID'si tanımlıysa, sadece o kanaldan gelen komutları çalıştır
    if METIN_KANAL_ID and message.channel.id != METIN_KANAL_ID:
        return

    await bot.process_commands(message)

@bot.command(name="katil", aliases=["join"])
async def katil(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await channel.connect()
            await ctx.send(f"🔊 **{channel.name}** kanalına bağlandım!")
        else:
            await ctx.voice_client.move_to(channel)
    else:
        await ctx.send("❌ Önce bir ses kanalına girmelisin!")

@bot.command(name="ayril", aliases=["leave"])
async def ayril(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Ses kanalından ayrıldım.")
    else:
        await ctx.send("❌ Zaten bir ses kanalında değilim.")

@bot.command(name="cal", aliases=["play"])
async def cal(ctx, *, url_veya_arama: str):
    # Eğer bot belirlenen sabit ses kanalında değilse veya kullanıcı ses kanalındaysa kontrol et
    target_voice = ctx.voice_client

    if not target_voice:
        if ctx.author.voice:
            target_voice = await ctx.author.voice.channel.connect()
        elif SES_KANAL_ID:
            channel = bot.get_channel(SES_KANAL_ID)
            if channel:
                target_voice = await channel.connect()

    if not target_voice:
        return await ctx.send("❌ Bot hiçbir ses kanalında değil!")

    async with ctx.typing():
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url_veya_arama, download=False))
        
        if 'entries' in data:
            data = data['entries'][0]

        song_url = data['url']
        title = data.get('title', 'Bilinmeyen Şarkı')

        source = discord.FFmpegPCMAudio(song_url, **FFMPEG_OPTIONS)
        
        if target_voice.is_playing():
            target_voice.stop()

        target_voice.play(source, after=lambda e: print(f"Oynatma hatası: {e}") if e else None)
        await ctx.send(f"🎵 **Şimdi Çalıyor:** {title}")

@bot.command(name="dur", aliases=["stop"])
async def dur(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏹️ Müzik durduruldu.")
    else:
        await ctx.send("❌ Şu an çalan bir müzik yok.")

# Token'ı koddaki BOT_TOKEN değişkeninden veya ortam değişkeninden al
FINAL_TOKEN = os.getenv("TOKEN") or BOT_TOKEN

if __name__ == "__main__":
    if FINAL_TOKEN and FINAL_TOKEN != "BURAYA_BOT_TOKENINI_YAZ":
        bot.run(FINAL_TOKEN)
    else:
        print("HATA: Bot Token'ı girilmedi! Lütfen koddaki 'BOT_TOKEN' alanını doldurun.")
