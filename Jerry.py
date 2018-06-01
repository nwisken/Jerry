import asyncio
import discord
from discord.ext import commands
import random
from betrayalplayer import BetrayalPlayer
from gtts import gTTS
import datetime
import pickle
import re
from threading import Lock, Thread

if not discord.opus.is_loaded():
    # the 'opus' library here is opus.dll on windows
    # or libopus.so on linux in the current directory
    # you should replace this with the location the
    # opus library is located in and with the proper filename.
    # note that on windows this DLL is automatically provided for you
    discord.opus.load_opus('opus')

"""
Represents message returned when song requested by user
Holds the requester of song, channel song will be played in and 
player used to play song
"""
class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '*{0.title}* requested by {1.display_name}'
        duration = self.player.duration
        if duration:  # if duration longer then 0, return length of song
            fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
        return fmt.format(self.player, self.requester)

# Represents state of robot used when song is playing
class VoiceState:
    def __init__(self, bot):
        self.current = None  # songs currently in list
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())

    # checks is bot is currently playing song
    def is_playing(self):
        if self.voice is None or self.current is None:
            return False
        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    # When new song changes, send message about next song and play next song in queue
    # waits until songs are finished
    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            await self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))
            self.current.player.start()
            await self.play_next_song.wait()

    @player.setter
    def player(self, value):
        self._player = value


# Voice related commands. Works in multiple servers at once.
class Music:

    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    # Returns state. Creates state if there is none in server currently.
    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state
        return state

    # creates a voice client for the state. Joins channel of user who summoned robot
    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    # Used for cleanup to close everything before unloading.
    # Closes playing songs and disconnects bot
    def __unload(self):
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass


    # Connects bot to voice channel of user who wrote message to call bot
    # Also handles if user was not in a voice channel
    @commands.command(pass_context=True, no_pm=True)
    async def summon(self, ctx):
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.say('You are not in a voice channel.')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:  # if currently in no voice channel
            state.voice = await self.bot.join_voice_channel(summoned_channel)
        else:
            await state.voice.move_to(summoned_channel)  # move to new voice channel
        return True

    """
    Plays song request by user. user types !play followed by the song they want to play. 
    If there is a song currently in the queue, then it is queued until the next song is done playing.
    This command automatically searches as well from YouTube. The list of supported sites can be found here:
    https://rg3.github.io/youtube-dl/supportedsites.html
    """
    @commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, song: str):

        # gets state to play on and sets parameters for player of music
        state = self.get_voice_state(ctx.message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        # tries join voice channel if not currently not in one, returns if not successful
        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        try:  # creates player to find and play song on youtube
            player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next,
                                                          before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5")
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        else:
            # sets volume and adds song to queue
            player.volume = 0.02
            entry = VoiceEntry(ctx.message, player)
            await self.bot.say('Queued ' + str(entry))
            await state.songs.put(entry)

    # Writes to chat volume of song if only !vol used, if number out after !vol sets volume to that value  "
    @commands.command(pass_context=True, no_pm=True)
    async def vol(self, ctx, *newvol):
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            if len(newvol) < 1:  # if only !vol typed
                await self.bot.say('Song volume is {:.0%}'.format(player.volume))
            else:
                try:
                    value = int(newvol[0])
                    player.volume = value / 100
                    await self.bot.say('Set the volume to {:.0%}'.format(player.volume))
                except:  # if value after !val was not a number
                    await self.bot.say("Enter a number after !vol to change the volume ")
        else:
            await self.bot.say("No song is currently playing")

    # Pauses the currently played song.
    @commands.command(pass_context=True, no_pm=True)
    async def pause(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    # Resumes the currently played song.
    @commands.command(pass_context=True, no_pm=True)
    async def resume(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    # Stops playing audio and leaves the voice channel.
    # This also clears the queue.
    @commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()
        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            await state.voice.disconnect()
        except:
            pass

    # skip current song to next song in queue stops is no next song
    @commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.say('Not playing any music right now...')
            return
        state.skip()
        await self.bot.say('Skipping song...')

    # show info on correctly playing song
    @commands.command(pass_context=True, no_pm=True)
    async def playing(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            await self.bot.say('Now playing {}'.format(state.current))

    # flips a random coin
    @commands.command(pass_context=True, no_pm=True)
    async def flip(self):
        flip = random.choice(['Heads', 'Tails'])
        await self.bot.say(flip)

    # Used to setup text for Betrayal at house on the hill
    @commands.command(pass_context=True, no_pm=True)
    async def betrayal(self, ctx, players: int):

        # Holds all the possible characters
        characters = (BetrayalPlayer("Madame Zostra", 4, 3, 4, 4), BetrayalPlayer("Vivian Lopez", 2, 4, 4, 5),
                      BetrayalPlayer("Darrin 'Flash' Williams", 3, 6, 3, 3), BetrayalPlayer("Ox Bellows", 5, 4, 3, 3),
                      BetrayalPlayer("Brandon Jaspers", 4, 4, 4, 3), BetrayalPlayer("Peter Akimoto", 3, 4, 4, 4),
                      BetrayalPlayer("Heather Granville", 3, 4, 3, 5), BetrayalPlayer("Jenny LeClerc", 4, 4, 4, 3),
                      BetrayalPlayer("Zoe Ingstrom", 3, 4, 5, 3), BetrayalPlayer("Missy Dubourde", 3, 5, 3, 4),
                      BetrayalPlayer("Professor Longfellow", 3, 4, 3, 5),
                      BetrayalPlayer("Father Rhinehardt", 2, 3, 6, 4))
        try:
            if players <= 0:  # if no number given
                await self.bot.say("Must end with number greater then 0")
                return
            elif players > 8:
                await self.bot.say("Must end with number below 9")
                return
        except ValueError:  # if non-number given
            await self.bot.say("Must end with number below 9")
            return
        final_statment = ""
        characters_chosen = []

        # checks character chosen so if it is a valid choice
        def character_check(inp):
            try:
                inp = int(inp.content)
                if inp in characters_chosen:
                    self.bot.say("Character has already been chosen")
                    return False
                if inp % 2 == 0:  # if even character number
                    if inp - 1 in characters_chosen:  # if characters same colour chosen
                        self.bot.say("Character with the same color has already been chosen")
                        return False
                    else:
                        characters_chosen.append(inp)
                        return inp
                elif inp % 2 == 1:  # if odd character number given
                    if inp + 1 in characters_chosen:  # if characters same colour chosen
                        self.bot.say("Character with the same color has already been chosen")
                        return False
                    else:
                        characters_chosen.append(inp)
                        return inp
                else:  # if number not a character number
                    self.bot.say("Incorrect number given")
                    return False
            except ValueError:  # not a integer number
                self.bot.say("Incorrect input given")
                return False

        characters_string = ""
        for j in range(0, len(characters)):  # for the number of players
            characters_string += characters[j].name + ": " + str(j + 1) + "\n"
        characters_string.strip()
        await self.bot.say(characters_string)
        for i in range(players):
            await self.bot.say("Enter character number for player " + str(i + 1))
            value = await bot.wait_for_message(timeout=15, check=character_check)
            if value is None:
                await self.bot.say("No value given. Exiting...")
                return
            value = int(value.content) - 1
            final_statment += "\n" + str(characters[value])
            final_statment += "\n"
            final_statment.strip()
            characters_chosen.append(value)
        await self.bot.say(final_statment)

    # Used to roll multiple values of dice"
    @commands.command(pass_context=True, no_pm=True)
    async def roll(self, ctx, value: str):

        rolls = limit = 0
        try:
            rolls, limit = map(int, value.split('d'))
            if rolls < 1 or limit < 1:
                return
        except (TypeError, IndexError, ValueError):
            await bot.say("Format has to be in NdN!")
        total = 0
        result = ""
        for r in range(rolls):
            rand = random.randint(1, limit)
            total += rand
            result += str(rand) + " + "
        result = result[: -2]
        if rolls > 1:
            result += " = " + str(total)
        await bot.say(result)

    # plays lucio soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def lucio(self, ctx):
        await play_sound(self, ctx, "Lúcio_-_Why_are_you_so_angry.ogg", 0.04)

    # plays omen soundclip"
    @commands.command(pass_context=True, no_pm=True)
    async def omen(self, ctx):
        await bot.say("It's a Omen!")
        await play_sound(self, ctx, "omen.mp3", 0.02)

    # plays dva soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def dva(self, ctx):
        await play_sound(self, ctx, "D.Va_Here_comes_a_new_challenger.ogg", 0.04)

    # plays tracer soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def tracer(self, ctx):
        await play_sound(self, ctx, "cavalry's here!.ogg", 0.04)

    # plays doomfist soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def doomfist(self, ctx):
        await play_sound(self, ctx, "Doomfist_-_Hello_there.ogg", 0.04)

    # plays obi soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def obi(self, ctx):
        await play_sound(self, ctx, "hello_there_obi.mp3", 0.1)

    # plays objection soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def objection(self, ctx):
        await play_sound(self, ctx, "objection.mp3", 0.04)

    # plays mei soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def mei(self, ctx):
        await play_sound(self, ctx, "Mei_-_A-Mei-Zing.mp3", 0.04)

    # plays hotel mario soundclip
    @commands.command(pass_context=True, no_pm=True)
    async def no(self, ctx):
        await play_sound(self, ctx, "Hotel Mario  No.mp3", 0.04)

    # Opens file and writes 3 random lines from file
    @commands.command(pass_context=True, no_pm=True)
    async def fmk(self, ctx, ):
        file_name = "fmk.txt"
        file = open(file_name, 'r')
        names = file.read().splitlines()
        chosen_names = random.sample(names, 3)
        await bot.say("{}, {} and {}".format(chosen_names[0], chosen_names[1], chosen_names[2]))
        file.close()

    # Opens file and writes 3 random lines from file"""
    @commands.command(pass_context=True, no_pm=True)
    async def fmkg(self, ctx, ):
        file_name = "fmk girl.txt"
        file = open(file_name, 'r')
        names = file.read().splitlines()
        chosen_names = random.sample(names, 3)
        await bot.say("{}, {} and {}".format(chosen_names[0], chosen_names[1], chosen_names[2]))
        file.close()

    # Opens file and writes 3 random lines from file
    @commands.command(pass_context=True, no_pm=True)
    async def fmkb(self, ctx, ):
        file_name = "fmk boy.txt"
        file = open(file_name, 'r')
        names = file.read().splitlines()
        chosen_names = random.sample(names, 3)
        await bot.say("{}, {} and {}".format(chosen_names[0], chosen_names[1], chosen_names[2]))
        file.close()

    # Opens file and writes 3 random lines from file
    @commands.command(pass_context=True, no_pm=True)
    async def fmkd(self, ctx, ):
        file_name = "fmkd"
        file = open(file_name, 'r')
        names = file.read().splitlines()
        chosen_names = random.sample(names, 3)
        await bot.say("{}, {} and {}".format(chosen_names[0], chosen_names[1], chosen_names[2]))
        file.close()

    # says the message sound in tts
    @commands.command(pass_context=True, no_pm=True)
    async def say(self, ctx, *, message: str):
        tts = gTTS(text=message, lang='en-uk')
        say_lock.acquire()
        try:
            tts.save("sound/say.mp3")
            await play_sound(self, ctx, "say.mp3", 0.1)
        finally:
            say_lock.release()

    # says the message sound in tts but slower
    @commands.command(pass_context=True, no_pm=True)
    async def slow(self, ctx, *, message: str):
        tts = gTTS(text=message, lang='en-uk', slow=True)
        say_lock.acquire()
        try:
            tts.save("sound/say.mp3")
            await play_sound(self, ctx, "say.mp3", 0.1)
        finally:
            say_lock.release()

    # Says the text in user message using the japanese tts
    @commands.command(pass_context=True, no_pm=True)
    async def jap(self, ctx, *, message: str):
        tts = gTTS(text=message, lang='ja')
        say_lock.acquire()
        try:
            tts.save("sound/say.mp3")
            await play_sound(self, ctx, "say.mp3", 0.1)
        finally:
            say_lock.release()

    # Cleans up channel by removing old bot messages
    @commands.command(pass_context=True, no_pm=True)
    async def cleanup(self, ctx):
        channel = ctx.message.channel
        try:
            deleted = await bot.purge_from(channel, limit=100, check=is_not_clean, after=datetime.datetime.now(
            ) - datetime.timedelta(days=13))
            await bot.send_message(channel, 'Deleted {} message(s)'.format(len(deleted)))
        except discord.HTTPException:
            await bot.say("You can't delete messages older then 14 days ")
        except discord.Forbidden:
            await bot.say("Need extra permissions to clean up")

    # used for getting or adding quotes of users saved
    @commands.command(pass_context=True, no_pm=True)
    async def quote(self, ctx):
        quote_name = "quotes"
        quote_file = open(quote_name, 'rb')
        quotes = pickle.load(quote_file)
        quote_file.close()

        try:
            quote_file = open(quote_name, "wb")
            message = ctx.message.content
            message = message.strip()
            message = re.sub(' +', ' ', message)  # removes all spaces to one
            message = message.split(" ")
            if len(message) == 1:  # if only !quote select random quote and return it
                user = random.choice(list(quotes))
                user_quotes = quotes[user]
                quote = random.choice(user_quotes)
                await say_quote(self, ctx, user, quote)
            elif len(message) == 2:  # if !quote then name of user
                user = message[1]
                if user.lower() not in quotes:  # if user not found
                    await bot.say("{} does not have any quotes".format(user.capitalize()))
                else:  # if user has quotes
                    user_quotes = quotes[user.lower()]
                    quote = random.choice(user_quotes)
                    await say_quote(self, ctx, user, quote)
            else:  # if !quote, name of user then quote
                user = message[1]
                quote = ""
                for i in range(2, len(message)):
                    quote += " " + message[i]
                quote = quote.strip()
                quote = quote[:1].upper() + quote[1:]
                if user.lower() not in quotes:  # if first quote for that user
                    quotes[user.lower()] = [quote]
                    await bot.say("There is now quotes for {}".format(user.capitalize()))
                else:  # if user had quotes before
                    quotes[user.lower()].append(quote)
                    await bot.say("Added quote for {}".format(user.capitalize()))
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        finally:
            pickle.dump(quotes, quote_file)
            quote_file.close()

    """
    Deletes quotes stored. If only name supplied after quoted, deletes all quotes stored that name has.
    if something given after name, everything after name is checked to see if that quote exists, 
    if it does delete only that quote from the user. 
    """
    @commands.command(pass_context=True, no_pm=True)
    async def quoted(self, ctx):
        quote_name = "quotes"
        quote_file = open(quote_name, 'rb')
        quotes = pickle.load(quote_file)
        quote_file.close()

        try:
            quote_file = open(quote_name, "wb")
            message = ctx.message.content
            message = message.strip()
            message = re.sub(' +', ' ', message)  # removes all spaces to one
            message = message.split(" ")
            if len(message) == 1:  # if only !quoted typed
                await bot.say("Please enter a name after to delete that name's quotes")
            elif len(message) == 2:  # if only quoted then name of user
                user = message[1]
                if user.lower() not in quotes:  # if name user has no quotes
                    await bot.say("{} does not have any quotes".format(user.capitalize()))
                else:  # delete all quotes for that user
                    quotes.pop(user.lower(), None)
                    await bot.say("Quotes for {} have been deleted".format(user.capitalize()))
            else:  # if user name given and specific quote
                user = message[1]
                quote = ""
                for i in range(2, len(message)):
                    quote += " " + message[i]
                quote = quote.strip()
                quote = quote[:1].upper() + quote[1:]
                if user.lower() not in quotes:  # if user does not have any quotes
                    await bot.say("{} does not have any quotes".format(user.capitalize()))
                else:
                    user_quotes = quotes[user.lower()]
                    if quote not in user_quotes:  # if user does not have specific quote in message
                        await bot.say("{} does not have that quote".format(user.capitalize()))
                    else:
                        quotes[user.lower()].remove(quote)
                        if len(user_quotes) == 0:
                            quotes.pop(user.lower(), None)
                            await bot.say("Quotes for {} have been deleted".format(user.capitalize()))
                        else:
                            await bot.say("Quote removed from {}".format(user.capitalize()))
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        finally:
            pickle.dump(quotes, quote_file)
            quote_file.close()

    # same as quote but tts reads quote
    @commands.command(pass_context=True, no_pm=True)
    async def quotes(self, ctx):
        quote_name = "quotes"
        quote_file = open(quote_name, 'rb')
        quotes = pickle.load(quote_file)
        quote_file.close()

        try:
            quote_file = open(quote_name, "wb")
            message = ctx.message.content
            message = message.strip()
            message = re.sub(' +', ' ', message)  # removes all spaces to one
            message = message.split(" ")
            if len(message) == 1:
                user = random.choice(list(quotes))
                user_quotes = quotes[user]
                quote = random.choice(user_quotes)
                await say_quote_sound(self, ctx, user, quote)
            elif len(message) == 2:
                user = message[1]
                if user.lower() not in quotes:
                    await bot.say("{} does not have any quotes".format(user.capitalize()))
                else:
                    user_quotes = quotes[user.lower()]
                    quote = random.choice(user_quotes)
                    await say_quote_sound(self, ctx, user, quote)
            else:
                user = message[1]
                quote = ""
                for i in range(2, len(message)):
                    quote += " " + message[i]
                quote = quote.strip()
                quote[:1].upper()
                if user.lower() not in quotes:
                    quotes[user.lower()] = [quote]
                    await bot.say("There is now quotes for {}".format(user.capitalize()))
                else:
                    quotes[user.lower()].append(quote)
                    await bot.say("Added quote for {}".format(user.capitalize()))
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        finally:
            pickle.dump(quotes, quote_file)
            quote_file.close()

    # Returns the number quotes stored for each person that has quotes
    @commands.command(pass_context=True, no_pm=True)
    async def qcheck(self):
        quote_name = "quotes"
        quote_file = open(quote_name, 'rb')
        quotes = pickle.load(quote_file)
        reply = ""
        for user in quotes:
            reply += "{}: {}\n".format(user.capitalize(), len(quotes[user]))
        await bot.say(reply)
        quote_file.close()

    # Returns all quotes stored with the user who said them
    @commands.command(pass_context=True, no_pm=True)
    async def qlist(self, ctx):
        quote_name = "quotes"
        quote_file = open(quote_name, 'rb')
        quotes = pickle.load(quote_file)
        try:
            message = ctx.message.content
            message = message.strip()
            message = re.sub(' +', ' ', message)  # removes all spaces to one
            message = message.split(" ")
            if len(message) == 1:
                reply = ""
                for user in quotes:
                    reply += "\n{}:\n".format(user.capitalize())
                    for quote in quotes[user.lower()]:
                        reply += "{}\n".format(quote)
                try:
                    await bot.say(reply)
                except discord.HTTPException:
                    n = 2000
                    replys = [reply[i:i + n] for i in range(0, len(reply), n)]
                    for reply in replys:
                        await bot.say(reply)
            elif len(message) == 2:
                user = message[1]
                if user.lower() not in quotes:
                    await bot.say("{} does not have any quotes".format(user.capitalize()))
                else:
                    user_quotes = quotes[user.lower()]
                    reply = "{}:\n".format(user.capitalize())
                    for quote in user_quotes:
                        reply += "{}\n".format(quote)
                    await bot.say(reply)
            else:
                await bot.say("Enter only a name after !qlist to see that person's quotes")
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        finally:
            quote_file.close()

    # removes all quotes stored
    @commands.command(pass_context=True, no_pm=True)
    async def resetpickle(self):
        quote_name = "quotes"
        quote_file = open(quote_name, 'wb')
        pickle.dump({}, quote_file)
        quote_file.close()


    # Used to mke bot write into chat
    @commands.command(pass_context=True, no_pm=True)
    async def jerry(self, ctx):
        message = ctx.message
        message_content = message.content.strip()
        split = message_content.split(" ", 1)
        if len(split) != 1:
            if ctx.message.author.name == "Voids forgotten":
                await bot.delete_message(message)
                await bot.say(split[1])

# decides which comments to remove when cleaning up
def is_not_clean(message):
    if message.author == bot.user:
        return True
    if message.content.startswith("!"):
        return True
    return False


# used to play any sounds in the sound folder when called
async def play_sound(self, ctx, sound, vol):
    state = self.get_voice_state(ctx.message.server)
    if state.voice is None:  # if in no voice channel
        success = await ctx.invoke(self.summon)
        if not success:
            return
    try:
        if VoiceState.is_playing(state):  # if currently playing music
            await self.bot.send_message(ctx.message.channel, "Can't play sounds while music is playing")
        else:
            player = state.voice.create_ffmpeg_player("sound/" + sound)
            player.volume = vol
            player.start()
    except Exception as e:
        fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
        await bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))

# writes quotes to chat
async def say_quote(self, ctx, name, quote):
    await self.bot.say("***'{}'*** *- {}*".format(quote, name.capitalize()))

# writes quote to chat and tts reads the quote
async def say_quote_sound(self, ctx, name, quote):
    await self.bot.say("***'{}'*** *- {}*".format(quote, name.capitalize()))
    quote = "{} said {}".format(name, quote)
    tts = gTTS(text=quote, lang='en-uk')
    say_lock.acquire()
    tts.save("sound/say.mp3")
    await play_sound(self, ctx, "say.mp3", 0.1)
    say_lock.release()

bot = commands.Bot(command_prefix=commands.when_mentioned_or('!'), description='A playlist example for discord.py')
bot.add_cog(Music(bot))

# logs details of bot on initialisation
@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

# welcomes new users to server when they join
@bot.event
async def on_member_join(member):
    server = member.server
    fmt = 'Welcome {0.mention} to {1.name}!'
    await bot.send_message(server, fmt.format(member, server))

say_lock = Lock()
bot.run('MzQ4NzUwMTU3MDY5NjgwNjQw.DHrenA.MNpQVhJEUG27co6rA_Zir8a5u0s')

