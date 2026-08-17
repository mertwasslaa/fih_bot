# =====================================================================
# FIH BOT - PART 3: ECONOMY AND MODERATION
# =====================================================================
import json
import os
import random

import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "economy.json")

# Fallback owner ID, used only if OWNER_ID isn't set in .env
DEFAULT_OWNER_ID = "1468988203376578728"


def load_economy() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Could not read economy.json, starting fresh: {e}")
    return {"users": {}}


def save_economy(data: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Could not save economy.json: {e}")


class EconomyModeration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.owner_id = os.getenv("OWNER_ID", DEFAULT_OWNER_ID)
        # Balances are persisted to economy.json so they survive restarts
        # (they used to reset to the default 1000 every time the bot restarted).
        self.economy = load_economy()

    def is_owner(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.owner_id

    def get_balance(self, user_id: int) -> int:
        return self.economy["users"].get(str(user_id), 1000)

    def set_balance(self, user_id: int, amount: int):
        self.economy["users"][str(user_id)] = amount
        save_economy(self.economy)

    # ---------- ECONOMY ----------
    @app_commands.command(name="balance", description="Check your fihcoin balance.")
    async def balance(self, interaction: discord.Interaction):
        bal = self.get_balance(interaction.user.id)
        await interaction.response.send_message(f"💰 Your balance: **{bal:,} fihcoin**.")

    @app_commands.command(name="coinflip", description="Flip a coin and gamble your fihcoin.")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Heads", value="heads"),
            app_commands.Choice(name="Tails", value="tails"),
        ]
    )
    async def coinflip(self, interaction: discord.Interaction, choice: app_commands.Choice[str], bet: int):
        if bet <= 0:
            return await interaction.response.send_message(
                "❌ The bet has to be greater than zero!", ephemeral=True
            )

        user_id = interaction.user.id
        balance = self.get_balance(user_id)

        if bet > balance:
            return await interaction.response.send_message(
                f"❌ Not enough balance! You have **{balance:,} fihcoin**.", ephemeral=True
            )

        result = random.choice(["heads", "tails"])
        if choice.value == result:
            new_balance = balance + bet
            self.set_balance(user_id, new_balance)
            await interaction.response.send_message(
                f"🪙 Result: **{result.upper()}**! You won **{bet:,} fihcoin**! 🎉 "
                f"New balance: **{new_balance:,} fihcoin**."
            )
        else:
            new_balance = balance - bet
            self.set_balance(user_id, new_balance)
            await interaction.response.send_message(
                f"🪙 Result: **{result.upper()}**! You lost **{bet:,} fihcoin**. 😢 "
                f"New balance: **{new_balance:,} fihcoin**."
            )

    # Owner-only. Hidden from everyone else by default (default_member_permissions=none) —
    # see the README note about granting yourself access via Server Settings > Integrations.
    @app_commands.command(name="set_balance", description="Set a user's fihcoin balance. (Owner only)")
    @app_commands.describe(user="Target user", amount="New balance amount")
    @app_commands.default_permissions(administrator=True)
    async def set_balance_cmd(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )

        if amount < 0:
            return await interaction.response.send_message("❌ Balance can't be negative!", ephemeral=True)

        self.set_balance(user.id, amount)
        await interaction.response.send_message(
            f"✅ Set {user.mention}'s balance to **{amount:,} fihcoin**.", ephemeral=True
        )

    # ---------- MODERATION (owner only, hidden by default) ----------
    @app_commands.command(name="clear", description="Bulk delete messages in this channel. (Owner only)")
    @app_commands.describe(amount="Number of messages to delete (1-100)")
    @app_commands.default_permissions(administrator=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )

        if amount < 1 or amount > 100:
            return await interaction.response.send_message(
                "❌ Pick a number between 1 and 100.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** message(s).", ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server. (Owner only)")
    @app_commands.describe(member="Member to kick", reason="Reason")
    @app_commands.default_permissions(administrator=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )
        try:
            await member.kick(reason=reason)
            await interaction.response.send_message(
                f"👢 Kicked **{member.name}**. Reason: {reason}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to kick: {e}", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a member from the server. (Owner only)")
    @app_commands.describe(member="Member to ban", reason="Reason")
    @app_commands.default_permissions(administrator=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )
        try:
            await member.ban(reason=reason)
            await interaction.response.send_message(
                f"🔨 Banned **{member.name}**. Reason: {reason}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to ban: {e}", ephemeral=True)

    @app_commands.command(name="move", description="Move a member from one voice channel to another. (Owner only)")
    @app_commands.describe(member="Member to move", channel="Destination voice channel")
    @app_commands.default_permissions(administrator=True)
    async def move(self, interaction: discord.Interaction, member: discord.Member, channel: discord.VoiceChannel):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )
        if not member.voice or not member.voice.channel:
            return await interaction.response.send_message(
                f"❌ {member.name} isn't in a voice channel.", ephemeral=True
            )
        try:
            await member.move_to(channel)
            await interaction.response.send_message(
                f"🔀 Moved **{member.name}** to **{channel.name}**.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to move: {e}", ephemeral=True)

    @app_commands.command(name="voicemap", description="See who is in each voice channel. (Owner only, private)")
    @app_commands.default_permissions(administrator=True)
    async def voicemap(self, interaction: discord.Interaction):
        if not self.is_owner(interaction):
            return await interaction.response.send_message(
                "❌ Only the bot owner can use this command!", ephemeral=True
            )

        guild = interaction.guild
        voice_channels = [c for c in guild.channels if isinstance(c, discord.VoiceChannel)]

        if not voice_channels:
            return await interaction.response.send_message(
                "📭 This server has no voice channels.", ephemeral=True
            )

        embed = discord.Embed(title="🔊 Voice Channel Overview", color=discord.Color.blurple())
        any_members = False
        for vc in voice_channels:
            if vc.members:
                any_members = True
                names = "\n".join(f"• {m.display_name}" for m in vc.members)
                embed.add_field(name=vc.name, value=names, inline=False)

        if not any_members:
            embed.description = "No one is currently in a voice channel."

        # ephemeral=True is what actually makes this visible only to you,
        # no matter who ends up able to run the command.
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EconomyModeration(bot))
