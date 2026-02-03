import discord
from discord import app_commands
import asyncio
import re
import os
import zipfile
import tempfile
from datetime import datetime, timedelta

BOT_TOKEN = os.getenv('BOT_TOKEN')
DELAY = 0.5

TASKS_CATEGORY_ID = 1464507292450951291
ARCHIVES_CATEGORY_ID = 1464517852454457488

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.is_sending = False
        self.stop_flag = False
        self.tasks_cache = {}
    
    async def setup_hook(self):
        await self.tree.sync()

bot = MyBot()

def parse_archive_name(filename):
    name = filename.rsplit('.', 1)[0]
    if name.endswith('.tar'):
        name = name.rsplit('.', 1)[0]
    parts = name.split('-')
    key_parts = []
    for part in parts:
        if part.isupper() and part.isalpha():
            continue
        if len(part) <= 2 and len(part) > 0 and part[0].isupper():
            continue
        key_parts.append(part)
    return '-'.join(key_parts)

def normalize_for_compare(text):
    return ' '.join(text.lower().split())

def get_search_variants(key):
    variants = [key.lower()]
    key_spaces = key.replace('-', ' ')
    if key_spaces != key:
        variants.append(key_spaces.lower())
    return variants

def get_task_key(task_text):
    task_text = re.sub(r'[<>]', '', task_text)
    task_text = re.sub(r'https?://', '', task_text)
    task_text = re.split(r'[\s/]', task_text)[0]
    return normalize_for_compare(task_text)

def add_to_cache(channel_id, task_key, msg_id):
    if channel_id not in bot.tasks_cache:
        bot.tasks_cache[channel_id] = {}
    bot.tasks_cache[channel_id][task_key] = msg_id

def remove_from_cache(channel_id, task_key):
    if channel_id in bot.tasks_cache and task_key in bot.tasks_cache[channel_id]:
        del bot.tasks_cache[channel_id][task_key]

async def load_tasks_cache(channel):
    cache = {}
    try:
        print(f"Загружаю таски из {channel.name}...")
        async for msg in channel.history(limit=2000):
            has_check = any(str(r.emoji) == '✅' for r in msg.reactions)
            if has_check:
                continue
            task_key = get_task_key(msg.content.strip())
            if task_key and task_key not in cache:
                cache[task_key] = msg.id
        bot.tasks_cache[channel.id] = cache
        print(f"Загружено {len(cache)} тасков из {channel.name}")
    except Exception as e:
        print(f"Ошибка загрузки кэша {channel.name}: {e}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if "Unknown interaction" in str(error):
        return
    print(f"Ошибка команды: {error}")

@bot.event
async def on_ready():
    print(f'Бот запущен: {bot.user}')
    for guild in bot.guilds:
        tasks_category = discord.utils.get(guild.categories, id=TASKS_CATEGORY_ID)
        if tasks_category:
            for channel in tasks_category.text_channels:
                await load_tasks_cache(channel)
                await asyncio.sleep(2)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if message.channel.category_id != ARCHIVES_CATEGORY_ID:
        return
    
    if not message.attachments:
        return
    
    for attachment in message.attachments:
        filename = attachment.filename
        
        if not any(filename.endswith(ext) for ext in ['.zip', '.rar', '.7z', '.tar', '.tar.gz', '.tgz']):
            continue
        
        key = parse_archive_name(filename)
        if not key:
            continue
        
        search_variants = get_search_variants(key)
        print(f"Архив: {filename} -> ключ: {key}")
        
        guild = message.guild
        tasks_category = discord.utils.get(guild.categories, id=TASKS_CATEGORY_ID)
        if not tasks_category:
            continue
        
        task_channel = None
        for channel in tasks_category.text_channels:
            if channel.name == message.channel.name:
                task_channel = channel
                break
        
        if not task_channel:
            print(f"Канал {message.channel.name} не найден в тасках")
            continue
        
        if task_channel.id not in bot.tasks_cache:
            await load_tasks_cache(task_channel)
        
        cache = bot.tasks_cache.get(task_channel.id, {})
        
        found = False
        print(f"Ищу в кэше: {search_variants}")
        print(f"В кэше {len(cache)} записей")
        if 'beste-wetten.com' in cache:
            print("beste-wetten.com ЕСТЬ в кэше")
        else:
            print("beste-wetten.com НЕТ в кэше")
            # Покажем похожие ключи
            similar = [k for k in cache.keys() if 'beste' in k or 'wetten' in k]
            print(f"Похожие ключи: {similar[:10]}")
        for variant in search_variants:
            variant_norm = normalize_for_compare(variant)
            if variant_norm in cache:
                msg_id = cache[variant_norm]
                try:
                    msg = await task_channel.fetch_message(msg_id)
                    
                    has_check = any(str(r.emoji) == '✅' for r in msg.reactions)
                    if has_check:
                        print(f"Таск уже выполнен: {variant_norm}")
                        remove_from_cache(task_channel.id, variant_norm)
                        continue
                    
                    try:
                        await msg.clear_reactions()
                    except:
                        pass
                    await msg.add_reaction('✅')
                    await message.add_reaction('✅')
                    remove_from_cache(task_channel.id, variant_norm)
                    print(f"Таск выполнен: {variant_norm}")
                    found = True
                    
                except discord.NotFound:
                    print(f"Сообщение удалено: {variant_norm}")
                    remove_from_cache(task_channel.id, variant_norm)
                except Exception as e:
                    print(f"Ошибка: {e}")
                break
        
        if not found:
            print(f"Таск не найден или не взят: {key}")

@bot.tree.command(name="reload", description="Перезагрузить кэш тасков")
async def reload_command(interaction: discord.Interaction):
    await interaction.response.send_message("🔄 Перезагружаю...", ephemeral=True)
    bot.tasks_cache = {}
    for guild in bot.guilds:
        tasks_category = discord.utils.get(guild.categories, id=TASKS_CATEGORY_ID)
        if tasks_category:
            for channel in tasks_category.text_channels:
                await load_tasks_cache(channel)
                await asyncio.sleep(2)
    await interaction.edit_original_response(content="✅ Кэш перезагружен")

@bot.tree.command(name="help", description="Показать справку")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "👋 **Привет!**\n\n"
        "📄 **Рассылка:** ПКМ → Приложения → Разослать\n"
        "📦 **Архивы:** кидай в 'Архивы' — бот отметит таск\n\n"
        "**/reload** — перезагрузить кэш\n"
        "**/stop** — остановить рассылку\n"
        "**/clear [кол-во]** — удалить сообщения",
        ephemeral=True
    )

@bot.tree.command(name="stop", description="Остановить рассылку")
async def stop_command(interaction: discord.Interaction):
    bot.stop_flag = True
    bot.is_sending = False
    await interaction.response.send_message("🛑 Остановлено", delete_after=10)

@bot.tree.command(name="reset", description="Сбросить состояние")
async def reset_command(interaction: discord.Interaction):
    bot.stop_flag = False
    bot.is_sending = False
    await interaction.response.send_message("✅ Сброшено", delete_after=10)

@bot.tree.command(name="clear", description="Удалить сообщения")
@app_commands.describe(amount="Количество (1-100)")
async def clear_command(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("❌ 1-100", ephemeral=True)
        return
    try:
        await interaction.response.send_message("🗑 Удаляю...", ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.edit_original_response(content=f"🗑 Удалено {len(deleted)}")
    except:
        pass

@bot.tree.context_menu(name="Собрать за эту дату")
async def download_by_date(interaction: discord.Interaction, message: discord.Message):
    try:
        await interaction.response.send_message("📥 Собираю...", ephemeral=True)
    except:
        return
    target_date = message.created_at.date()
    files = []
    async for msg in interaction.channel.history(limit=1000):
        if msg.created_at.date() == target_date:
            for att in msg.attachments:
                files.append({'url': att.url, 'filename': att.filename})
    if not files:
        await interaction.edit_original_response(content=f"❌ Нет файлов за {target_date}")
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, f"{interaction.channel.name}_{target_date}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            import urllib.request
            for f in files:
                try:
                    with urllib.request.urlopen(f['url']) as resp:
                        zf.writestr(f['filename'], resp.read())
                except:
                    pass
        if os.path.getsize(zip_path) > 25*1024*1024:
            await interaction.edit_original_response(content="❌ Архив > 25MB")
            return
        await interaction.channel.send(f"📦 {len(files)} файлов", file=discord.File(zip_path))
        await interaction.edit_original_response(content="✅ Готово")

@bot.tree.context_menu(name="Разослать")
async def send_context_menu(interaction: discord.Interaction, message: discord.Message):
    if bot.is_sending:
        await interaction.response.send_message("⚠️ Уже идёт", ephemeral=True)
        return
    if not message.attachments or not message.attachments[0].filename.endswith('.txt'):
        await interaction.response.send_message("❌ Нужен .txt", ephemeral=True)
        return
    
    try:
        await interaction.response.send_message("📥 Загружаю...", ephemeral=True)
    except:
        return
    
    content = (await message.attachments[0].read()).decode('utf-8')
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    if not lines:
        await interaction.edit_original_response(content="❌ Пусто")
        return
    
    await interaction.edit_original_response(content=f"📤 {len(lines)} строк...")
    
    bot.is_sending = True
    bot.stop_flag = False
    sent = 0
    failed = []
    
    for line in lines:
        if bot.stop_flag:
            break
        try:
            send_line = re.sub(r'(https?://[^\s]+)', r'<\1>', line)
            sent_msg = await interaction.channel.send(send_line)
            sent += 1
            
            if interaction.channel.category_id == TASKS_CATEGORY_ID:
                task_key = get_task_key(line)
                if task_key:
                    add_to_cache(interaction.channel.id, task_key, sent_msg.id)
        except:
            failed.append(line)
        await asyncio.sleep(DELAY)
    
    try:
        await message.delete()
    except:
        pass
    
    bot.is_sending = False
    done = await interaction.channel.send(f"✅ Отправлено: {sent}, ошибок: {len(failed)}")
    await asyncio.sleep(10)
    try:
        await done.delete()
    except:
        pass

bot.run(BOT_TOKEN)
