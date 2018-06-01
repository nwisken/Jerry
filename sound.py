from threading import Lock, Thread
import time
from Jerry import Music

lock = Lock()

is_playing_sound = False
player = None

# plays sound requested by client
async def play_sound(message, client, sound, vol):
    lock.acquire()
    if Music.get_voice_state().voice is not None:
        await client.send_message(message.channel, "Another sound is playing.")
    elif message.author.voice_channel: # user in voice channel
        if not client.voice_client_in(message.server): # if bot not in any voice channel
            voice = await client.join_voice_channel(message.author.voice_channel)
        else: # move to user voice channel
            voice = client.voice_client_in(message.server)
            await voice.move_to(message.author.voice_channel)
        sound.player =  await voice.create_ffmpeg_player(sound)
        sound.player.volume = 0.2
        sound.player.start()
        duration = sound.player.duration
        time.sleep(duration)
    else: # user not in voice channel
        await client.send_message(message.channel, 'You\'re not in a voice channel!')
    lock.release()

# finds first youtube video for requested song by user
async def play_youtube(message, client):
    lock.acquire()
    if message.author.voice_channel: # if user in voice channel
        if not client.voice_client_in(message.server): # if bot not in any voice channel
            voice = await client.join_voice_channel(message.author.voice_channel)
        else: # bot not in correct voice chanel
            voice = client.voice_client_in(message.server)
            await voice.move_to(message.author.voice_channel)
        url = message.content.rsplit(None, 1)[1]
        try:
            player = await voice.create_ytdl_player(url)
            player.volume = 0.025
            player.start()
        except:
            await client.send_message(message.channel, "Could not open " + url)
    else: # user not in voice channel
        await client.send_message(message.channel, 'You\'re not in a voice channel!')
    lock.release()
