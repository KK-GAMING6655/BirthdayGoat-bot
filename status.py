import os
import discord
from discord.ext import commands, tasks

class StatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # Load Voice Channel IDs from environment variables
        self.server_channel_id = int(os.getenv("SERVER_COUNT_CHANNEL_ID", "0"))
        self.user_channel_id = int(os.getenv("USER_COUNT_CHANNEL_ID", "0"))
        
        # Start the task loop
        self.update_status_channels.start()

    def cog_unload(self):
        self.update_status_channels.cancel()

    @tasks.loop(minutes=30)  # Safe interval matching Discord's 2 edits / 10 mins rate limit
    async def update_status_channels(self):
        await self.bot.wait_until_ready()

        # Calculate live stats
        total_servers = len(self.bot.guilds)
        total_users = sum(guild.member_count or 0 for guild in self.bot.guilds)

        # 1. Update Server Count Channel
        if self.server_channel_id:
            channel = self.bot.get_channel(self.server_channel_id)
            if channel:
                target_name = f"Servers: {total_servers} 🎂"
                # Only call API if the name has actually changed
                if channel.name != target_name:
                    try:
                        await channel.edit(name=target_name)
                    except discord.HTTPException as e:
                        print(f"[Status Cog] Failed to rename server channel: {e}")

        # 2. Update User Count Channel
        if self.user_channel_id:
            channel = self.bot.get_channel(self.user_channel_id)
            if channel:
                target_name = f"Users: {total_users} 👥"
                # Only call API if the name has actually changed
                if channel.name != target_name:
                    try:
                        await channel.edit(name=target_name)
                    except discord.HTTPException as e:
                        print(f"[Status Cog] Failed to rename user channel: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(StatusCog(bot))

