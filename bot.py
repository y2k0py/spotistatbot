import logging
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from spotipy.oauth2 import SpotifyOAuth
import spotipy
from aiogram.dispatcher.filters.state import State, StatesGroup
  # Assuming this is your module for SQLAlchemy User model
import config  # Replace this with environment variables
from sqlalchemy import Column, Integer, String, BigInteger
from sqlalchemy.orm import declarative_base


# Create a database engine and session
engine = create_engine('postgres://postgres:65*fc*gAcBff51CbGCDca5EcADBcGFeD@monorail.proxy.rlwy.net:11369/railway')
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()


class Users(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    spotify_token = Column(String(750), unique=True, nullable=False)
    telegram_code = Column(String(20), unique=True, nullable=False)
    telegram_user_id = Column(BigInteger, unique=True)

    def __repr__(self):
        return f'users {self.id}'



# Initialize the Spotify OAuth client
sp_oauth = SpotifyOAuth(
    client_id=config.CLIENT_ID,
    client_secret=config.CLIENT_SECRET,
    redirect_uri='http://spotistatbot.up.railway.app/redirect',
    scope="user-library-read user-top-read user-library-modify"
)

# Initialize the bot
bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)
dp.middleware.setup(LoggingMiddleware())

# Create reply keyboard markup
markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
item1 = KeyboardButton("Artists👤")
item2 = KeyboardButton("Tracks🎵")
markup.add(item1, item2)

# Inline keyboard buttons for time ranges
button_long_term = InlineKeyboardButton("ALL TIME", callback_data='long_term')
button_short_term = InlineKeyboardButton("MONTH", callback_data='short_term')
button_medium_term = InlineKeyboardButton("4 MONTH", callback_data='medium_term')

long_short = InlineKeyboardMarkup(row_width=2)
long_short.add(button_short_term, button_long_term)

short_medium = InlineKeyboardMarkup(row_width=2)
short_medium.add(button_short_term, button_medium_term)

medium_long = InlineKeyboardMarkup(row_width=2)
medium_long.add(button_medium_term, button_long_term)

# Remove keyboard markup
remove_markup = ReplyKeyboardRemove()

# States for FSM
class UserState(StatesGroup):
    type_info = State()

# Handle the start command
@dp.message_handler(Command('start'))
async def on_start(message: types.Message):
    link_code = message.get_args()
    if link_code:
        target = session.query(Users).filter_by(telegram_code=str(link_code)).first()
        if target:
            try:
                # Явно приведите telegram_user_id к строковому типу данных
                target.telegram_user_id = str(message.from_user.id)
                session.commit()
                await message.answer('Success authorization', reply_markup=markup)
            except Exception as e:
                await message.answer('Error occurred', reply_markup=markup)
                session.rollback()
                logging.error(str(e))
        else:
            await message.answer('User not found in the database')
    else:
        await message.answer('Hi, this is a bot to view your stats on Spotify. Follow this link to log in to Spotify: <a href="https://spotistatbot.up.railway.app/">LogIn</a>',parse_mode=ParseMode.HTML)


# Handle "Artists👤" button click
@dp.message_handler(lambda message: message.text == "Artists👤")
async def artists(message: types.Message, state: FSMContext):
    await state.update_data(type_info='artist')
    await message.answer(get_top_10(message.from_user.id, 'artist', 'medium_term'), parse_mode=ParseMode.HTML, reply_markup=long_short)

# Handle "Tracks🎵" button click
@dp.message_handler(lambda message: message.text == "Tracks🎵")
async def tracks(message: types.Message, state: FSMContext):
    await state.update_data(type_info='track')
    await message.answer(get_top_10(message.from_user.id, 'track', 'medium_term'), parse_mode=ParseMode.HTML, reply_markup=long_short)

# Callback handler for time range buttons
@dp.callback_query_handler(lambda c: c.data in ['long_term', 'medium_term', 'short_term'])
async def time_range_process(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    current_state = await state.get_data()
    type_info = current_state.get('type_info')

    if type_info not in ['artist', 'track']:
        await callback_query.answer('Invalid request')
        return

    time_range = callback_query.data
    stat = get_top_10(user_id, type_info, time_range)

    # Edit the message text and reply markup
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=stat,
        parse_mode=ParseMode.HTML,
    )

    if time_range == 'long_term':
        await bot.edit_message_reply_markup(chat_id=callback_query.message.chat.id,
                                            message_id=callback_query.message.message_id, reply_markup=short_medium)
    elif time_range == 'medium_term':
        await bot.edit_message_reply_markup(chat_id=callback_query.message.chat.id,
                                            message_id=callback_query.message.message_id, reply_markup=long_short)
    elif time_range == 'short_term':
        await bot.edit_message_reply_markup(chat_id=callback_query.message.chat.id,
                                            message_id=callback_query.message.message_id, reply_markup=medium_long)

# Function to get the top 10 artists or tracks
def get_top_10(telegram_user_id, type_info, time_range):
    user_sp_token = session.query(Users).filter_by(telegram_user_id=telegram_user_id).first()
    if not user_sp_token:
        return 'User not found'

    spotify_token_str = user_sp_token.spotify_token
    token = json.loads(spotify_token_str)

    if sp_oauth.is_token_expired(token):
        token_info = sp_oauth.refresh_access_token(token['refresh_token'])
        try:
            target = session.query(Users).filter_by(telegram_user_id=telegram_user_id).first()
            target.spotify_token = json.dumps(token_info)
            session.commit()
        except Exception as e:
            logging.error(str(e))
            return 'Error occurred'

        token = token_info

    sp = spotipy.Spotify(auth=token['access_token'])
    time_range_str = {
        'short_term': 'TOP FOR THE MONTH',
        'medium_term': 'TOP FOR THE 4 MONTH',
        'long_term': 'TOP FOR THE ALL TIME'
    }.get(time_range, 'Unknown')

    top_user = None
    emoji = None
    if type_info == 'artist':
        top_user = sp.current_user_top_artists(limit=10, time_range=time_range)
        emoji = "👤"
    elif type_info == 'track':
        top_user = sp.current_user_top_tracks(limit=10, time_range=time_range)
        emoji = "🎵"

    stat = f"<b>{time_range_str} {type_info.upper()}S {emoji}</b>:\n\n"
    for i, item in enumerate(top_user['items'], start=1):
        emoji = {
            1: "🥇TOP-1: ",
            2: "🥈TOP-2: ",
            3: "🥉TOP-3: ",
        }.get(i, "◾️")
        name = item['name']
        if type_info == 'track':
            artists = item['artists']
            artist_names = ', '.join([artist['name'] for artist in artists])
            # Проверяем, является ли трек нецензурным (explicit)
            is_explicit = item['explicit']
            if is_explicit:
                name = f"{name} 🅴"
            name = f"{name} - {artist_names}"

        if i <= 3:
            stat += f"{emoji}<b>{name}</b>\n"
        else:
            stat += f"{emoji}{name}\n"

    return stat


if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
