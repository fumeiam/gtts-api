import discord
from discord.ext import commands
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from gtts import gTTS
import os
import uuid

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

# Track inactivity timers per guild
inactivity_tasks = {}

@app.post("/say")
async def say(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc_id = int(data["vc_id"])
    text = data["text"]
    voice = data.get("voice", "en")
    volume = float(data.get("volume", 1.0))

    guild = bot.get_guild(guild_id)
    vc_channel = guild.get_channel(vc_id) if guild else None

    if not guild or not vc_channel:
        return {"error": "Guild or VC not found"}

    # Generate unique audio file
    filename = f"tts_{uuid.uuid4()}.mp3"
    tts = gTTS(text=text, lang=voice)
    tts.save(filename)

    # Connect if not already connected
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        vc = await vc_channel.connect()

    # Play in VC
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(filename))
    source.volume = volume
    vc.play(source)

    # Reset inactivity timer
    if guild_id in inactivity_tasks:
        inactivity_tasks[guild_id].cancel()
    inactivity_tasks[guild_id] = asyncio.create_task(auto_disconnect(guild_id))

    # Wait until finished
    while vc.is_playing():
        await asyncio.sleep(1)

    os.remove(filename)
    return {"status": "played", "voice": voice, "volume": volume}


@app.post("/leave")
async def leave(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])

    guild = bot.get_guild(guild_id)
    if not guild or not guild.voice_client:
        return {"error": "Bot is not in a VC"}

    vc = guild.voice_client
    await vc.disconnect()

    # Cancel inactivity timer if active
    if guild_id in inactivity_tasks:
        inactivity_tasks[guild_id].cancel()
        del inactivity_tasks[guild_id]

    return {"status": "disconnected"}


async def auto_disconnect(guild_id: int):
    """Disconnect after 10 minutes of inactivity"""
    try:
        await asyncio.sleep(600)  # 10 minutes
        guild = bot.get_guild(guild_id)
        if guild and guild.voice_client and guild.voice_client.is_connected():
            await guild.voice_client.disconnect()
    except asyncio.CancelledError:
        pass


async def start_fastapi():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await asyncio.gather(
        bot.start(TOKEN),
        start_fastapi()
    )

if __name__ == "__main__":
    asyncio.run(main())

