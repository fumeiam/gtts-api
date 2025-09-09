import discord
from discord.ext import commands
from fastapi import FastAPI, Request
import uvicorn
import asyncio
import os
import uuid
import aiohttp
from yt_dlp import YoutubeDL

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

# --------------------
# TTS CONFIG
# --------------------
TTS_API_SAY = "https://tts-bot-bo6n.onrender.com/say"
TTS_API_LEAVE = "https://tts-bot-bo6n.onrender.com/leave"
guild_defaults = {}  # {guild_id: {"voice": str, "volume": float}}

def get_guild_defaults(guild_id: int):
    if guild_id not in guild_defaults:
        guild_defaults[guild_id] = {"voice": "en", "volume": 1.0}
    return guild_defaults[guild_id]

# --------------------
# MUSIC CONFIG
# --------------------
guild_music_queues = {}     # guild_id -> list of track dicts
guild_autoplay_flags = {}   # guild_id -> bool
inactivity_tasks = {}       # guild_id -> asyncio.Task

# PATCHED: add cookies.txt to options
YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "extract_flat": "in_playlist",
    "default_search": "ytsearch",
    "cookiefile": "cookies.txt",  # <--- use your exported cookies here
}

# PATCH: add ffmpeg opts + resolver
FFMPEG_OPTIONS = "-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

def resolve_audio_url(query: str):
    try:
        with YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            return info.get("url")
    except Exception as e:
        print(f"yt-dlp resolve failed: {e}")
        return None

# --------------------
# HELPER FUNCTIONS
# --------------------
async def play_next(guild_id: int):
    queue = guild_music_queues.get(guild_id, [])
    if not queue:
        # Autoplay random if flag is set
        if guild_autoplay_flags.get(guild_id, False):
            import random
            query = random.choice(["lofi beats", "chill music", "game music", "relaxing music"])
            await play_track(guild_id, None, query, autoplay=True)
        return

    track = queue.pop(0)
    guild_music_queues[guild_id] = queue

    guild = bot.get_guild(guild_id)
    if not guild:
        return
    vc_channel = guild.get_channel(track["vc_id"])
    if not vc_channel:
        return
    vc = guild.voice_client
    if not vc or not vc.is_connected():
        vc = await vc_channel.connect()

    loop = asyncio.get_event_loop()

    try:
        raw = track.get("url") or track.get("query")
        if not raw:
            print("No URL or query found, skipping…")
            await play_next(guild_id)
            return

        stream_url = resolve_audio_url(raw)
        if not stream_url:
            print("Failed to resolve URL, skipping…")
            await play_next(guild_id)
            return

        ffmpeg_source = discord.FFmpegPCMAudio(stream_url, options=FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(ffmpeg_source)
        source.volume = track.get("volume", 1.0)
        vc.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), loop))
    except Exception as e:
        print(f"Failed to play track: {e}")
        await play_next(guild_id)

async def play_track(guild_id: int, vc_id: int, query_or_url: str = None, autoplay=False, volume=1.0):
    if guild_id not in guild_music_queues:
        guild_music_queues[guild_id] = []
    track = {"vc_id": vc_id, "volume": volume}
    if query_or_url:
        if query_or_url.startswith("http"):
            track["url"] = query_or_url
        else:
            track["query"] = query_or_url
    guild_music_queues[guild_id].append(track)
    guild_autoplay_flags[guild_id] = autoplay
    guild = bot.get_guild(guild_id)
    if guild and (not guild.voice_client or not guild.voice_client.is_playing()):
        await play_next(guild_id)

# --------------------
# AUTO DISCONNECT
# --------------------
async def auto_disconnect(guild_id: int):
    try:
        await asyncio.sleep(600)  # 10 min
        guild = bot.get_guild(guild_id)
        if guild and guild.voice_client and guild.voice_client.is_connected():
            await guild.voice_client.disconnect()
    except asyncio.CancelledError:
        pass

# --------------------
# TTS ENDPOINTS
# --------------------
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "TTS bot is alive!"}

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

    filename = f"tts_{uuid.uuid4()}.mp3"
    from gtts import gTTS
    tts = gTTS(text=text, lang=voice)
    tts.save(filename)

    vc = guild.voice_client
    if not vc or not vc.is_connected():
        vc = await vc_channel.connect()

    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(filename))
    source.volume = volume
    vc.play(source)

    if guild_id in inactivity_tasks:
        inactivity_tasks[guild_id].cancel()
    inactivity_tasks[guild_id] = asyncio.create_task(auto_disconnect(guild_id))

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

    if guild_id in inactivity_tasks:
        inactivity_tasks[guild_id].cancel()
        del inactivity_tasks[guild_id]

    return {"status": "disconnected"}

# --------------------
# MUSIC ENDPOINTS
# --------------------
@app.post("/play")
async def music_play(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc_id = data.get("vc_id")
    url = data.get("url")
    query = data.get("query")
    autoplay = bool(data.get("autoplay", False))
    volume = float(data.get("volume", 1.0))

    if not vc_id:
        guild = bot.get_guild(guild_id)
        if guild:
            for channel in guild.voice_channels:
                if channel.members:
                    vc_id = channel.id
                    break
        if not vc_id:
            return {"error": "No vc_id provided and no active voice channel found."}

    await play_track(guild_id, int(vc_id), url or query, autoplay, volume)
    return {"status": "queued"}

@app.post("/skip")
async def music_skip(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc = bot.get_guild(guild_id).voice_client
    if vc and vc.is_playing():
        vc.stop()
    return {"status": "skipped"}

@app.post("/stop")
async def music_stop(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc = bot.get_guild(guild_id).voice_client
    if vc:
        vc.stop()
        await vc.disconnect()
    guild_music_queues[guild_id] = []
    return {"status": "stopped"}

@app.post("/pause")
async def music_pause(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc = bot.get_guild(guild_id).voice_client
    if vc and vc.is_playing():
        vc.pause()
    return {"status": "paused"}

@app.post("/resume")
async def music_resume(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    vc = bot.get_guild(guild_id).voice_client
    if vc and vc.is_paused():
        vc.resume()
    return {"status": "resumed"}

@app.post("/volume")
async def music_volume(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    volume = float(data.get("volume", 1.0))
    vc = bot.get_guild(guild_id).voice_client
    if vc and vc.source:
        vc.source.volume = volume
    return {"status": "volume set", "value": volume}

@app.post("/queue")
async def music_queue(request: Request):
    data = await request.json()
    guild_id = int(data["guild_id"])
    queue = guild_music_queues.get(guild_id, [])
    now_playing = None
    vc = bot.get_guild(guild_id).voice_client
    if vc and vc.is_playing():
        now_playing = "Currently playing"
    track_list = [t.get("url") or t.get("query") for t in queue]
    return {"now_playing": now_playing, "queue": track_list}

# --------------------
# RUN BOT & API
# --------------------
async def start_fastapi():
    PORT = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT, loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(
        bot.start(TOKEN),
        start_fastapi()
    )

if __name__ == "__main__":
    asyncio.run(main())
