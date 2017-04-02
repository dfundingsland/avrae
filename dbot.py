import asyncio
from datetime import timedelta, datetime, tzinfo
import json
import logging
from math import floor
import os
import pickle
import random
import signal
import sys
import time
import traceback

import discord
from discord.errors import Forbidden, NotFound
from discord.ext import commands
from discord.ext.commands.errors import CommandInvokeError
import psutil

from cogs5e.charGen import CharGenerator
from cogs5e.diceAlgorithm import Dice
from cogs5e.initiativeTracker import InitTracker
from cogs5e.lookup import Lookup
from cogs5e.pbpUtils import PBPUtils
from cogs5e.sheetManager import SheetManager
from cogsmisc.adminUtils import AdminUtils
from cogsmisc.core import Core
from cogsmisc.customization import Customization
from cogsmisc.permissions import Permissions
from cogsmisc.publicity import Publicity
from cogsmisc.repl import REPL
from utils import checks
from utils.dataIO import DataIO
from utils.functions import make_sure_path_exists, discord_trim, get_positivity, \
    list_get
from utils.help import Help

INITIALIZING = True
TESTING = get_positivity(os.environ.get("TESTING", False))
if 'test' in sys.argv:
    TESTING = True
prefix = '!' if not TESTING else '#'
shard_id = 0
shard_count = 1
SHARDED = False
if '-s' in sys.argv:
    temp_shard_id = list_get(sys.argv.index('-s') + 1, None, sys.argv)
    if temp_shard_id is not None:
        shard_count = os.environ.get('SHARDS', 1)
        shard_id = temp_shard_id if temp_shard_id < shard_count else 0
        SHARDED = True


# TODO: 
# more flavor text
# More Breath Weapons
description = '''Avrae, a D&D 5e utility bot made by @zhu.exe#4211.
Invite Avrae to your server [here](https://discordapp.com/oauth2/authorize?&client_id=***REMOVED***&scope=bot&permissions=36727808)!
Join the official testing server [here](https://discord.gg/pQbd4s6)!
Love the bot? Donate to me [here](https://www.paypal.me/avrae)! \u2764
'''
if not SHARDED:
    bot = commands.Bot(command_prefix=commands.when_mentioned_or(prefix), description=description, pm_help=True)
else:
    bot = commands.Bot(command_prefix=commands.when_mentioned_or(prefix), description=description, pm_help=True, shard_id=int(shard_id), shard_count=int(shard_count))
bot.prefix = prefix
bot.remove_command('help')
bot.testing = TESTING

if os.path.isfile('./resources.txt'):
    with open('./resources.txt', 'r') as f:  # this is really inefficient
        resource = list(f)
        bot.mask = int(resource[0], base=2)
else:
    bot.mask = 0x00

class Credentials():
    pass

# CREDENTIALS
try:
    import credentials
    bot.credentials = Credentials()
    bot.credentials.testToken = credentials.testToken
    bot.credentials.officialToken = credentials.officialToken
    bot.credentials.discord_bots_key = credentials.discord_bots_key
    bot.credentials.carbon_key = credentials.carbon_key
    bot.credentials.test_database_url = credentials.test_database_url
except ImportError:
    bot.credentials = Credentials()
    bot.credentials.testToken = os.environ.get('TEST_TOKEN')
    bot.credentials.officialToken = os.environ.get('OFFICIAL_TOKEN')
    bot.credentials.discord_bots_key = os.environ.get('DISCORD_BOTS_KEY')
    bot.credentials.carbon_key = os.environ.get('CARBON_KEY')
    bot.credentials.test_database_url = os.environ.get('TEST_DATABASE_URL')
    
bot.db = DataIO() if not TESTING else DataIO(testing=True, test_database_url=bot.credentials.test_database_url)

logger = logging.getLogger('discord')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('s.{}:%(levelname)s:%(name)s: %(message)s'.format(getattr(bot, 'shard_id', 0))))
logger.addHandler(handler)

#-----COGS-----
diceCog = Dice(bot)
charGenCog = CharGenerator(bot)
initiativeTrackerCog = InitTracker(bot)
adminUtilsCog = AdminUtils(bot)
lookupCog = Lookup(bot)
coreCog = Core(bot)
permissionsCog = Permissions(bot)
publicityCog = Publicity(bot)
pbpCog = PBPUtils(bot)
helpCog = Help(bot)
sheetCog = SheetManager(bot)
customizationCog = Customization(bot)
cogs = [diceCog,
        charGenCog,
        initiativeTrackerCog,
        adminUtilsCog,
        lookupCog,
        coreCog,
        permissionsCog,
        publicityCog,
        pbpCog,
        helpCog,
        sheetCog,
        customizationCog,
        REPL(bot)]

@bot.event
async def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')
    await enter()

async def enter():
    await bot.wait_until_ready()
    appInfo = await bot.application_info()
    bot.owner = appInfo.owner
    bot.botStats = {}
    statKeys = ["dice_rolled_session", "spells_looked_up_session", "monsters_looked_up_session", "commands_used_session", "dice_rolled_life", "spells_looked_up_life", "monsters_looked_up_life", "commands_used_life", "items_looked_up_life", "items_looked_up_session"]
    for k in statKeys:
        if not bot.db.exists(k): bot.db.set(k, 0)
        bot.botStats[k] = int(bot.db.get(k, 0))
    bot.botStats["items_looked_up_session"] = bot.botStats["items_looked_up_session"] = bot.botStats["dice_rolled_session"] = bot.botStats["spells_looked_up_session"] = bot.botStats["monsters_looked_up_session"] = bot.botStats["commands_used_session"] = 0
    if not bot.db.exists('build_num'): bot.db.set('build_num', 114) # this was added in build 114
    if getattr(bot, "shard_id", 0) == 0: bot.db.incr('build_num')
    await bot.change_presence(game=discord.Game(name='D&D 5e | !help'))
    
@bot.event
async def on_command_error(error, ctx):
    if isinstance(error, commands.CommandNotFound):
        return
    tb = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    if isinstance(error, commands.CheckFailure):
        await bot.send_message(ctx.message.channel, "Error: Either you do not have the permissions to run this command, the command is disabled, or something went wrong internally.")
        return
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument, commands.NoPrivateMessage, ValueError)):
        return await bot.send_message(ctx.message.channel, "Error: " + str(error) + "\nUse `!help " + ctx.command.qualified_name + "` for help.")
    elif isinstance(error, CommandInvokeError):
        original = error.original
        if isinstance(original, Forbidden):
            try:
                return await bot.send_message(ctx.message.author, "Error: I am missing permissions to run this command. Please make sure I have permission to send messages to <#{}>.".format(ctx.message.channel.id))
            except:
                pass
        if isinstance(original, NotFound):
            return await bot.send_message(ctx.message.channel, "Error: I tried to edit or delete a message that no longer exists.")
        if isinstance(original, ValueError) and str(original) == "No closing quotation":
            return await bot.send_message(ctx.message.channel, "Error: No closing quotation.")
    if bot.mask & coreCog.debug_mask:
        await bot.send_message(ctx.message.channel, "Error: " + str(error) + "\nThis incident has been reported to the developer.")
        try:
            await bot.send_message(bot.owner, "Error in channel {} ({}), server {} ({}), shard {}: {}\nCaused by message: `{}`".format(ctx.message.channel, ctx.message.channel.id, ctx.message.server, ctx.message.server.id, getattr(bot, 'shard_id', 0), repr(error), ctx.message.content))
        except AttributeError:
            await bot.send_message(bot.owner, "Error in PM with {} ({}), shard 0: {}\nCaused by message: `{}`".format(ctx.message.author.mention, str(ctx.message.author), repr(error), ctx.message.content))
        for o in discord_trim(tb):
            await bot.send_message(bot.owner, o)
    else:
        await bot.send_message(ctx.message.channel, "Error: " + str(error))
    print("s.{}: Error caused by message: `{}`".format(getattr(bot, 'shard_id', 0), ctx.message.content))
    traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)
                
@bot.event
async def on_message(message):
    if message.author in adminUtilsCog.muted:
        return
    if message.content.startswith('avraepls'):
        if coreCog.verbose_mask & bot.mask:
            print("Shard {} reseeding RNG...".format(getattr(bot, 'shard_id', 0)))
            await bot.send_message(message.channel, "`Reseeding RNG...`")
        random.seed()
    if not hasattr(bot, 'global_prefixes'):  # bot's still starting up!
        return
    try:
        guild_prefix = bot.global_prefixes.get(message.server.id, bot.prefix)
    except:
        guild_prefix = bot.prefix
    if message.content.startswith(guild_prefix):
        message.content = message.content.replace(guild_prefix, bot.prefix, 1)
    elif message.content.startswith(bot.prefix): return
    if message.content.startswith(bot.prefix) and INITIALIZING: return await bot.send_message(message.channel, "Bot is initializing, try again in a few seconds!")
    await bot.process_commands(message)
    
@bot.event
async def on_command(command, ctx):
    bot.botStats['commands_used_session'] += 1
    bot.db.incr('commands_used_life')

# SIGNAL HANDLING
def sigterm_handler(_signum, _frame):
    try:
        print("Attempting to save combats...")
        bot.get_cog("InitTracker").panic_save()
    except: pass
    bot.loop.run_until_complete(bot.logout())
    bot.loop.close()
    sys.exit(0)
    
signal.signal(signal.SIGTERM, sigterm_handler)
            
for cog in cogs:
    bot.add_cog(cog)

if SHARDED: print("I am shard {} of {}.".format(str(int(bot.shard_id) + 1), str(bot.shard_count)))

INITIALIZING = False
if not TESTING:     
    bot.run(bot.credentials.officialToken)  # official token
else:
    bot.run(bot.credentials.testToken)  # test token
