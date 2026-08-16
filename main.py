import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import libsql_client
import datetime
import calendar
import asyncio
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
# 1. CONFIGURATION & TOKENS
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TURSO_URL = os.getenv("TURSO_URL")
TURSO_TOKEN = os.getenv("TURSO_TOKEN")

# Optional safety check to stop the script early if variables are missing
if not DISCORD_TOKEN or not TURSO_URL or not TURSO_TOKEN:
    raise ValueError("Missing one or more environment variables (DISCORD_TOKEN, TURSO_URL, TURSO_TOKEN).")

# Custom emojis (Stickers)
STICKER_1 = "<:Announcement:1531654701656051835>"
STICKER_2 = "<:Gift:1531654766093008988>"
STICKER_3 = "<:Point:1531654800054288475>"
STICKER_4 = "<:Failed:1531654880685457542>"
STICKER_5 = "<:Success:1531654846116270181>"

DEFAULT_COLOR = discord.Color.from_str("#7BDFF2")

# ==========================================
# 2. BOT INITIALIZATION & DATABASE
# ==========================================
class BirthdayGoat(commands.Bot):
    def __init__(self):
        # Enable message content intent to clear the warning
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.db: libsql_client.Client = None


    async def setup_hook(self):
        # Initialize Turso Database Connection
        self.db = libsql_client.create_client(url=TURSO_URL, auth_token=TURSO_TOKEN)
        
        # Load Cogs / Extensions
        await self.load_extension("status")
        
        # Create Tables if they don't exist
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                server_id TEXT PRIMARY KEY,
                channel_id TEXT,
                ping_role_id TEXT,
                heading TEXT,
                description TEXT,
                image_url TEXT,
                thumbnail_url TEXT,
                footer TEXT,
                colour TEXT
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_birthdays (
                user_id TEXT,
                server_id TEXT,
                day INTEGER,
                month INTEGER,
                year INTEGER,
                PRIMARY KEY (user_id, server_id)
            )
        """)
        
        # Sync slash commands
        await self.tree.sync()
        
        # Start the background task
        self.check_birthdays.start()
        print("BirthdayGoat is online and commands are synced!")
        
    
    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

    # ==========================================
    # 3. DAILY BIRTHDAY CHECK (GMT 00:00)
    # ==========================================
    @tasks.loop(time=datetime.time(hour=0, minute=00, tzinfo=datetime.timezone.utc))
    async def check_birthdays(self):
        today = datetime.datetime.now(datetime.timezone.utc)
        is_leap = calendar.isleap(today.year)
        
        # Fetch today's birthdays. If it's Feb 28 on a non-leap year, also grab Feb 29 birthdays.
        if not is_leap and today.month == 2 and today.day == 28:
            result = await self.db.execute(
                "SELECT user_id, server_id FROM user_birthdays WHERE (day = 28 AND month = 2) OR (day = 29 AND month = 2)"
            )
        else:
            result = await self.db.execute(
                "SELECT user_id, server_id FROM user_birthdays WHERE day = ? AND month = ?", 
                (today.day, today.month)
            )

        for row in result.rows:
            user_id, server_id = int(row[0]), int(row[1])
            guild = self.get_guild(server_id)
            if not guild: continue
            
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            if not member: continue

            # Get Server Settings
            settings_req = await self.db.execute("SELECT * FROM guild_settings WHERE server_id = ?", (str(server_id),))
            
            if not settings_req.rows:
                continue # No channel set for this server
            
            settings = settings_req.rows[0]
            channel_id = settings[1]
            if not channel_id:
                continue
                
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue
            
            ping_role_id = settings[2]
            ping_text = f"<@&{ping_role_id}>" if ping_role_id else ""
            
            # Send the message
            embed = build_birthday_embed(member, settings)
            try:
                await channel.send(content=ping_text, embed=embed)
            except discord.Forbidden:
                pass # Bot lacks permissions to send in that channel

bot = BirthdayGoat()

# ==========================================
# 4. HELPER FUNCTIONS
# ==========================================
def replace_vars(text: str, member: discord.Member) -> str:
    if not text:
        return text
    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y")
    
    text = text.replace("{User}", member.mention)
    text = text.replace("{Server_name}", member.guild.name)
    text = text.replace("{Username}", member.name)
    text = text.replace("{User_id}", str(member.id))
    text = text.replace("{Server_id}", str(member.guild.id))
    text = text.replace("{Message send date}", today_str)
    return text

def build_birthday_embed(member: discord.Member, settings=None) -> discord.Embed:
    # Default values
    heading = f"{STICKER_1} Birthday Announcement"
    desc = f"{STICKER_2} Today is a special day\n{STICKER_3} Please wish {{User}} a happy birthday <3"
    footer = "BirthdayGoat | {Message send date}"
    color = DEFAULT_COLOR
    image_url = None
    thumbnail_url = None
    
    if settings:
        heading = settings[3] or heading
        desc = settings[4] or desc
        image_url = settings[5]
        thumbnail_url = settings[6]
        footer = settings[7] or footer
        if settings[8]:
            try:
                color = discord.Color.from_str(settings[8])
            except ValueError:
                color = DEFAULT_COLOR

    embed = discord.Embed(
        title=replace_vars(heading, member),
        description=replace_vars(desc, member),
        color=color
    )
    if footer:
        embed.set_footer(text=replace_vars(footer, member))
    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
        
    return embed

# ==========================================
# 5. MEMBER COMMANDS
# ==========================================
birthday_group = app_commands.Group(name="birthday", description="Birthday management commands")

@birthday_group.command(name="register", description="Register your birthday")
@app_commands.describe(day="Day of birth (1-31)", month="Month of birth", year="Year of birth (optional)")
@app_commands.choices(month=[
    app_commands.Choice(name="January", value=1), app_commands.Choice(name="February", value=2),
    app_commands.Choice(name="March", value=3), app_commands.Choice(name="April", value=4),
    app_commands.Choice(name="May", value=5), app_commands.Choice(name="June", value=6),
    app_commands.Choice(name="July", value=7), app_commands.Choice(name="August", value=8),
    app_commands.Choice(name="September", value=9), app_commands.Choice(name="October", value=10),
    app_commands.Choice(name="November", value=11), app_commands.Choice(name="December", value=12)
])
async def bday_register(interaction: discord.Interaction, day: app_commands.Range[int, 1, 31], month: app_commands.Choice[int], year: int = None):
    # Date Validation
    try:
        # If no year is provided, test with a leap year (2024) to allow Feb 29
        test_year = year if year else 2024
        datetime.date(test_year, month.value, day)
    except ValueError:
        embed = discord.Embed(title=f"Failed {STICKER_4}", description=f"{interaction.user.mention}\nThat date does not exist. Enter your real birthday date.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    await bot.db.execute(
        "INSERT INTO user_birthdays (user_id, server_id, day, month, year) VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, server_id) DO UPDATE SET day=excluded.day, month=excluded.month, year=excluded.year",
        (str(interaction.user.id), str(interaction.guild.id), day, month.value, year)
    )
    
    month_name = calendar.month_name[month.value]
    year_str = f" {year}" if year else ""
    
    embed = discord.Embed(title=f"Success {STICKER_5}", description=f"{interaction.user.mention}\nSuccessfully registered your birthday on {day} {month_name}{year_str}.", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=embed)

@birthday_group.command(name="remove", description="Remove your registered birthday")
async def bday_remove(interaction: discord.Interaction):
    result = await bot.db.execute("SELECT * FROM user_birthdays WHERE user_id = ? AND server_id = ?", (str(interaction.user.id), str(interaction.guild.id)))
    
    if not result.rows:
        embed = discord.Embed(title=f"Failed {STICKER_4}", description=f"{interaction.user.mention}\nYou didn't register your birthday.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    await bot.db.execute("DELETE FROM user_birthdays WHERE user_id = ? AND server_id = ?", (str(interaction.user.id), str(interaction.guild.id)))
    
    embed = discord.Embed(title=f"Success {STICKER_5}", description=f"{interaction.user.mention}\nSuccessfully removed your birthday.", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=embed)

@birthday_group.command(name="list", description="List all registered birthdays in the server")
async def bday_list(interaction: discord.Interaction):
    result = await bot.db.execute("SELECT user_id, day, month, year FROM user_birthdays WHERE server_id = ? ORDER BY month, day", (str(interaction.guild.id),))
    
    embed = discord.Embed(title=f"Birthday list - {interaction.guild.name}", color=DEFAULT_COLOR)
    embed.description = f"{STICKER_2} Register your birthday with\n`/birthday register <day> <month> [year]`\n\n"
    
    if not result.rows:
        embed.description += "*No birthdays registered yet!*"
        return await interaction.response.send_message(embed=embed)

    # Group by month
    birthdays_by_month = {}
    for row in result.rows:
        u_id, d, m, y = row
        m_name = calendar.month_name[int(m)]
        if m_name not in birthdays_by_month:
            birthdays_by_month[m_name] = []
            
        year_str = f" {y}" if y else ""
        birthdays_by_month[m_name].append(f"<@{u_id}> {d} {m_name}{year_str}")

    for month_name in calendar.month_name[1:]: # Jan to Dec
        if month_name in birthdays_by_month:
            month_list = "\n".join(birthdays_by_month[month_name])
            embed.add_field(name=f"**{month_name}**", value=month_list, inline=False)

    await interaction.response.send_message(embed=embed)

# ==========================================
# 6. WEB SERVER (RENDER WORKAROUND)
# ==========================================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BirthdayGoat is alive!")

    def do_HEAD(self):
        # This stops Render's health checks from throwing a 501 error!
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()
    
# ==========================================
# 7. OWNER COMMANDS
# ==========================================




set_group = app_commands.Group(name="set", description="Server configuration commands", default_permissions=discord.Permissions(administrator=True))

@set_group.command(name="channel", description="Set the channel where birthday wishes will be sent")
async def set_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await bot.db.execute(
        "INSERT INTO guild_settings (server_id, channel_id) VALUES (?, ?) ON CONFLICT(server_id) DO UPDATE SET channel_id=excluded.channel_id",
        (str(interaction.guild.id), str(channel.id))
    )
    embed = discord.Embed(title=f"Success {STICKER_5}", description=f"Successfully set {channel.mention} as the birthday channel.", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=embed)

@set_group.command(name="ping", description="Set the role to ping for birthdays")
async def set_ping(interaction: discord.Interaction, role: discord.Role):
    if role == interaction.guild.default_role or role.name in ["@everyone", "@here"]:
        embed = discord.Embed(title=f"Failed {STICKER_4}", description="We can't set @everyone/@here as the birthday ping.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed)

    await bot.db.execute(
        "INSERT INTO guild_settings (server_id, ping_role_id) VALUES (?, ?) ON CONFLICT(server_id) DO UPDATE SET ping_role_id=excluded.ping_role_id",
        (str(interaction.guild.id), str(role.id))
    )
    embed = discord.Embed(title=f"Success {STICKER_5}", description=f"Birthday ping set to {role.mention}", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=embed)

@set_group.command(name="message", description="Customize the server's birthday message")
async def set_message(interaction: discord.Interaction, heading: str = None, description: str = None, image_url: str = None, thumbnail_url: str = None, footer: str = None, colour: str = None):
    if colour:
        if not colour.startswith("#"): colour = f"#{colour}"
        try:
            discord.Color.from_str(colour)
        except ValueError:
            return await interaction.response.send_message("Invalid colour format. Use hex codes (e.g., #FFFFFF)", ephemeral=True)

    await bot.db.execute("""
        INSERT INTO guild_settings (server_id, heading, description, image_url, thumbnail_url, footer, colour) 
        VALUES (?, ?, ?, ?, ?, ?, ?) 
        ON CONFLICT(server_id) DO UPDATE SET 
        heading=COALESCE(?, guild_settings.heading), 
        description=COALESCE(?, guild_settings.description),
        image_url=COALESCE(?, guild_settings.image_url),
        thumbnail_url=COALESCE(?, guild_settings.thumbnail_url),
        footer=COALESCE(?, guild_settings.footer),
        colour=COALESCE(?, guild_settings.colour)
    """, (str(interaction.guild.id), heading, description, image_url, thumbnail_url, footer, colour, 
          heading, description, image_url, thumbnail_url, footer, colour))

    embed = discord.Embed(title=f"Success {STICKER_5}", description="Successfully updated the custom birthday message.", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=embed)



@birthday_group.command(name="test", description="Test the birthday message (Owner only)")
@app_commands.checks.has_permissions(administrator=True)
async def bday_test(interaction: discord.Interaction):
    success_embed = discord.Embed(title=f"Success {STICKER_5}", description="Birthday message sent successfully.", color=DEFAULT_COLOR)
    await interaction.response.send_message(embed=success_embed, ephemeral=True)
    
    result = await bot.db.execute("SELECT * FROM guild_settings WHERE server_id = ?", (str(interaction.guild.id),))
    
    if not result.rows or not result.rows[0][1]:
        return await interaction.followup.send("No birthday channel is set! Use `/set channel` first.", ephemeral=True)
    
    settings = result.rows[0]
    channel_id = int(settings[1])
    ping_role_id = settings[2]
    
    channel = interaction.guild.get_channel(channel_id)
    ping_text = f"<@&{ping_role_id}>" if ping_role_id else ""
    
    embed = build_birthday_embed(interaction.user, settings)
    await channel.send(content=ping_text, embed=embed)

@bot.tree.command(name="id", description="Displays all slash command IDs for this bot.")
@app_commands.default_permissions(administrator=True)
async def get_command_ids(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        commands = await interaction.client.tree.fetch_commands()

        if not commands:
            await interaction.followup.send("No synced commands found.")
            return

        command_list = [f"**/{cmd.name}**: `{cmd.id}`" for cmd in commands]
        message = "**Bot Slash Command IDs:**\n" + "\n".join(command_list)

        await interaction.followup.send(message)

    except Exception as e:
        await interaction.followup.send(f"Failed to fetch command IDs: {e}")



# Register command trees
bot.tree.add_command(birthday_group)
bot.tree.add_command(set_group)



# ==========================================
# 8. RUN BOT & WEB SERVER
# ==========================================
if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    bot.run(DISCORD_TOKEN)
    
