import discord
from discord.ext import commands
import os
import json
from datetime import datetime, timezone, timedelta
import pytz

utc=pytz.UTC

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# Folder to store message logs
MESSAGE_LOG_DIR = 'message_logs'
if not os.path.exists(MESSAGE_LOG_DIR):
    os.makedirs(MESSAGE_LOG_DIR)

if 'DISCORD_BOT_TOKEN' not in os.environ:
    print("Error: DISCORD_BOT_TOKEN is not set")
    exit(1)
else:
    bot_token = os.environ.get('DISCORD_BOT_TOKEN')

    
# Load existing messages from disk
def load_existing_messages(channel_id):
    file_path = f"{MESSAGE_LOG_DIR}/{channel_id}.json"
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# Fetch and save messages from a specific channel, only fetching new ones
async def fetch_new_messages(channel):
    existing_messages = load_existing_messages(channel.id)
    
    # Find the timestamp of the last saved message
    last_saved_time = None
    if existing_messages:
        last_saved_time = max(datetime.fromisoformat(msg['timestamp']) for msg in existing_messages)
    
    # Fetch only messages newer than the last saved one
    new_messages = []
    async for message in channel.history(limit=10000, after=last_saved_time):
        new_messages.append({'timestamp': message.created_at.isoformat(), 'author': message.author.id})

    newest_messages_by_author = {}

    # Iterate through both existing and new messages to keep the latest per author
    for msg in existing_messages + new_messages:
        author_id = msg['author']
        msg_timestamp = datetime.fromisoformat(msg['timestamp'])
        
        # Keep only the latest message for each author
        if (author_id not in newest_messages_by_author) or (msg_timestamp > datetime.fromisoformat(newest_messages_by_author[author_id]['timestamp'])):
            newest_messages_by_author[author_id] = msg
    
    # Convert dictionary values back to a list of messages
    all_messages = list(newest_messages_by_author.values())

    # Sort the messages by timestamp in reverse (newest first)
    sorted_new_messages = sorted(all_messages, key=lambda x: datetime.fromisoformat(x["timestamp"]), reverse=True)

    # Save the updated list back to disk
    with open(f"{MESSAGE_LOG_DIR}/{channel.id}.json", 'w', encoding='utf-8') as f:
        json.dump(sorted_new_messages, f, ensure_ascii=False, indent=4)
    
    if new_messages:
        print(f"Fetched {len(new_messages)} new messages from {channel.name}")
    

# Fetch and save messages from all channels
async def fetch_messages(guild):
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).read_message_history:
            await fetch_new_messages(channel)

# Get the last message timestamp for each user
def get_last_message_time(guild):
    user_last_message = {}
    for channel_file in os.listdir(MESSAGE_LOG_DIR):
        with open(f"{MESSAGE_LOG_DIR}/{channel_file}", 'r', encoding='utf-8') as f:
            messages = json.load(f)
            for msg in messages:
                user = msg['author']
                timestamp = datetime.fromisoformat(msg['timestamp'])
                if user not in user_last_message or user_last_message[user] < timestamp:
                    user_last_message[user] = timestamp
    return user_last_message

def remove_member_messages(member, guild):
    for channel_file in os.listdir(MESSAGE_LOG_DIR):
        messages = []
        with open(f"{MESSAGE_LOG_DIR}/{channel_file}", 'r', encoding='utf-8') as f:
            messages += [ msg for msg in json.load(f) if msg['author'] != member.id]
        with open(f"{MESSAGE_LOG_DIR}/{channel_file}", 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=4)
    return

def get_whitelist():
    with open('whitelist.json', 'r', encoding='utf-8') as f:
        return json.load(f)


@bot.hybrid_group(fallback="show")
@commands.has_permissions(administrator=True)
async def whitelist(ctx, name):
    whitelist = "\n".join(get_whitelist())
    await ctx.send(f"**Whitelisted members (will not be kicked out even when inactive:** \n" + whitelist)

@whitelist.command()
@commands.has_permissions(administrator=True)
async def add(ctx, name):
    guild = ctx.guild
    existing_members = []
    with open('whitelist.json', 'r', encoding='utf-8') as f:
        existing_members = json.load(f)
    if name not in [member.name for member in guild.members]:
        await ctx.send(f"**User {name} does not exist or is not a member of this server**")
        return
    if name in existing_members:
        await ctx.send(f"**User {name} is already on the whitelist**")
        return
    new_members = existing_members + [name]
    with open('whitelist.json', 'w', encoding='utf-8') as f:
        json.dump(new_members, f, ensure_ascii=False, indent=4)
    await ctx.send(f"**User {name} was added to the whitelist**\nThe whitelist currently contains the following users:\n" + "\n".join(new_members))


@whitelist.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, name):
    guild = ctx.guild
    existing_members = []
    with open('whitelist.json', 'r', encoding='utf-8') as f:
        existing_members = json.load(f)
    if name not in [member.name for member in guild.members]:
        await ctx.send(f"**User {name} does not exist or is not a member of this server**")
        return
    if name not in existing_members:
        await ctx.send(f"**User {name} is not currently on the whitelist**")
        return
    existing_members.remove(name)
    with open('whitelist.json', 'w', encoding='utf-8') as f:
        json.dump(existing_members, f, ensure_ascii=False, indent=4)
    await ctx.send(f"**User {name} was removed from the whitelist**\nThe whitelist currently contains the following users:\n" + "\n".join(existing_members))

# Check for inactive members
@bot.command(name='inactive')
async def check_inactive(ctx, n: int):
    await ctx.send(f"Checking for members who haven't sent a message in the last {n} days...")
    guild = ctx.guild
    
    user_last_message = get_last_message_time(guild)
    inactive_members = []
    inactive_whitelisted_members = []
    cutoff_date = datetime.now() - timedelta(days=n)

    whitelist = get_whitelist()

    for member in guild.members:
        if not member.bot:
            last_message_time = user_last_message.get(member.id)
            if last_message_time is None or last_message_time < utc.localize(cutoff_date):
                if member.name not in whitelist:
                    inactive_members.append(member.name)
                else:
                    inactive_whitelisted_members.append(member.name)

    inactive_members.sort()
    inactive_whitelisted_members.sort()
    if inactive_members:
        await ctx.send(f"**{str(len(inactive_members))} inactive members in the last {n} days:**\n" + "\n".join(inactive_members))
    else:
        await ctx.send(f"No inactive members found in the last {n} days.")
    if inactive_whitelisted_members:
        await ctx.send(f"**{str(len(inactive_whitelisted_members))} whitelisted inactive members:**\n" + "\n".join(inactive_whitelisted_members))

# Check for inactive members
@bot.command(name='kick_inactive')
@commands.has_permissions(administrator=True)
async def kick_inactive(ctx, n: int):
    await ctx.send(f"Kicking members who haven't sent a message in the last {n} days...")
    guild = ctx.guild
    
    user_last_message = get_last_message_time(guild)
    inactive_members = []
    inactive_whitelisted_members = []
    cutoff_date = datetime.now() - timedelta(days=n)

    whitelist = get_whitelist()

    for member in guild.members:
        if not member.bot:
            last_message_time = user_last_message.get(member.id)
            if last_message_time is None or last_message_time < utc.localize(cutoff_date):
                if member.name not in whitelist:
                    inactive_members.append(member.name)
                    remove_member_messages(member, guild)
                    try:
                        await member.kick(reason=f"Inactive in {guild.name} for {n} days")
                        await ctx.send(f"**Kicked {member.name} for inactivity**")
                    except:
                        print('Error kicking {member.name}')
                else:
                    inactive_whitelisted_members.append(member.name)

    inactive_members.sort()
    inactive_whitelisted_members.sort()
    if inactive_members:
        await ctx.send(f"**Kicked {str(len(inactive_members))} members which were inactive in the last {n} days**\n" + "\n".join(inactive_members))
    else:
        await ctx.send(f"No inactive members found in the last {n} days.")
    if inactive_whitelisted_members:
        await ctx.send(f"**Did not kick {str(len(inactive_whitelisted_members))} whitelisted inactive members:**\n" + "\n".join(inactive_whitelisted_members))


@bot.event
async def on_message(message):
    await bot.process_commands(message)
    for guild in bot.guilds:
        await fetch_messages(guild)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    for guild in bot.guilds:
        await fetch_messages(guild)
    print(f"Ready for your commands!")

# Run the bot
bot.run(bot_token)
