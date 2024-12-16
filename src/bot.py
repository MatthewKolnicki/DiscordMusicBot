import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import config
import random
from lyrics_extractor import SongLyrics

# Configure yt-dlp
YTDLP_OPTIONS = {
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
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -bufsize 64k'
}

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.music_queues = {}  # Dictionary to store queues for each guild
        
    async def setup_hook(self):
        print("Syncing commands...")
        await self.tree.sync()
        print("Commands synced!")
        
    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')

bot = MusicBot()

def is_dj(interaction: discord.Interaction) -> bool:
    dj_role = discord.utils.get(interaction.guild.roles, name="DJ")
    return dj_role in interaction.user.roles or interaction.user.guild_permissions.administrator

def dj_only():
    async def predicate(interaction: discord.Interaction):
        if not is_dj(interaction):
            await interaction.response.send_message("This command requires the DJ role!", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

@bot.tree.command(name="play", description="Play a song from YouTube")
async def play(interaction: discord.Interaction, query: str):
    # Check if user is in a voice channel
    if not interaction.user.voice:
        await interaction.response.send_message("You need to be in a voice channel to play music!")
        return

    await interaction.response.defer()

    try:
        voice_channel = interaction.user.voice.channel
        
        # Initialize queue for this guild if it doesn't exist
        guild_id = interaction.guild_id
        if guild_id not in bot.music_queues:
            bot.music_queues[guild_id] = []
            
        with yt_dlp.YoutubeDL(YTDLP_OPTIONS) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            song_info = {
                'url': info['url'],
                'title': info['title']
            }
            
            if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
                # Play immediately if nothing is playing
                await play_song(interaction, song_info)
            else:
                # Add to queue if something is already playing
                bot.music_queues[guild_id].append(song_info)
                await interaction.followup.send(f"Added to queue: {song_info['title']}")
                
    except Exception as e:
        print(f"Error: {str(e)}")
        await interaction.followup.send("An error occurred while trying to play the song.")

async def play_song(interaction, song_info):
    try:
        voice_client = interaction.guild.voice_client
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()
        elif voice_client.channel != interaction.user.voice.channel:
            await voice_client.move_to(interaction.user.voice.channel)

        # Clear any existing audio
        if voice_client.is_playing():
            voice_client.stop()

        audio_source = discord.FFmpegPCMAudio(song_info['url'], **FFMPEG_OPTIONS)
        
        def after_playing(error):
            if error:
                print(f"Error after playing: {error}")
                asyncio.run_coroutine_threadsafe(
                    interaction.channel.send("An error occurred while playing the song."), 
                    bot.loop
                )
            else:
                # Play next song in queue
                asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
                
        voice_client.play(audio_source, after=after_playing)
        voice_client.current_song = song_info
        await interaction.followup.send(f"Now playing: {song_info['title']}")
        
    except Exception as e:
        print(f"Error in play_song: {str(e)}")
        await interaction.followup.send("An error occurred while trying to play the song.")
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

async def play_next(interaction):
    guild_id = interaction.guild_id
    if guild_id in bot.music_queues and bot.music_queues[guild_id]:
        next_song = bot.music_queues[guild_id].pop(0)
        await play_song(interaction, next_song)

@bot.tree.command(name="stop", description="Stop the current song")
async def stop(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("I'm not playing anything!")
        return

    interaction.guild.voice_client.stop()
    await interaction.response.send_message("Stopped playing!")

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("I'm not in a voice channel!")
        return

    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("Left the voice channel!")

@bot.tree.command(name="queue", description="Show the current music queue")
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id not in bot.music_queues or not bot.music_queues[guild_id]:
        await interaction.response.send_message("The queue is empty!")
        return
        
    queue_list = "\n".join(f"{i+1}. {song['title']}" 
                          for i, song in enumerate(bot.music_queues[guild_id]))
    await interaction.response.send_message(f"Current Queue:\n{queue_list}")

@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
        await interaction.response.send_message("Nothing is playing!")
        return
        
    interaction.guild.voice_client.stop()  # This will trigger the after callback to play next song
    await interaction.response.send_message("Skipped the current song!")

@bot.tree.command(name="pause", description="Pause the current song")
async def pause(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("Nothing is playing!")
        return
        
    if interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("Paused the music!")
    else:
        await interaction.response.send_message("Nothing is playing!")

@bot.tree.command(name="resume", description="Resume the paused song")
async def resume(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message("Nothing is paused!")
        return
        
    if interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("Resumed the music!")
    else:
        await interaction.response.send_message("Nothing is paused!")

@bot.tree.command(name="volume", description="Set the volume (0-100)")
async def volume(interaction: discord.Interaction, volume: int):
    if not 0 <= volume <= 100:
        await interaction.response.send_message("Volume must be between 0 and 100!")
        return
        
    if not interaction.guild.voice_client:
        await interaction.response.send_message("Not connected to a voice channel!")
        return
        
    # Volume is a float between 0 and 1
    interaction.guild.voice_client.source.volume = volume / 100
    await interaction.response.send_message(f"Volume set to {volume}%")

@bot.tree.command(name="nowplaying", description="Show the currently playing song")
async def nowplaying(interaction: discord.Interaction):
    if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
        await interaction.response.send_message("Nothing is playing!")
        return
        
    # Assuming we store the current song info somewhere
    current_song = interaction.guild.voice_client.current_song  # You'll need to implement this
    await interaction.response.send_message(f"Now playing: {current_song['title']}")

@bot.tree.command(name="loop", description="Toggle loop mode")
async def loop(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if not hasattr(bot, 'loop_mode'):
        bot.loop_mode = {}
    
    bot.loop_mode[guild_id] = not bot.loop_mode.get(guild_id, False)
    status = "enabled" if bot.loop_mode[guild_id] else "disabled"
    await interaction.response.send_message(f"Loop mode {status}")

@bot.tree.command(name="shuffle", description="Shuffle the current queue")
async def shuffle(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id not in bot.music_queues or not bot.music_queues[guild_id]:
        await interaction.response.send_message("Nothing to shuffle!")
        return
        
    random.shuffle(bot.music_queues[guild_id])
    await interaction.response.send_message("Queue has been shuffled!")

@bot.tree.command(name="playlist", description="Play a YouTube playlist")
async def playlist(interaction: discord.Interaction, url: str):
    if not interaction.user.voice:
        await interaction.response.send_message("You need to be in a voice channel!")
        return

    await interaction.response.defer()

    try:
        # Modify YTDLP_OPTIONS to allow playlists
        playlist_opts = YTDLP_OPTIONS.copy()
        playlist_opts['noplaylist'] = False
        
        with yt_dlp.YoutubeDL(playlist_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                # It's a playlist
                songs = [{
                    'url': entry['url'],
                    'title': entry['title']
                } for entry in info['entries']]
                
                guild_id = interaction.guild_id
                if guild_id not in bot.music_queues:
                    bot.music_queues[guild_id] = []
                
                bot.music_queues[guild_id].extend(songs)
                await interaction.followup.send(f"Added {len(songs)} songs to the queue!")
                
                if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
                    await play_song(interaction, bot.music_queues[guild_id][0])
    except Exception as e:
        await interaction.followup.send(f"Error loading playlist: {str(e)}")

@bot.tree.command(name="lyrics", description="Show lyrics for the current song")
async def lyrics(interaction: discord.Interaction):
    if not interaction.guild.voice_client or not hasattr(interaction.guild.voice_client, 'current_song'):
        await interaction.response.send_message("No song is currently playing!")
        return
        
    song_title = interaction.guild.voice_client.current_song['title']
    
    try:
        # You'll need Google Custom Search API credentials
        GCS_API_KEY = "your_api_key"
        GCS_ENGINE_ID = "your_engine_id"
        
        extract_lyrics = SongLyrics(GCS_API_KEY, GCS_ENGINE_ID)
        data = extract_lyrics.get_lyrics(song_title)
        
        # Split lyrics into chunks if too long
        lyrics = data['lyrics']
        if len(lyrics) > 2000:
            chunks = [lyrics[i:i+2000] for i in range(0, len(lyrics), 2000)]
            for chunk in chunks:
                await interaction.followup.send(chunk)
        else:
            await interaction.response.send_message(lyrics)
    except Exception as e:
        await interaction.response.send_message(f"Couldn't find lyrics: {str(e)}")

@bot.tree.command(name="clear", description="Clear the music queue")
@dj_only()
async def clear(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id in bot.music_queues:
        bot.music_queues[guild_id].clear()
    await interaction.response.send_message("Queue cleared!")

@bot.tree.command(name="filter", description="Apply an audio filter")
async def filter(interaction: discord.Interaction, filter_type: str):
    if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
        await interaction.response.send_message("Nothing is playing!")
        return
        
    filters = {
        'bass': 'bass=g=20',
        'treble': 'treble=g=5',
        'nightcore': 'asetrate=48000*1.25,aresample=48000',
        'vaporwave': 'asetrate=48000*0.8,aresample=48000',
        'echo': 'aecho=0.8:0.9:1000:0.3',
        'clear': ''  # No filter
    }
    
    if filter_type not in filters:
        await interaction.response.send_message(f"Available filters: {', '.join(filters.keys())}")
        return
        
    # Update FFMPEG_OPTIONS with the new filter
    FFMPEG_OPTIONS['options'] = f'-vn -af "{filters[filter_type]}"'
    
    # Restart the current song with the new filter
    current_song = interaction.guild.voice_client.current_song
    await play_song(interaction, current_song)
    
    await interaction.response.send_message(f"Applied {filter_type} filter!")

bot.run(config.TOKEN) 