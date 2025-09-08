import discord
from discord.ext import commands
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from gtts import gTTS
import os
import uuid

TOKEN = "YOUR_TTS_BOT_TOKEN"

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

@app.post("/say")
async def say(request: Request):
    data = await request.json()
    guild_id = data["guild_id"]
    vc_id = data["vc_id"]
    text = data["text"]
    voice = data.get("voice", "en")
    volume = float(data.get("volume", 1.0))

    guild = bot.get_guild(int(guild_id))
    vc_channel = guild.get_channel(int(vc_id))

    if not guild or not vc_channel:
        return {"error": "Guild or VC not found"}

    # Generate unique audio file
    filename = f"tts_{uuid.uuid4()}.mp3"
    tts = gTTS(text=text, lang=voice)
    tts.save(filename)

    # Play in VC
    vc = await vc_channel.connect()
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(filename))
    source.volume = volume
    vc.play(source)

    while vc.is_playing():
        await asyncio.sleep(1)
    await vc.disconnect()

    os.remove(filename)
    return {"status": "played", "voice": voice, "volume": volume}

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
