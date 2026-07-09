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
    raise ValueError('BOT_TOKEN nao configurado')

intents = discord.Intents.default()

# Armazena votos por mensagem: {message_id: {"aceitar": int, "recusar": int, "voters": {user_id: "aceitar"|"recusar"}}}
vote_storage: dict[int, dict] = {}


def get_votes(message_id: int) -> dict:
    if message_id not in vote_storage:
        vote_storage[message_id] = {"aceitar": 0, "recusar": 0, "voters": {}}
    return vote_storage[message_id]


class SugestaoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Aceitar (0)',
        style=discord.ButtonStyle.success,
        custom_id='tdn_btn_aceitar',
        emoji='✅'
    )
    async def btn_aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, 'aceitar')

    @discord.ui.button(
        label='Recusar (0)',
        style=discord.ButtonStyle.danger,
        custom_id='tdn_btn_recusar',
        emoji='❌'
    )
    async def btn_recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, 'recusar')

    async def _handle_vote(self, interaction: discord.Interaction, vote_type: str):
        try:
            msg_id = interaction.message.id
            user_id = interaction.user.id
            data = get_votes(msg_id)
            previous = data['voters'].get(user_id)

            if previous == vote_type:
                data[vote_type] -= 1
                del data['voters'][user_id]
            else:
                if previous:
                    data[previous] -= 1
                data[vote_type] += 1
                data['voters'][user_id] = vote_type

            view = SugestaoView()
            for child in view.children:
                if isinstance(child, discord.ui.Button):
                    if child.custom_id == 'tdn_btn_aceitar':
                        child.label = f'Aceitar ({data["aceitar"]})'
                    elif child.custom_id == 'tdn_btn_recusar':
                        child.label = f'Recusar ({data["recusar"]})'

            await interaction.response.edit_message(view=view)

        except Exception as e:
            logger.error(f'Erro ao votar: {e}', exc_info=True)
            try:
                await interaction.response.send_message('❌ Erro ao registrar voto.', ephemeral=True)
            except Exception:
                pass


class TDNBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        self.add_view(SugestaoView())

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


@bot.tree.command(name='sugerir', description='Envie uma sugestao para o servidor!')
@app_commands.describe(mensagem='Escreva sua sugestao aqui')
async def sugerir(interaction: discord.Interaction, mensagem: str):
    await interaction.response.defer(ephemeral=True)

    try:
        canal_sugestoes = interaction.guild.get_channel(SUGESTOES_CHANNEL_ID)

        if canal_sugestoes is None:
            await interaction.followup.send(
                '❌ Canal de sugestoes nao encontrado.',
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

        vote_storage[msg.id] = {"aceitar": 0, "recusar": 0, "voters": {}}

        await msg.create_thread(name='Melhore a sugestao!')

        await interaction.followup.send(
            f'✅ Sua sugestao foi enviada para {canal_sugestoes.mention}!',
            ephemeral=True
        )
        logger.info(f'Sugestao de {interaction.user} enviada (msg id: {msg.id})')

    except Exception as e:
        logger.error(f'Erro no /sugerir: {e}', exc_info=True)
        try:
            await interaction.followup.send(f'❌ Erro: {str(e)}', ephemeral=True)
        except Exception:
            pass


bot.run(BOT_TOKEN)
