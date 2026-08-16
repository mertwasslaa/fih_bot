import random
import discord
from discord.ext import commands
import yt_dlp

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- KANAL VE TOKEN AYARLARI ---
TOKEN = "MTUzODY0MDgwNzI4Mjg2ODMwNA.Gu54R0.tNAodBqDwUmN4c3XcaK4IKwUfBy_UIATzt-uq4"
VOICE_CHANNEL_ID = 1516142852814540923  # Botun 7/24 duracağı ses kanalı ID'si
TEXT_CHANNEL_ID = 1538636940230926507   # Botun SADECE mesaj atacağı metin kanalı ID'si

# yt-dlp & FFmpeg Ayarları
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'default_search': 'ytsearch',
    'quiet': True
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

async def mesaj_gonder(gonderilecek_metin):
    """Botun sadece belirlenen metin kanalına yazmasını sağlar."""
    target_channel = bot.get_channel(TEXT_CHANNEL_ID)
    if target_channel:
        await target_channel.send(gonderilecek_metin)

@bot.event
async def on_ready():
    print(f'{bot.user} aktif!')
    vc_channel = bot.get_channel(VOICE_CHANNEL_ID)
    if vc_channel and not discord.utils.get(bot.voice_clients, guild=vc_channel.guild):
        await vc_channel.connect(reconnect=True)
        print("7/24 Ses kanalına bağlandı.")

# --- MÜZİK KOMUTLARI ---

@bot.command(name="play", help="Müzik çalar")
async def play(ctx, *, search: str):
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            await mesaj_gonder("Önce bir ses kanalında olmalısın!")
            return

    async with ctx.typing():
        info = ytdl.extract_info(search, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        
        url = info['url']
        title = info.get('title', 'Müzik')

        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()

        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source)
        await mesaj_gonder(f"🎵 **Çalınıyor:** {title}")

@bot.command(name="stop", help="Müziği durdurur")
async def stop(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await mesaj_gonder("⏹️ Müzik durduruldu.")

@bot.command(name="pause", help="Müziği duraklatır")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await mesaj_gonder("⏸️ Müzik duraklatıldı.")

@bot.command(name="resume", help="Müziği devam ettirir")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await mesaj_gonder("▶️ Müzik devam ettiriliyor.")

# --- BLACKJACK OYUNU ---

@bot.command(name="blackjack", aliases=["bj"], help="Blackjack oynar")
async def blackjack(ctx):
    def kart_cek():
        cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11]
        return random.choice(cards)

    oyuncu_kartlar = [kart_cek(), kart_cek()]
    bot_kartlar = [kart_cek(), kart_cek()]

    oyuncu_toplam = sum(oyuncu_kartlar)
    bot_toplam = sum(bot_kartlar)

    msg = f"🃏 **Blackjack** ({ctx.author.mention})\n"
    msg += f"**Senin Kartların:** {oyuncu_kartlar} (Toplam: {oyuncu_toplam})\n"
    msg += f"**Botun Açık Kartı:** [{bot_kartlar[0]}, ?]\n\n"

    if oyuncu_toplam == 21:
        msg += "🎉 **Blackjack! Doğrudan kazandın!**"
    elif oyuncu_toplam > 21:
        msg += "💥 **21'i geçtin, kaybettin!**"
    else:
        while bot_toplam < 17:
            bot_kartlar.append(kart_cek())
            bot_toplam = sum(bot_kartlar)

        msg += f"**Botun Bütün Kartları:** {bot_kartlar} (Toplam: {bot_toplam})\n\n"

        if bot_toplam > 21 or oyuncu_toplam > bot_toplam:
            msg += "🏆 **Tebrikler, kazandın!**"
        elif oyuncu_toplam < bot_toplam:
            msg += "❌ **Bot kazandı, kaybettin!**"
        else:
            msg += "🤝 **Berabere bitti!**"

    await mesaj_gonder(msg)

bot.run(TOKEN)
