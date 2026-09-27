# =====================================================================
# FIH BOT - PART 5: AI CHAT (/ask)
# =====================================================================
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ask", description="Ask the AI a question.")
    @app_commands.describe(question="What do you want to ask?")
    async def ask(self, interaction: discord.Interaction, question: str):
        if not GROQ_API_KEY:
            return await interaction.response.send_message(
                "❌ AI isn't configured yet (missing GROQ_API_KEY).", ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "You are a helpful, concise Discord bot assistant."},
                {"role": "user", "content": question},
            ],
            "max_tokens": 600,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(GROQ_URL, headers=headers, json=payload, timeout=30) as resp:
                    data = await resp.json()
                    if resp.status != 200:
                        err = data.get("error", {}).get("message", "Unknown error")
                        return await interaction.followup.send(f"❌ AI error: {err}")
        except Exception as e:
            return await interaction.followup.send(f"❌ Request failed: {e}")

        answer = data["choices"][0]["message"]["content"].strip()

        # Discord messages cap at 2000 characters — split into chunks if the answer is long.
        if len(answer) <= 2000:
            await interaction.followup.send(answer)
        else:
            chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.channel.send(chunk)


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChat(bot))
