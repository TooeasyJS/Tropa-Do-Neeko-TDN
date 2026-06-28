import discord
from discord.ext import tasks
import os
import googleapiclient.discovery
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY')
YOUTUBE_CHANNEL_HANDLE = 'canaldoneeko'
DISCORD_CHANNEL_ID = 1519006791864946728

intents = discord.Intents.default()
client = discord.Client(intents=intents)

youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

is_live = False
announced_video_id = None
youtube_channel_id = None


def get_youtube_channel_id():
    global youtube_channel_id
    if youtube_channel_id:
        return youtube_channel_id

    try:
        response = youtube.channels().list(
            part='id',
            forHandle=YOUTUBE_CHANNEL_HANDLE
        ).execute()

        if response.get('items'):
            youtube_channel_id = response['items'][0]['id']
            logger.info(f'Canal YouTube encontrado: {youtube_channel_id}')
        else:
            logger.error(f'Canal @{YOUTUBE_CHANNEL_HANDLE} nao encontrado')
    except Exception as e:
        logger.error(f'Erro ao buscar canal YouTube: {e}')

    return youtube_channel_id


@tasks.loop(minutes=2)
async def check_live():
    global is_live, announced_video_id

    try:
        channel_id = get_youtube_channel_id()
        if not channel_id:
            logger.error('ID do canal YouTube nao disponivel')
            return

        response = youtube.search().list(
            part='snippet',
            channelId=channel_id,
            eventType='live',
            type='video'
        ).execute()

        items = response.get('items', [])

        if items:
            video = items[0]
            video_id = video['id']['videoId']

            if not is_live or announced_video_id != video_id:
                is_live = True
                announced_video_id = video_id
                live_url = f'https://youtube.com/watch?v={video_id}'

                discord_channel = client.get_channel(DISCORD_CHANNEL_ID)
                if discord_channel:
                    message = (
                        f"🔴 ESSE GORDO TÁ AO VIVO AGORA! CORRE!!\n"
                        f"O Neeko começou uma LIVE! Vai perder não é?! @everyone :Olhar_de_mil_jardas:\n"
                        f"👉 {live_url}"
                    )
                    await discord_channel.send(message)
                    logger.info(f'Live anunciada: {live_url}')
                else:
                    logger.error(f'Canal Discord {DISCORD_CHANNEL_ID} nao encontrado')
            else:
                logger.info('Live ja anunciada, aguardando proxima...')
        else:
            if is_live:
                logger.info('Live encerrada. Resetando estado para proxima live.')
                is_live = False
                announced_video_id = None
            else:
                logger.info('Sem live no momento.')

    except Exception as e:
        logger.error(f'Erro ao verificar live: {e}')


@check_live.before_loop
async def before_check():
    await client.wait_until_ready()


@client.event
async def on_ready():
    logger.info(f'Bot {client.user} esta online e monitorando @{YOUTUBE_CHANNEL_HANDLE}!')
    check_live.start()


if not BOT_TOKEN:
    raise ValueError('BOT_TOKEN nao configurado nas variaveis de ambiente')

if not YOUTUBE_API_KEY:
    raise ValueError('YOUTUBE_API_KEY nao configurada nas variaveis de ambiente')

client.run(BOT_TOKEN)
