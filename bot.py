import discord
from discord import app_commands
from discord.ext import commands
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
SUGESTOES_CHANNEL_ID = 1524644043316006983
GUILD_ID = 1323580646664441877

if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN nao configurado nas variaveis de ambiente')

intents = discord.Intents.default()

class TDNBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info(f'Slash commands sincronizados no servidor {GUILD_ID}!')

    async def on_ready(self):
        logger.info(f'Bot {self.user} esta online!')
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name='as sugestoes da Tropa'
        ))

bot = TDNBot()


class SugestaoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.aceitar_count = 0
        self.recusar_count = 0
        self.voted_users: dict[int, str] = {}

    def _update_labels(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == 'btn_aceitar':
                    child.label = f'Aceitar ({self.aceitar_count})'
                elif child.custom_id == 'btn_recusar':
                    child.label = f'Recusar ({self.recusar_count})'

    @discord.ui.button(
        label='Aceitar (0)',
        style=discord.ButtonStyle.success,
        custom_id='btn_aceitar',
        emoji='✅'
    )
    async def btn_aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        voto_anterior = self.voted_users.get(user_id)

        if voto_anterior == 'aceitar':
            self.aceitar_count -= 1
            del self.voted_users[user_id]
        else:
            if voto_anterior == 'recusar':
                self.recusar_count -= 1
            self.aceitar_count += 1
            self.voted_users[user_id] = 'aceitar'

        self._update_labels()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(
        label='Recusar (0)',
        style=discord.ButtonStyle.danger,
        custom_id='btn_recusar',
        emoji='❌'
    )
    async def btn_recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        voto_anterior = self.voted_users.get(user_id)

        if voto_anterior == 'recusar':
            self.recusar_count -= 1
            del self.voted_users[user_id]
        else:
            if voto_anterior == 'aceitar':
                self.aceitar_count -= 1
            self.recusar_count += 1
            self.voted_users[user_id] = 'recusar'

        self._update_labels()
        await interaction.response.edit_message(view=self)


@bot.tree.command(name='sugerir', description='Envie uma sugestao para o servidor!')
@app_commands.describe(mensagem='Escreva sua sugestao aqui')
async def sugerir(interaction: discord.Interaction, mensagem: str):
    await interaction.response.defer(ephemeral=True)

    try:
        canal_sugestoes = interaction.guild.get_channel(SUGESTOES_CHANNEL_ID)

        if canal_sugestoes is None:
            await interaction.followup.send(
                '❌ Canal de sugestoes nao encontrado. Verifique se o bot tem acesso ao canal.',
                ephemeral=True
            )
            return

        embed = discord.Embed(
            description=mensagem,
            color=discord.Color.from_rgb(88, 101, 242),
            timestamp=interaction.created_at
        )
        embed.set_author(
            name=f'Sugestao por {interaction.user.display_name}',
            icon_url=interaction.user.display_avatar.url
        )

        view = SugestaoView()
        msg = await canal_sugestoes.send(embed=embed, view=view)

        thread = await msg.create_thread(name='Melhore a sugestao!')

        await interaction.followup.send(
            f'✅ Sua sugestao foi enviada para {canal_sugestoes.mention}!',
            ephemeral=True
        )
        logger.info(f'Sugestao de {interaction.user} ({interaction.user.id}) enviada em #{canal_sugestoes.name}')

    except Exception as e:
        logger.error(f'Erro no comando /sugerir: {e}', exc_info=True)
        await interaction.followup.send(
            f'❌ Ocorreu um erro ao enviar a sugestao: {str(e)}',
            ephemeral=True
        )


bot.run(BOT_TOKEN)
