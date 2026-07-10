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

temp_channels: dict[int, int] = {}       # {channel_id: owner_user_id}
interface_messages: dict[int, int] = {}  # {temp_channel_id: interface_message_id}
waiting_rooms: dict[int, int] = {}       # {temp_channel_id: waiting_room_channel_id}
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
        max_length=100, min_length=1
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
                msg = f'✅ Limite: **{n} membros**!' if n > 0 else '✅ Limite **removido**!'
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.response.send_message('❌ Digite entre 0 e 99.', ephemeral=True)
        except ValueError:
            await interaction.response.send_message('❌ Número inválido.', ephemeral=True)


# ── SELECTS PARA TRUST / UNTRUST ─────────────────────────────────

class TrustUserSelect(discord.ui.UserSelect):
    def __init__(self, canal: discord.VoiceChannel, action: str):
        placeholder = 'Selecione quem confiar...' if action == 'trust' else 'Selecione quem desconfiar...'
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.canal = canal
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        overwrites = dict(self.canal.overwrites)
        if self.action == 'trust':
            overwrites[member] = discord.PermissionOverwrite(connect=True, view_channel=True)
            await self.canal.edit(overwrites=overwrites)
            await interaction.response.send_message(
                f'🤝 **{member.display_name}** agora é de confiança e pode entrar mesmo bloqueado!',
                ephemeral=True
            )
        else:
            if member in overwrites:
                del overwrites[member]
                await self.canal.edit(overwrites=overwrites)
            await interaction.response.send_message(
                f'🚫 **{member.display_name}** removido da lista de confiança.', ephemeral=True
            )


class TrustView(discord.ui.View):
    def __init__(self, canal: discord.VoiceChannel, action: str):
        super().__init__(timeout=30)
        self.add_item(TrustUserSelect(canal, action))


# ── SELECTS PARA BLOCK / UNBLOCK ─────────────────────────────────

class BlockUserSelect(discord.ui.UserSelect):
    def __init__(self, canal: discord.VoiceChannel, action: str):
        placeholder = 'Selecione quem bloquear...' if action == 'block' else 'Selecione quem desbloquear...'
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.canal = canal
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        overwrites = dict(self.canal.overwrites)
        if self.action == 'block':
            if member.voice and member.voice.channel == self.canal:
                await member.move_to(None)
            overwrites[member] = discord.PermissionOverwrite(connect=False, view_channel=False)
            await self.canal.edit(overwrites=overwrites)
            await interaction.response.send_message(
                f'🚷 **{member.display_name}** foi bloqueado do canal!', ephemeral=True
            )
        else:
            if member in overwrites:
                del overwrites[member]
                await self.canal.edit(overwrites=overwrites)
            await interaction.response.send_message(
                f'✅ **{member.display_name}** foi desbloqueado!', ephemeral=True
            )


class BlockView(discord.ui.View):
    def __init__(self, canal: discord.VoiceChannel, action: str):
        super().__init__(timeout=30)
        self.add_item(BlockUserSelect(canal, action))


# ── SELECT PARA KICK ─────────────────────────────────────────────

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


# ── SELECT PARA TRANSFERIR ───────────────────────────────────────

class TransferUserSelect(discord.ui.UserSelect):
    def __init__(self, canal: discord.VoiceChannel):
        super().__init__(placeholder='Selecione o novo dono...', min_values=1, max_values=1)
        self.canal = canal

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if member.id == interaction.user.id:
            await interaction.response.send_message('❌ Você já é o dono!', ephemeral=True)
            return
        temp_channels[self.canal.id] = member.id
        await interaction.response.send_message(
            f'🔄 Canal transferido para **{member.mention}**! Ele agora é o dono.', ephemeral=True
        )
        logger.info(f'Canal {self.canal.name} transferido para {member}')


class TransferView(discord.ui.View):
    def __init__(self, canal: discord.VoiceChannel):
        super().__init__(timeout=30)
        self.add_item(TransferUserSelect(canal))


# ── SELECT PARA REGIÃO ───────────────────────────────────────────

class RegionSelect(discord.ui.Select):
    def __init__(self, canal: discord.VoiceChannel):
        options = [
            discord.SelectOption(label='🌐 Automático', value='auto', description='Deixa o Discord escolher'),
            discord.SelectOption(label='🇧🇷 Brasil', value='brazil', description='São Paulo'),
            discord.SelectOption(label='🇺🇸 US Leste', value='us-east'),
            discord.SelectOption(label='🇺🇸 US Sul', value='us-south'),
            discord.SelectOption(label='🇺🇸 US Oeste', value='us-west'),
            discord.SelectOption(label='🇺🇸 US Central', value='us-central'),
            discord.SelectOption(label='🇪🇺 Europa', value='europe'),
            discord.SelectOption(label='🇸🇬 Singapura', value='singapore'),
            discord.SelectOption(label='🇯🇵 Japão', value='japan'),
            discord.SelectOption(label='🇦🇺 Sydney', value='sydney'),
            discord.SelectOption(label='🇿🇦 África do Sul', value='southafrica'),
            discord.SelectOption(label='🇮🇳 Índia', value='india'),
        ]
        super().__init__(placeholder='Selecione a região de voz...', options=options)
        self.canal = canal

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        region = None if value == 'auto' else value
        await self.canal.edit(rtc_region=region)
        label = next(o.label for o in self.options if o.value == value)
        await interaction.response.send_message(
            f'🌍 Região alterada para **{label}**!', ephemeral=True
        )


class RegionView(discord.ui.View):
    def __init__(self, canal: discord.VoiceChannel):
        super().__init__(timeout=30)
        self.add_item(RegionSelect(canal))


# ── INTERFACE VIEW (PERSISTENTE) — 15 BOTÕES ─────────────────────

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

    # ── ROW 0 ──────────────────────────────────────────────────
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
            current = overwrites.get(everyone, discord.PermissionOverwrite())
            pair = current.pair()
            new_ow = discord.PermissionOverwrite.from_pair(pair[0], pair[1])
            locked = pair[1].connect  # True if connect is denied
            if locked:
                new_ow.connect = None
                await canal.edit(overwrites={**overwrites, everyone: new_ow})
                await interaction.response.send_message('🔓 Canal **desbloqueado**! Todos podem entrar.', ephemeral=True)
            else:
                new_ow.connect = False
                await canal.edit(overwrites={**overwrites, everyone: new_ow})
                await interaction.response.send_message('🔒 Canal **bloqueado**! Só convidados entram.', ephemeral=True)

    @discord.ui.button(label='⏳ Sala Espera', style=discord.ButtonStyle.secondary, custom_id='tv_btn_waiting', row=0)
    async def btn_waiting(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            if canal.id in waiting_rooms:
                wr_ch = interaction.guild.get_channel(waiting_rooms[canal.id])
                if wr_ch:
                    await wr_ch.delete(reason='Sala de espera desativada')
                del waiting_rooms[canal.id]
                await interaction.response.send_message('✅ Sala de espera **desativada**!', ephemeral=True)
            else:
                category = interaction.guild.get_channel(TEMP_VOICE_CATEGORY_ID)
                wr = await interaction.guild.create_voice_channel(
                    name=f'⏳ Espera — {interaction.user.display_name}',
                    category=category
                )
                waiting_rooms[canal.id] = wr.id
                everyone = interaction.guild.default_role
                overwrites = dict(canal.overwrites)
                current = overwrites.get(everyone, discord.PermissionOverwrite())
                pair = current.pair()
                new_ow = discord.PermissionOverwrite.from_pair(pair[0], pair[1])
                new_ow.connect = False
                await canal.edit(overwrites={**overwrites, everyone: new_ow})
                await interaction.response.send_message(
                    f'⏳ Sala de espera criada: {wr.mention}\n'
                    'Membros aguardarão lá até você convidá-los com **📨 Convidar**.',
                    ephemeral=True
                )

    @discord.ui.button(label='💬 Chat', style=discord.ButtonStyle.secondary, custom_id='tv_btn_chat', row=0)
    async def btn_chat(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            everyone = interaction.guild.default_role
            overwrites = dict(canal.overwrites)
            current = overwrites.get(everyone, discord.PermissionOverwrite())
            pair = current.pair()
            new_ow = discord.PermissionOverwrite.from_pair(pair[0], pair[1])
            chat_denied = pair[1].send_messages
            if chat_denied:
                new_ow.send_messages = None
                await canal.edit(overwrites={**overwrites, everyone: new_ow})
                await interaction.response.send_message('💬 Chat **ativado** no canal de voz!', ephemeral=True)
            else:
                new_ow.send_messages = False
                await canal.edit(overwrites={**overwrites, everyone: new_ow})
                await interaction.response.send_message('🔇 Chat **desativado** no canal de voz!', ephemeral=True)

    # ── ROW 1 ──────────────────────────────────────────────────
    @discord.ui.button(label='🤝 Confiar', style=discord.ButtonStyle.success, custom_id='tv_btn_trust', row=1)
    async def btn_trust(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '🤝 Selecione quem confiar (pode entrar mesmo bloqueado):',
                view=TrustView(canal, 'trust'), ephemeral=True
            )

    @discord.ui.button(label='🚫 Desconfiar', style=discord.ButtonStyle.secondary, custom_id='tv_btn_untrust', row=1)
    async def btn_untrust(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '🚫 Selecione quem remover da confiança:',
                view=TrustView(canal, 'untrust'), ephemeral=True
            )

    @discord.ui.button(label='📨 Convidar', style=discord.ButtonStyle.secondary, custom_id='tv_btn_invite', row=1)
    async def btn_invite(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            invite = await canal.create_invite(max_age=3600, max_uses=10, reason='Convite TempVoice')
            await interaction.response.send_message(
                f'📨 **Link de convite** para seu canal (válido 1h / 10 usos):\n{invite.url}',
                ephemeral=True
            )

    @discord.ui.button(label='👢 Kick', style=discord.ButtonStyle.danger, custom_id='tv_btn_kick', row=1)
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            others = [m for m in canal.members if m.id != interaction.user.id]
            if not others:
                await interaction.response.send_message('❌ Ninguém mais no canal para expulsar.', ephemeral=True)
                return
            await interaction.response.send_message(
                '👢 Selecione quem expulsar:', view=KickSelectView(canal), ephemeral=True
            )

    @discord.ui.button(label='🌍 Região', style=discord.ButtonStyle.secondary, custom_id='tv_btn_region', row=1)
    async def btn_region(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '🌍 Selecione a região de voz:', view=RegionView(canal), ephemeral=True
            )

    # ── ROW 2 ──────────────────────────────────────────────────
    @discord.ui.button(label='🚷 Bloquear', style=discord.ButtonStyle.danger, custom_id='tv_btn_block', row=2)
    async def btn_block(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '🚷 Selecione quem bloquear do canal:', view=BlockView(canal, 'block'), ephemeral=True
            )

    @discord.ui.button(label='✅ Desbloquear', style=discord.ButtonStyle.success, custom_id='tv_btn_unblock', row=2)
    async def btn_unblock(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '✅ Selecione quem desbloquear:', view=BlockView(canal, 'unblock'), ephemeral=True
            )

    @discord.ui.button(label='👑 Reivindicar', style=discord.ButtonStyle.secondary, custom_id='tv_btn_claim', row=2)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        claimed = None
        for ch_id, owner_id in list(temp_channels.items()):
            if owner_id == interaction.user.id:
                await interaction.response.send_message(
                    '❌ Você já é dono de um canal!', ephemeral=True
                )
                return
            ch = interaction.guild.get_channel(ch_id)
            if not ch:
                continue
            if interaction.user not in ch.members:
                continue
            owner = interaction.guild.get_member(owner_id)
            if owner is None or owner.voice is None or owner.voice.channel != ch:
                claimed = (ch_id, ch)
                break

        if claimed:
            ch_id, ch = claimed
            temp_channels[ch_id] = interaction.user.id
            await interaction.response.send_message(
                f'👑 Você agora é o dono do canal **{ch.name}**!', ephemeral=True
            )
        else:
            await interaction.response.send_message(
                '❌ Nenhum canal para reivindicar.\n'
                'O dono ainda está no canal ou você não está em nenhum canal temporário.',
                ephemeral=True
            )

    @discord.ui.button(label='🔄 Transferir', style=discord.ButtonStyle.secondary, custom_id='tv_btn_transfer', row=2)
    async def btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message(
                '🔄 Selecione o novo dono do canal:', view=TransferView(canal), ephemeral=True
            )

    @discord.ui.button(label='🗑️ Deletar', style=discord.ButtonStyle.danger, custom_id='tv_btn_delete', row=2)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        canal = await self._get_canal(interaction)
        if canal:
            await interaction.response.send_message('✅ Canal deletado!', ephemeral=True)
            canal_id = canal.id
            if canal_id in waiting_rooms:
                wr = interaction.guild.get_channel(waiting_rooms[canal_id])
                if wr:
                    await wr.delete(reason='Canal principal deletado')
                del waiting_rooms[canal_id]
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
            # Entrou no canal "Entrar para Criar"
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
                        name='O que cada botão faz',
                        value=(
                            '✏️ **Nome** — renomear  •  👥 **Limite** — limitar vagas\n'
                            '🔒 **Privacidade** — bloquear/abrir  •  ⏳ **Sala Espera** — fila de espera\n'
                            '💬 **Chat** — ativar/desativar chat\n'
                            '🤝 **Confiar** — dar acesso  •  🚫 **Desconfiar** — remover acesso\n'
                            '📨 **Convidar** — gerar link  •  👢 **Kick** — expulsar\n'
                            '🌍 **Região** — trocar região de voz\n'
                            '🚷 **Bloquear** — banir do canal  •  ✅ **Desbloquear** — remover ban\n'
                            '👑 **Reivindicar** — assumir canal sem dono\n'
                            '🔄 **Transferir** — passar dono  •  🗑️ **Deletar** — encerrar'
                        ),
                        inline=False
                    )
                    embed.set_footer(text='Somente o dono do canal pode usar os botões')
                    msg = await iface_channel.send(embed=embed, view=InterfaceView())
                    interface_messages[novo_canal.id] = msg.id

                logger.info(f'Canal temp criado: {novo_canal.name} (ID: {novo_canal.id}) para {member}')

            # Saiu de um canal temporário
            if before.channel and before.channel.id in temp_channels:
                canal = before.channel

                # Lógica de sala de espera: mover não-confiáveis para espera
                if after.channel and after.channel.id in temp_channels:
                    ch_id = after.channel.id
                    if ch_id in waiting_rooms:
                        owner_id = temp_channels.get(ch_id)
                        if member.id != owner_id:
                            ow = after.channel.overwrites_for(member)
                            if ow.connect is not True:
                                wr_ch = member.guild.get_channel(waiting_rooms[ch_id])
                                if wr_ch:
                                    await member.move_to(wr_ch)

                if len(canal.members) == 0:
                    canal_id = canal.id
                    if canal_id in waiting_rooms:
                        wr = member.guild.get_channel(waiting_rooms[canal_id])
                        if wr:
                            await wr.delete(reason='Canal principal vazio')
                        del waiting_rooms[canal_id]
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
