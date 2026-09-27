# =====================================================================
# FIH BOT - PART 4: EXTRA COMMANDS (voice control, utility, radio)
# =====================================================================
import time

import discord
from discord import app_commands
from discord.ext import commands

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# Free public internet radio streams (SomaFM). Add more here if you want.
RADIO_STATIONS = {
    "lofi": ("Lofi Chill", "http://ice1.somafm.com/groovesalad-128-mp3"),
    "electronic": ("Electronic Beats", "http://ice1.somafm.com/beatblender-128-mp3"),
    "indie": ("Indie Pop", "http://ice1.somafm.com/indiepop-128-mp3"),
}


class Extra(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()
        self.autostay: set[int] = set()          # guild ids with /247 active
        self.radio_playing: dict[int, str] = {}  # guild id -> station key

    def get_music_cog(self):
        return self.bot.get_cog("Music")

    def find_voice_channel(self, guild: discord.Guild, name: str):
        return discord.utils.find(
            lambda c: isinstance(c, discord.VoiceChannel) and c.name.lower() == name.lower(),
            guild.channels,
        )

    # ---------- UTILITY ----------
    @app_commands.command(name="ping", description="Show the bot's current status and latency.")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        uptime_seconds = int(time.time() - self.start_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        embed = discord.Embed(title="🏓 Pong!", color=discord.Color.green())
        embed.add_field(name="Latency", value=f"{latency_ms}ms", inline=True)
        embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        await interaction.response.send_message(embed=embed)

    # ---------- VOICE CHANNEL CONTROL ----------
    @app_commands.command(name="join", description="Join a specific voice channel by name.")
    @app_commands.describe(channel_name="Name of the voice channel to join")
    async def join(self, interaction: discord.Interaction, channel_name: str):
        channel = self.find_voice_channel(interaction.guild, channel_name)
        if not channel:
            return await interaction.response.send_message(
                f"❌ Couldn't find a voice channel named **{channel_name}**.", ephemeral=True
            )

        vc = interaction.guild.voice_client
        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect()

        await interaction.response.send_message(f"✅ Joined **{channel.name}**.")

    @app_commands.command(name="leave", description="Kick the bot out of the voice channel.")
    async def leave(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message(
                "❌ I'm not even in a voice channel, relax.", ephemeral=True
            )

        self.autostay.discard(interaction.guild_id)
        self.radio_playing.pop(interaction.guild_id, None)
        await vc.disconnect()
        await interaction.response.send_message("👋 Alright, get the fuck out — I'm gone.")

    @app_commands.command(name="247", description="Join a voice channel and stay there 24/7 (no auto-leave).")
    @app_commands.describe(channel_name="Voice channel to camp in")
    async def two_four_seven(self, interaction: discord.Interaction, channel_name: str):
        channel = self.find_voice_channel(interaction.guild, channel_name)
        if not channel:
            return await interaction.response.send_message(
                f"❌ Couldn't find a voice channel named **{channel_name}**.", ephemeral=True
            )

        vc = interaction.guild.voice_client
        if vc:
            await vc.move_to(channel)
        else:
            await channel.connect()

        self.autostay.add(interaction.guild_id)
        await interaction.response.send_message(
            f"📌 24/7 mode on — staying in **{channel.name}** even with nothing playing."
        )

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        # If /247 is active for this guild and the bot somehow drops out
        # of voice, try to rejoin the same channel automatically.
        if member.id != self.bot.user.id:
            return
        guild_id = member.guild.id
        if guild_id in self.autostay and after.channel is None and before.channel is not None:
            try:
                await before.channel.connect()
            except Exception:
                pass

    # ---------- PLAYBACK CONTROL ----------
    @app_commands.command(name="pause", description="Pause the current song.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.")
        else:
            await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume the paused song.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("❌ Nothing is paused right now.", ephemeral=True)

    @app_commands.command(name="volume", description="Set radio playback volume (0-200%).")
    @app_commands.describe(level="Volume percentage, 0 to 200")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 200]):
        vc = interaction.guild.voice_client
        if not vc or not isinstance(vc.source, discord.PCMVolumeTransformer):
            return await interaction.response.send_message(
                "❌ Nothing adjustable is playing right now (works with /radio for now — "
                "see note below for enabling it on /play too).",
                ephemeral=True,
            )
        vc.source.volume = level / 100
        await interaction.response.send_message(f"🔊 Volume set to **{level}%**.")

    @app_commands.command(name="nowplaying", description="Show the currently playing song or station.")
    async def nowplaying(self, interaction: discord.Interaction):
        gid = interaction.guild_id

        if gid in self.radio_playing:
            name, _ = RADIO_STATIONS[self.radio_playing[gid]]
            return await interaction.response.send_message(f"📻 Now streaming radio: **{name}**")

        music_cog = self.get_music_cog()
        if not music_cog:
            return await interaction.response.send_message("❌ Music module isn't loaded.", ephemeral=True)

        current = music_cog.current_playing.get(gid)
        if not current:
            return await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)

        await interaction.response.send_message(f"🎶 Now playing: **{current['title']}**")

    # ---------- RADIO ----------
    @app_commands.command(name="radio", description="Play a continuous internet radio stream.")
    @app_commands.choices(
        station=[
            app_commands.Choice(name="Lofi Chill", value="lofi"),
            app_commands.Choice(name="Electronic Beats", value="electronic"),
            app_commands.Choice(name="Indie Pop", value="indie"),
        ]
    )
    async def radio(self, interaction: discord.Interaction, station: app_commands.Choice[str]):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message(
                "❌ You need to join a voice channel first!", ephemeral=True
            )

        await interaction.response.defer(thinking=True)
        voice_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        if not vc:
            vc = await voice_channel.connect()
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)

        if vc.is_playing() or vc.is_paused():
            vc.stop()

        name, url = RADIO_STATIONS[station.value]
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS))
        vc.play(source)
        self.radio_playing[interaction.guild_id] = station.value

        await interaction.followup.send(f"📻 Now streaming: **{name}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Extra(bot))
