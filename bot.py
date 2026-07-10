import discord
from discord import app_commands
from discord.ext import commands
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
SUGESTOES_CHANNEL_ID = 1524644043316006983
GUILD_ID = 1323580646664441877
JOIN_TO_CREATE_ID = 1525225868949983262
TEMP_VOICE_CATEGORY_ID = 1525225870049153187
INTERFACE_CHANNEL_ID = 1525228538599444640

if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN nao configurado')

intents = discord.Intents.default()
intents.voice_states = True

temp_channels: dict[int, int] = {}
interface_messages: dict[int, int] = {}
vote_storage: dict[int, dict] = {}


def get_votes(message_id: int) -> dict:
    if message_id not in vote_storage:
        vote_storage[message_id] = {"aceitar": 0, "recusar": 0, "voters": {}}
    return vote_storage[message_id]


def get_user_temp_channel(guild: discord.Guild, user_id: int):
    for ch_id, owner_id in temp_channels.items():
        if owner_id == user_id:
            ch = guild.get_channel(ch_id)
            if ch:
                return ch
    return None


# ── MODAIS ───────────────────────────────────────────────────────

class RenameModal(discord.ui.Modal, title='✏️ Renomear Canal'):
    novo_nome = discord.ui.TextInput(
        label='Novo nome do canal',
        placeholder='Ex: Call dos Parceiros',
        max_length=100,
        min_length=1
    )

    def __init__(self, canal_id: int):
        super().__init__()
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        canal = interaction.guild.get_channel(self.canal_id)
        if canal:
            await canal.edit(name=str(self.novo_nome))
            await interaction.response.send_message(
                f'✅ Canal renomeado para **{self.novo_nome}**!', ephemeral=True
            )
        else:
            await interaction.response.send_message('❌ Canal não encontrado.', ephemeral=True)


class LimiteModal(discord.ui.Modal, title='👥 Limite de Membros'):
    limite = discord.ui.TextInput(
        label='Limite (0 = sem limite)',
        placeholder='Ex: 5  |  máx: 99',
        max_length=2
    )

    def __init__(self, canal_id: int):
        super().__init__()
        self.canal_id = canal_id

    async def on_submit(self, interaction: discord.Interaction):
        canal = interaction.guild.get_channel(self.canal_id)
        try:
            n = int(str(self.limite))
            if 0 <= n <= 99 and canal:
                await canal.edit(user_limit=n)
                msg = f'✅ Limite definido: **{n} membros**!' if n > 0 else '✅ Limite **removido**!'
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.response.send_message('❌ Digite entre 0 e 99.', ephemeral=True)
        except ValueError:
            await interaction.response.send_message('❌ Número inválido.', ephemeral=True)


# ── KICK SELECT ──────────────────────────────────────────────────

class KickUserSelect(discord.ui.UserSelect):
    def __init__(self, canal: discord.VoiceChannel):
        super().__init__(placeholder='Selecione quem expulsar...', min_values=1, max_values=1)
        self.canal = canal

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if member.voice and member.voice.channel and member.voice.channel.id == self.canal.id:
            await member.move_to(None)
            await interaction.response.send_message(
                f'👢 **{member.display_name}** foi expulso do canal!', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f'❌ **{member.display_name}** não está no seu canal.', ephemeral=True
            )


class KickSelectView(discord.ui.View):
    def __init__(self, canal: discord.VoiceChannel):
        super().__init__(timeout=30)
        self.add_item(KickUserSelect(canal))


# ── INTERFACE VIEW (PERSISTENTE) ─────────────────────────────────

class InterfaceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _get_canal(self, interaction: discord.Interaction):
        canal = get_user_temp_channel(interaction.guild, interaction.user.id)
        if not canal:
            await interaction.response.send_message(
                '❌ Você não tem um canal ativo!\n'
                'Entre em **➕ Entrar para Criar** para criar o seu.',
                ephemeral=True
            )
        return canal

    @discord.ui.button(label='✏️ Nome', style=discord.ButtonStyle.secondary, custom_id='tv_btn_nome', row=0)
    async def btn_nome(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_modal(RenameModal(canal.id))

    @discord.ui.button(label='👥 Limite', style=discord.ButtonStyle.secondary, custom_id='tv_btn_limite', row=0)
    async def btn_limite(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_modal(LimiteModal(canal.id))

    @discord.ui.button(label='🔒 Privacidade', style=discord.ButtonStyle.secondary, custom_id='tv_btn_privacy', row=0)
    async def btn_privacy(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            everyone = interaction.guild.default_role
            overwrites = dict(canal.overwrites)
            current = overwrites.get(everyone)
            locked = current is not None and current.connect is False
            if locked:
                overwrites[everyone] = discord.PermissionOverwrite(connect=True)
                await canal.edit(overwrites=overwrites)
                await interaction.response.send_message(
                    '🔓 Canal **desbloqueado**! Todos podem entrar.', ephemeral=True
                )
            else:
                overwrites[everyone] = discord.PermissionOverwrite(connect=False)
                await canal.edit(overwrites=overwrites)
                await interaction.response.send_message(
                    '🔒 Canal **bloqueado**! Só convidados entram.', ephemeral=True
                )

    @discord.ui.button(label='👢 Kick', style=discord.ButtonStyle.danger, custom_id='tv_btn_kick', row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            others = [m for m in canal.members if m.id != interaction.user.id]
            if not others:
                await interaction.response.send_message(
                    '❌ Ninguém mais no canal para expulsar.', ephemeral=True
                )
                return
            view = KickSelectView(canal)
            await interaction.response.send_message(
                '👢 Selecione quem expulsar:', view=view, ephemeral=True
            )

    @discord.ui.button(label='🗑️ Deletar', style=discord.ButtonStyle.danger, custom_id='tv_btn_delete', row=1)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message('✅ Canal deletado!', ephemeral=True)
            canal_id = canal.id
            if canal_id in temp_channels:
                del temp_channels[canal_id]
            if canal_id in interface_messages:
                try:
                    iface_ch = interaction.guild.get_channel(INTERFACE_CHANNEL_ID)
                    if iface_ch:
                        old_msg = await iface_ch.fetch_message(interface_messages[canal_id])
                        await old_msg.delete()
                except Exception:
                    pass
                del interface_messages[canal_id]
            await canal.delete(reason=f'Deletado pelo dono {interaction.user}')


# ── SUGESTÃO VIEW (PERSISTENTE) ──────────────────────────────────

class SugestaoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label='Aceitar (0)', style=discord.ButtonStyle.success,
        custom_id='tdn_btn_aceitar', emoji='✅'
    )
    async def btn_aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_vote(interaction, 'aceitar')

    @discord.ui.button(
        label='Recusar (0)', style=discord.ButtonStyle.danger,
        custom_id='tdn_btn_recusar', emoji='❌'
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
                await interaction.response.send_message(
                    '⚠️ Você já votou nessa opção! Clique no outro botão para trocar seu voto.',
                    ephemeral=True
                )
                return

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


# ── BOT ──────────────────────────────────────────────────────────

class TDNBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        self.add_view(SugestaoView())
        self.add_view(InterfaceView())
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

    async def on_voice_state_update(
        self, member: discord.Member,
        before: discord.VoiceState, after: discord.VoiceState
    ):
        try:
            if after.channel and after.channel.id == JOIN_TO_CREATE_ID:
                category = member.guild.get_channel(TEMP_VOICE_CATEGORY_ID)
                novo_canal = await member.guild.create_voice_channel(
                    name=f'🎙️ {member.display_name}',
                    category=category,
                    bitrate=64000
                )
                temp_channels[novo_canal.id] = member.id
                await member.move_to(novo_canal)

                iface_channel = member.guild.get_channel(INTERFACE_CHANNEL_ID)
                if iface_channel:
                    embed = discord.Embed(
                        title='🎙️ Painel do Canal',
                        description=(
                            f'{member.mention}, seu canal foi criado!\n'
                            'Use os botões abaixo para gerenciá-lo.'
                        ),
                        color=discord.Color.blurple()
                    )
                    embed.add_field(name='Canal', value=novo_canal.mention, inline=True)
                    embed.add_field(name='Dono', value=member.mention, inline=True)
                    embed.add_field(
                        name='Botões disponíveis',
                        value=(
                            '✏️ **Nome** — renomear o canal\n'
                            '👥 **Limite** — limitar vagas\n'
                            '🔒 **Privacidade** — bloquear/desbloquear\n'
                            '👢 **Kick** — expulsar alguém\n'
                            '🗑️ **Deletar** — encerrar o canal'
                        ),
                        inline=False
                    )
                    embed.set_footer(text='Somente o dono do canal pode usar os botões')
                    msg = await iface_channel.send(embed=embed, view=InterfaceView())
                    interface_messages[novo_canal.id] = msg.id

                logger.info(f'Canal temp criado: {novo_canal.name} (ID: {novo_canal.id}) para {member}')

            if before.channel and before.channel.id in temp_channels:
                canal = before.channel
                if len(canal.members) == 0:
                    canal_id = canal.id
                    if canal_id in interface_messages:
                        try:
                            iface_ch = member.guild.get_channel(INTERFACE_CHANNEL_ID)
                            if iface_ch:
                                old_msg = await iface_ch.fetch_message(interface_messages[canal_id])
                                await old_msg.delete()
                        except Exception:
                            pass
                        del interface_messages[canal_id]
                    del temp_channels[canal_id]
                    await canal.delete(reason='Canal temporário vazio')
                    logger.info(f'Canal temp deletado: {canal.name}')

        except Exception as e:
            logger.error(f'Erro no TempVoice: {e}', exc_info=True)


bot = TDNBot()


@bot.tree.command(name='sugerir', description='Envie uma sugestao para o servidor!')
@app_commands.describe(mensagem='Escreva sua sugestao aqui')
async def sugerir(interaction: discord.Interaction, mensagem: str):
    await interaction.response.defer(ephemeral=True)
    try:
        canal_sugestoes = interaction.guild.get_channel(SUGESTOES_CHANNEL_ID)
        if canal_sugestoes is None:
            await interaction.followup.send('❌ Canal de sugestoes nao encontrado.', ephemeral=True)
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
            f'✅ Sua sugestao foi enviada para {canal_sugestoes.mention}!', ephemeral=True
        )
        logger.info(f'Sugestao de {interaction.user} enviada (msg id: {msg.id})')

    except Exception as e:
        logger.error(f'Erro no /sugerir: {e}', exc_info=True)
        try:
            await interaction.followup.send(f'❌ Erro: {str(e)}', ephemeral=True)
        except Exception:
            pass


bot.run(BOT_TOKEN)
