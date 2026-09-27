# =====================================================================
# FIH BOT - PART 1: SETUP AND STARTUP
# =====================================================================
import os
import asyncio
from threading import Thread

import discord
from discord.ext import commands
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is not set! "
        "Create a .env file in the project root and add a BOT_TOKEN=... line."
    )

# =====================================================================
# FLASK KEEP-ALIVE SERVER (for hosts like Render / Replit)
# =====================================================================
app = Flask(__name__)


@app.route("/")
def home():
    return "Fih Bot is running!"


def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))


def keep_alive():
    Thread(target=run_flask, daemon=True).start()


# =====================================================================
# DISCORD BOT SETUP
# =====================================================================
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
intents.members = True
# NOTE: message_content intent removed since nothing reads raw message
# content anywhere (only slash commands are used). You don't need to
# enable "Message Content Intent" in the Discord Developer Portal.

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    # Without this, an unexpected error inside a command left the user
    # stuck on "Bot is thinking..." forever.
    print(f"Slash command error ({interaction.command}): {error}")
    message = "❌ Something went wrong while running that command."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        pass


async def load_cogs():
    await bot.load_extension("cogs.music")
    await bot.load_extension("cogs.economy_moderation")
    await bot.load_extension("cogs.extra")


async def main():
    keep_alive()
    async with bot:
        await load_cogs()
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
