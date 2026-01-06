import disnake
import os
from disnake.ext import commands, tasks
from datetime import timedelta, datetime
import random, time, aiosqlite

# ======== Настройки ========
MY_GUILD_ID = 1319737766053019720
BOT_PREFIX = "!"
WELCOME_CHANNEL_ID = 1457197951209312277
COUNT_CHANNEL_ID = 1457199865162502325
ROLE_ID = 1454602641681154202

intents = disnake.Intents.all()
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# ======== Анти-рейд ========
raid_threshold = 3
short_time = 10
recent_joins = []

# ======== Войс ========
voice_times = {}

# ======== XP ========
DB_FILE = "ravenfall_xp.db"

async def create_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            voice_time INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            last_message REAL DEFAULT 0
        )
        """)
        await db.commit()

async def add_xp(user_id: int, amount: int):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT xp, level, voice_time, messages, last_message FROM users WHERE user_id=?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                xp, level, voice_time, messages, last_message = row
                xp += amount
            else:
                xp, level, voice_time, messages, last_message = amount, 1, 0, 0, 0

        leveled_up = False
        while xp >= 5*level*level + 50*level + 100:
            xp -= 5*level*level + 50*level + 100
            level += 1
            leveled_up = True

        await db.execute("""
            INSERT OR REPLACE INTO users
            (user_id, xp, level, voice_time, messages, last_message)
            VALUES(?,?,?,?,?,?)
        """, (user_id, xp, level, voice_time, messages, last_message))
        await db.commit()

    if leveled_up:
        guild = bot.get_guild(MY_GUILD_ID)
        if guild:
            member = guild.get_member(user_id)
            if member and guild.system_channel:
                await guild.system_channel.send(
                    embed=disnake.Embed(
                        title="🎉 Level Up!",
                        description=f"{member.mention} достиг {level} уровня!",
                        color=disnake.Color.green()
                    )
                )

# ======== Статус ========
@tasks.loop(minutes=1)
async def update_status():
    guild = bot.get_guild(MY_GUILD_ID)
    if guild:
        await bot.change_presence(
            activity=disnake.Game(
                name=f"{guild.member_count} участников на RAVENFALL"
            )
        )

# ======== Канал участников ========
@tasks.loop(seconds=5)
async def update_count_channel():
    guild = bot.get_guild(MY_GUILD_ID)
    if guild:
        channel = guild.get_channel(COUNT_CHANNEL_ID)
        if channel:
            try:
                await channel.edit(
                    name=f"𝖒𝖊𝖒𝖇𝖊𝖗𝖘⠀:➡{guild.member_count}"
                )
            except:
                pass

# ======== READY ========
@bot.event
async def on_ready():
    await create_db()
    update_status.start()
    update_count_channel.start()
    print(f"Бот запущен как {bot.user}")

# ======== ОБЪЕДИНЁННЫЙ on_member_join ========
@bot.event
async def on_member_join(member):
    if member.guild.id != MY_GUILD_ID:
        return

    # БД
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
            (member.id,)
        )
        await db.commit()

    # Роль
    role = member.guild.get_role(ROLE_ID)
    if role:
        await member.add_roles(role)

    # Приветствие
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        await channel.send(
            embed=disnake.Embed(
                title="🎉 Добро пожаловать!",
                description=f"{member.mention}, ты {member.guild.member_count}-й участник!",
                color=disnake.Color.green()
            )
        )

    # Анти-рейд
    now = datetime.utcnow()
    recent_joins.append(now)
    recent_joins[:] = [
        t for t in recent_joins
        if (now - t).seconds < short_time
    ]

    if len(recent_joins) >= raid_threshold:
        if member.guild.system_channel:
            await member.guild.system_channel.send(
                embed=disnake.Embed(
                    title="⚠️ Анти-рейд",
                    description="Обнаружен массовый вход",
                    color=disnake.Color.red()
                )
            )

        for m in member.guild.members:
            if m.joined_at and (now - m.joined_at).seconds < short_time:
                try:
                    await m.timeout(
                        duration=timedelta(minutes=10),
                        reason="Анти-рейд"
                    )
                except:
                    pass

# ======== ВОЙС ========
@bot.event
async def on_voice_state_update(member, before, after):
    if member.guild.id != MY_GUILD_ID:
        return

    if not before.channel and after.channel:
        voice_times[member.id] = time.time()

    elif before.channel and not after.channel:
        start = voice_times.pop(member.id, None)
        if start:
            seconds = int(time.time() - start)
            xp = (seconds // 60) * 2

            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute(
                    "SELECT voice_time FROM users WHERE user_id=?",
                    (member.id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    total = (row[0] if row else 0) + seconds

                await db.execute(
                    "UPDATE users SET voice_time=? WHERE user_id=?",
                    (total, member.id)
                )
                await db.commit()

            await add_xp(member.id, xp)

# ======== СООБЩЕНИЯ ========
@bot.event
async def on_message(message):
    if message.author.bot or message.guild.id != MY_GUILD_ID:
        return

    now = time.time()
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT last_message FROM users WHERE user_id=?",
            (message.author.id,)
        ) as cursor:
            row = await cursor.fetchone()
            last = row[0] if row else 0

        if now - last >= 45:
            await add_xp(message.author.id, 5)
            await db.execute(
                "UPDATE users SET last_message=? WHERE user_id=?",
                (now, message.author.id)
            )
            await db.commit()

    await bot.process_commands(message)

# ======== EMBED ========
def make_embed(title, description, color=disnake.Color.blurple()):
    return disnake.Embed(title=title, description=description, color=color)

# ======== КОМАНДЫ ========
@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! `{round(bot.latency*1000)} ms`")

@bot.command()
async def say(ctx, *, text):
    await ctx.message.delete()
    await ctx.send(text)

@bot.command()
async def roll(ctx, max_num: int = 100):
    await ctx.send(f"🎲 Выпало: **{random.randint(1, max_num)}**")

@bot.command()
async def avatar(ctx, member: disnake.Member = None):
    member = member or ctx.author
    embed = disnake.Embed(
        title=f"Аватар {member.name}",
        color=disnake.Color.dark_purple()
    )
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def server(ctx):
    g = ctx.guild
    embed = disnake.Embed(title=g.name, color=disnake.Color.dark_gray())
    embed.add_field(name="👥 Участники", value=g.member_count)
    embed.add_field(name="🆔 ID", value=g.id)
    embed.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    embed = disnake.Embed(title="🏆 Топ", color=disnake.Color.gold())
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT user_id, xp, level, voice_time FROM users ORDER BY level DESC, xp DESC LIMIT 10"
        ) as cursor:
            i = 1
            async for uid, xp, lvl, vt in cursor:
                m = ctx.guild.get_member(uid)
                name = m.display_name if m else uid
                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"🆙 {lvl} | 💎 {xp} | 🎧 {vt//60} мин",
                    inline=False
                )
                i += 1
    await ctx.send(embed=embed)

# ======== ОШИБКИ ========
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(make_embed("❌ Ошибка", "Нет прав", disnake.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(make_embed("⚠️ Ошибка", "Не хватает аргументов", disnake.Color.orange()))
    else:
        await ctx.send(make_embed("⚠️ Ошибка", str(error), disnake.Color.red()))

# ======== ЗАПУСК ========
bot.run(os.getenv("TOKEN"))