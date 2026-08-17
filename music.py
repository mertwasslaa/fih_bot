# =====================================================================
# FIH BOT - PART 2: MUSIC COMMANDS
# =====================================================================
import os
import asyncio
from typing import Any, Dict, List

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

        self.music_queues: Dict[int, List[Dict[str, Any]]] = {}
        self.current_playing: Dict[int, Dict[str, Any]] = {}
        self.loop_modes: Dict[int, str] = {}

        self.spotify = None
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        if client_id and client_secret:
            try:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=client_id, client_secret=client_secret
                    )
                )
                print("Connected to the Spotify API.")
            except Exception as e:
                print(f"Failed to connect to the Spotify API: {e}")

    def extract_spotify_queries(self, url: str) -> List[str]:
        queries: List[str] = []
        if not self.spotify:
            return queries
        try:
            if "track" in url:
                t = self.spotify.track(url)
                queries.append(f"{t['name']} {t['artists'][0]['name']}")
            elif "playlist" in url:
                items = self.spotify.playlist_items(url).get("items", [])
                for it in items:
                    track = it.get("track")
                    if track:
                        queries.append(f"{track['name']} {track['artists'][0]['name']}")
            elif "album" in url:
                items = self.spotify.album_tracks(url).get("items", [])
                for it in items:
                    queries.append(f"{it['name']} {it['artists'][0]['name']}")
        except Exception as e:
            print(f"Error processing Spotify link: {e}")
        return queries

    async def play_next(self, guild: discord.Guild, channel: discord.abc.Messageable):
        gid = guild.id
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return

        mode = self.loop_modes.get(gid, "off")

        if mode == "single" and gid in self.current_playing:
            pass
        elif mode == "queue" and gid in self.current_playing:
            self.music_queues.setdefault(gid, []).append(self.current_playing[gid])
            if self.music_queues[gid]:
                self.current_playing[gid] = self.music_queues[gid].pop(0)
            else:
                self.current_playing.pop(gid, None)
        else:
            if self.music_queues.get(gid):
                self.current_playing[gid] = self.music_queues[gid].pop(0)
            else:
                self.current_playing.pop(gid, None)

        if gid not in self.current_playing or not self.current_playing[gid]:
            await channel.send("🎵 Queue finished, leaving the voice channel...")
            await vc.disconnect()
            return

        song = self.current_playing[gid]
        source = discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS)

        def after_playing(error):
            if error:
                print(f"Playback error: {error}")
            fut = asyncio.run_coroutine_threadsafe(self.play_next(guild, channel), self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f"Error in play_next callback: {e}")

        vc.play(source, after=after_playing)
        await channel.send(f"🎶 Now playing: **{song['title']}**")

    @app_commands.command(name="play", description="Play a song, video, or playlist from YouTube or Spotify.")
    @app_commands.describe(query="Song name or a YouTube/Spotify link")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send("❌ You need to join a voice channel first!")

        voice_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client
        if not vc:
            vc = await voice_channel.connect()
        elif vc.channel != voice_channel:
            await vc.move_to(voice_channel)

        gid = interaction.guild_id
        self.music_queues.setdefault(gid, [])

        if "spotify.com" in query:
            queries = self.extract_spotify_queries(query)
            if not queries:
                return await interaction.followup.send(
                    "❌ Couldn't process that Spotify link, or the Spotify API keys aren't configured."
                )

            await interaction.followup.send(f"🔍 Added **{len(queries)}** track(s) from Spotify to the queue.")
            for q in queries:
                try:
                    data = await self.bot.loop.run_in_executor(
                        None, lambda q=q: self.ytdl.extract_info(f"ytsearch:{q}", download=False)
                    )
                except Exception as e:
                    print(f"YouTube search failed ({q}): {e}")
                    continue
                if data and "entries" in data and data["entries"]:
                    entry = data["entries"][0]
                    self.music_queues[gid].append({"title": entry["title"], "url": entry["url"]})

            if not vc.is_playing() and gid not in self.current_playing:
                await self.play_next(interaction.guild, interaction.channel)
            return

        try:
            data = await self.bot.loop.run_in_executor(
                None,
                lambda: self.ytdl.extract_info(
                    query if query.startswith("http") else f"ytsearch:{query}", download=False
                ),
            )
        except Exception as e:
            return await interaction.followup.send(f"❌ Something went wrong while searching: {e}")

        if not data:
            return await interaction.followup.send("❌ No results found.")

        if "entries" in data:
            if not data["entries"]:
                return await interaction.followup.send("❌ No results found.")
            data = data["entries"][0]

        song = {"title": data["title"], "url": data["url"]}
        self.music_queues[gid].append(song)

        if vc.is_playing() or gid in self.current_playing:
            await interaction.followup.send(f"➕ Added to queue: **{song['title']}**")
        else:
            await interaction.followup.send(f"🔍 Found it, now playing: **{song['title']}**")
            await self.play_next(interaction.guild, interaction.channel)

    @app_commands.command(name="skip", description="Skip the currently playing song.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped.")
        else:
            await interaction.response.send_message("❌ Nothing is playing right now.", ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    async def stop(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        self.music_queues[gid] = []
        self.current_playing.pop(gid, None)
        vc = interaction.guild.voice_client
        if vc:
            await vc.disconnect()
            await interaction.response.send_message("⏹️ Stopped playback and cleared the queue.")
        else:
            await interaction.response.send_message("❌ The bot isn't connected to a voice channel.", ephemeral=True)

    @app_commands.command(name="queue", description="Show the current music queue.")
    async def queue(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        q = self.music_queues.get(gid, [])
        current = self.current_playing.get(gid)

        if not current and not q:
            return await interaction.response.send_message("📜 The queue is empty.")

        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blurple())
        if current:
            embed.add_field(name="Now Playing", value=current["title"], inline=False)
        if q:
            listed = "\n".join(f"**{i + 1}.** {s['title']}" for i, s in enumerate(q[:10]))
            if len(q) > 10:
                listed += f"\n*...and {len(q) - 10} more*"
            embed.add_field(name="Up Next", value=listed, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="Set the queue repeat mode.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Single Song", value="single"),
            app_commands.Choice(name="Entire Queue", value="queue"),
        ]
    )
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        self.loop_modes[interaction.guild_id] = mode.value
        await interaction.response.send_message(f"🔁 Repeat mode set to: **{mode.name}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
