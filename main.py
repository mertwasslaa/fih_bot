# =====================================================================
# FIH BOT - PART 1: CONFIGURATION, IMPORTS, AND HELPERS
# =====================================================================

import os
import io
import asyncio
import random
from typing import Dict, Any, List

import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask
from threading import Thread
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# =====================================================================
# CONFIGURATION & ENVIRONMENT SETUP
# =====================================================================
BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
OWNER_ID = "YOUR_DISCORD_USER_ID"

SPOTIPY_CLIENT_ID = "YOUR_SPOTIFY_CLIENT_ID"
SPOTIPY_CLIENT_SECRET = "YOUR_SPOTIFY_CLIENT_SECRET"

# Flask Web Server for Keeping the Bot Alive (Render / Replit hosting)
app = Flask(__name__)

@app.route('/')
def home():
    return "Fih Bot is running and active!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()

# Spotify API Client Initialization
spotify_client = None
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET and SPOTIPY_CLIENT_ID != "YOUR_SPOTIFY_CLIENT_ID":
    try:
        spotify_client = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=SPOTIPY_CLIENT_ID,
                client_secret=SPOTIPY_CLIENT_SECRET
            )
        )
        print("Successfully connected to Spotify API.")
    except Exception as error:
        print(f"Failed to connect to Spotify API: {error}")

# Discord Bot Intents and Instance Setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =====================================================================
# GLOBAL STATE MANAGEMENT DICTIONARIES
# =====================================================================
music_queues: Dict[int, List[Dict[str, Any]]] = {}
current_playing_songs: Dict[int, Dict[str, Any]] = {}
guild_loop_modes: Dict[int, str] = {}  # Modes: "off", "single", "queue"
economy_database: Dict[str, Any] = {"users": {}}

# =====================================================================
# YTDL AND FFMPEG CONFIGURATION OPTIONS
# =====================================================================
YTDL_DOWNLOAD_OPTIONS = {
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

FFMPEG_AUDIO_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

youtube_dl_instance = yt_dlp.YoutubeDL(YTDL_DOWNLOAD_OPTIONS)

# =====================================================================
# MUSIC HELPER FUNCTIONS & LOGIC
# =====================================================================
def extract_spotify_track_queries(playlist_or_track_url: str) -> List[str]:
    extracted_track_list = []
    if not spotify_client:
        return extracted_track_list
    try:
        if "track" in playlist_or_track_url:
            track_data = spotify_client.track(playlist_or_track_url)
            track_name = track_data['name']
            artist_name = track_data['artists'][0]['name']
            extracted_track_list.append(f"{track_name} {artist_name}")
        elif "playlist" in playlist_or_track_url:
            playlist_results = spotify_client.playlist_items(playlist_or_track_url)
            for playlist_item in playlist_results.get('items', []):
                track_obj = playlist_item.get('track')
                if track_obj:
                    t_name = track_obj['name']
                    a_name = track_obj['artists'][0]['name']
                    extracted_track_list.append(f"{t_name} {a_name}")
        elif "album" in playlist_or_track_url:
            album_results = spotify_client.album_tracks(playlist_or_track_url)
            for album_item in album_results.get('items', []):
                al_t_name = album_item['name']
                al_a_name = album_item['artists'][0]['name']
                extracted_track_list.append(f"{al_t_name} {al_a_name}")
    except Exception as spotify_error:
        print(f"Error while fetching tracks from Spotify link: {spotify_error}")
    return extracted_track_list

async def advance_and_play_next_song(interaction: discord.Interaction):
    target_guild_id = interaction.guild_id
    voice_client_instance = interaction.guild.voice_client

    if not voice_client_instance or not voice_client_instance.is_connected():
        return

    active_loop_mode = guild_loop_modes.get(target_guild_id, "off")

    if active_loop_mode == "single" and target_guild_id in current_playing_songs:
        pass
    elif active_loop_mode == "queue" and target_guild_id in current_playing_songs:
        music_queues.setdefault(target_guild_id, []).append(current_playing_songs[target_guild_id])
        if music_queues[target_guild_id]:
            current_playing_songs[target_guild_id] = music_queues[target_guild_id].pop(0)
        else:
            current_playing_songs.pop(target_guild_id, None)
    else:
        if music_queues.get(target_guild_id):
            current_playing_songs[target_guild_id] = music_queues[target_guild_id].pop(0)
        else:
            current_playing_songs.pop(target_guild_id, None)

    if target_guild_id not in current_playing_songs or not current_playing_songs[target_guild_id]:
        await interaction.channel.send("🎵 The music queue is now empty. Disconnecting from the voice channel...")
        await voice_client_instance.disconnect()
        return

    current_song_data = current_playing_songs[target_guild_id]
    audio_source_stream = discord.FFmpegPCMAudio(current_song_data['url'], **FFMPEG_AUDIO_OPTIONS)

    def handle_playback_completion(error_obj):
        if error_obj:
            print(f"Encountered an error during audio playback: {error_obj}")
        coroutine_task = advance_and_play_next_song(interaction)
        future_result = asyncio.run_coroutine_threadsafe(coroutine_task, bot.loop)
        try:
            future_result.result()
        except Exception as future_exception:
            print(f"Error handling asynchronous callback in playback loop: {future_exception}")

    voice_client_instance.play(audio_source_stream, after=handle_playback_completion)
    await interaction.channel.send(f"🎶 Now playing: **{current_song_data['title']}**")
    # =====================================================================
# FIH BOT - PART 2: MUSIC COMMANDS MODULE
# =====================================================================

@bot.tree.command(name="play", description="Play a song, video, or playlist from YouTube or Spotify.")
@app_commands.describe(query="The name of the song or the direct URL from YouTube/Spotify")
async def play_slash_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)

    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.followup.send("❌ You must be connected to a voice channel to use this command!")

    user_voice_channel = interaction.user.voice.channel
    voice_client_ref = interaction.guild.voice_client

    if not voice_client_ref:
        voice_client_ref = await user_voice_channel.connect()

    guild_identifier = interaction.guild_id
    music_queues.setdefault(guild_identifier, [])

    if "spotify.com" in query:
        track_queries_found = extract_spotify_track_queries(query)
        if not track_queries_found:
            return await interaction.followup.send("❌ Unable to process the Spotify link, or Spotify API keys are not configured.")
        
        await interaction.followup.send(f"🔍 Successfully added **{len(track_queries_found)}** track(s) from Spotify to the queue.")
        for single_query in track_queries_found:
            search_result_data = await bot.loop.run_in_executor(None, lambda: youtube_dl_instance.extract_info(f"ytsearch:{single_query}", download=False))
            if 'entries' in search_result_data and len(search_result_data['entries']) > 0:
                best_entry = search_result_data['entries'][0]
                new_song_item = {'title': best_entry['title'], 'url': best_entry['url']}
                music_queues[guild_identifier].append(new_song_item)

        if not voice_client_ref.is_playing() and guild_identifier not in current_playing_songs:
            await advance_and_play_next_song(interaction)
        return

    extracted_info_dict = await bot.loop.run_in_executor(
        None, 
        lambda: youtube_dl_instance.extract_info(query if query.startswith("http") else f"ytsearch:{query}", download=False)
    )

    if 'entries' in extracted_info_dict:
        extracted_info_dict = extracted_info_dict['entries'][0]

    song_payload = {
        'title': extracted_info_dict['title'],
        'url': extracted_info_dict['url']
    }

    music_queues[guild_identifier].append(song_payload)

    if voice_client_ref.is_playing() or guild_identifier in current_playing_songs:
        await interaction.followup.send(f"➕ Added song to the queue: **{song_payload['title']}**")
    else:
        await advance_and_play_next_song(interaction)
        await interaction.followup.send(f"🔍 Searching and playing: **{song_payload['title']}**")

@bot.tree.command(name="skip", description="Skip the currently playing song in the voice channel.")
async def skip_slash_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    voice_client_ref = interaction.guild.voice_client
    if voice_client_ref and voice_client_ref.is_playing():
        voice_client_ref.stop()
        await interaction.followup.send("⏭️ Successfully skipped the current song.")
    else:
        await interaction.followup.send("❌ There is no song currently playing to skip.")

@bot.tree.command(name="stop", description="Stop the music playback and clear the entire music queue.")
async def stop_slash_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    guild_identifier = interaction.guild_id
    music_queues[guild_identifier] = []
    current_playing_songs.pop(guild_identifier, None)
    voice_client_ref = interaction.guild.voice_client

    if voice_client_ref:
        await voice_client_ref.disconnect()
        await interaction.followup.send("⏹️ Stopped music playback and cleared the queue.")
    else:
        await interaction.followup.send("❌ The bot is not currently connected to any voice channel.")

@bot.tree.command(name="queue", description="Display the current music queue and currently playing song.")
async def queue_slash_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    guild_identifier = interaction.guild_id
    queue_list_ref = music_queues.get(guild_identifier, [])
    currently_playing_ref = current_playing_songs.get(guild_identifier)

    if not currently_playing_ref and not queue_list_ref:
        return await interaction.followup.send("📜 The music queue is completely empty right now.")

    embed_message = discord.Embed(title="🎵 Current Music Queue", color=discord.Color.blurple())
    if currently_playing_ref:
        embed_message.add_field(name="Now Playing", value=currently_playing_ref['title'], inline=False)

    if queue_list_ref:
        formatted_queue_items = "\n".join([f"**{index + 1}.** {track_item['title']}" for index, track_item in enumerate(queue_list_ref[:10])])
        if len(queue_list_ref) > 10:
            formatted_queue_items += f"\n*...and {len(queue_list_ref) - 10} more song(s) in queue*"
        embed_message.add_field(name="Up Next", value=formatted_queue_items, inline=False)

    await interaction.followup.send(embed=embed_message)

@bot.tree.command(name="loop", description="Configure the repeat/loop mode for the music queue.")
@app_commands.choices(mode=[
    app_commands.Choice(name="Off", value="off"),
    app_commands.Choice(name="Single Song", value="single"),
    app_commands.Choice(name="Entire Queue", value="queue")
])
async def loop_slash_command(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    guild_loop_modes[interaction.guild_id] = mode.value
    await interaction.response.send_message(f"🔁 Repeat mode has been updated to: **{mode.name}**")
    # =====================================================================
# FIH BOT - PART 3: ECONOMY, MODERATION, AND LIFECYCLE EVENTS
# =====================================================================

# Economy Helper Functions
def fetch_user_balance(user_identifier: int) -> int:
    return economy_database["users"].get(str(user_identifier), 1000)

def update_user_balance(user_identifier: int, updated_amount: int):
    economy_database["users"][str(user_identifier)] = updated_amount

@bot.tree.command(name="balance", description="Check your current Fihcoin balance.")
async def balance_slash_command(interaction: discord.Interaction):
    user_balance_value = fetch_user_balance(interaction.user.id)
    await interaction.response.send_message(f"💰 Your current balance is: **{user_balance_value:,} Fihcoins**.")

@bot.tree.command(name="coinflip", description="Flip a coin and gamble your Fihcoins.")
@app_commands.choices(choice=[
    app_commands.Choice(name="Heads", value="heads"),
    app_commands.Choice(name="Tails", value="tails")
])
async def coinflip_slash_command(interaction: discord.Interaction, choice: app_commands.Choice[str], bet: int):
    if bet <= 0:
        return await interaction.response.send_message("❌ The bet amount must be greater than zero!", ephemeral=True)

    user_identifier = interaction.user.id
    current_balance = fetch_user_balance(user_identifier)

    if bet > current_balance:
        return await interaction.response.send_message(f"❌ Insufficient balance! You have **{current_balance:,} Fihcoins**.", ephemeral=True)

    flip_outcome = random.choice(["heads", "tails"])
    if choice.value == flip_outcome:
        new_balance = current_balance + bet
        update_user_balance(user_identifier, new_balance)
        await interaction.response.send_message(f"🪙 Result: **{flip_outcome.upper()}**! You won **{bet:,} Fihcoins**! 🎉 Your new balance is **{new_balance:,} Fihcoins**.")
    else:
        new_balance = current_balance - bet
        update_user_balance(user_identifier, new_balance)
        await interaction.response.send_message(f"🪙 Result: **{flip_outcome.upper()}**! You lost **{bet:,} Fihcoins**. 😢 Your new balance is **{new_balance:,} Fihcoins**.")

@bot.tree.command(name="set_balance", description="Modify a user's Fihcoin balance (Bot Owner only).")
@app_commands.describe(user="The target user", amount="The new balance amount")
async def set_balance_slash_command(interaction: discord.Interaction, user: discord.User, amount: int):
    if str(interaction.user.id) != OWNER_ID:
        return await interaction.response.send_message("❌ Only the designated bot owner can execute this command!", ephemeral=True)

    if amount < 0:
        return await interaction.response.send_message("❌ The balance amount cannot be a negative number!", ephemeral=True)

    update_user_balance(user.id, amount)
    await interaction.response.send_message(f"✅ Successfully updated {user.mention}'s balance to **{amount:,} Fihcoins**.")

# =====================================================================
# DISCORD SLASH COMMANDS: MODERATION MODULE
# =====================================================================
@bot.tree.command(name="clear", description="Bulk delete messages in the current text channel.")
@app_commands.describe(amount="The number of messages to delete (between 1 and 100)")
async def clear_slash_command(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message("❌ You lack the `Manage Messages` permission required for this command!", ephemeral=True)

    if amount < 1 or amount > 100:
        return await interaction.response.send_message("❌ Please specify a message count between 1 and 100.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    deleted_messages_list = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 Successfully deleted **{len(deleted_messages_list)}** messages from this channel.", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a specific member from the server.")
@app_commands.describe(member="The member to kick", reason="The reason for kicking the member")
async def kick_slash_command(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        return await interaction.response.send_message("❌ You lack the `Kick Members` permission required for this command!", ephemeral=True)

    try:
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 Successfully kicked **{member.name}** from the server. Reason: {reason}")
    except Exception as kick_error:
        await interaction.response.send_message(f"❌ Failed to kick the member due to an error: {kick_error}", ephemeral=True)

@bot.tree.command(name="ban", description="Ban a specific member from the server.")
@app_commands.describe(member="The member to ban", reason="The reason for banning the member")
async def ban_slash_command(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("❌ You lack the `Ban Members` permission required for this command!", ephemeral=True)

    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"🔨 Successfully banned **{member.name}** from the server. Reason: {reason}")
    except Exception as ban_error:
        await interaction.response.send_message(f"❌ Failed to ban the member due to an error: {ban_error}", ephemeral=True)

# =====================================================================
# BOT LIFECYCLE EVENTS & LAUNCH ROUTINE
# =====================================================================
@bot.event
async def on_ready():
    print(f"Logged into Discord successfully as {bot.user.name} (ID: {bot.user.id})")
    try:
        synced_commands_list = await bot.tree.sync()
        print(f"Successfully synced {len(synced_commands_list)} application command(s) globally.")
    except Exception as sync_error:
        print(f"Failed to synchronize application commands: {sync_error}")

if __name__ == "__main__":
    keep_alive()
    bot.run(BOT_TOKEN)
