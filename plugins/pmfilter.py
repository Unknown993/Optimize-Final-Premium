import json
from utils import get_size, format_clean_file_item, get_display_name, is_subscribed, is_req_subscribed, group_setting_buttons, get_poster, get_posterx, temp, get_settings, save_group_settings, get_cap, imdb, is_check_admin, extract_request_content, log_error, clean_filename, generate_season_variations, clean_search_text
from fuzzywuzzy import process
from dreamxbotz.util.file_properties import get_name, get_hash
from urllib.parse import quote_plus
import logging
from database.ia_filterdb import Media, Media2, get_file_details, get_search_results, get_bad_files
from database.config_db import mdb
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid, ChatAdminRequired, UserNotParticipant
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, WebAppInfo
from info import *
from Script import script
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from database.refer import referdb
from database.users_chats_db import db
import asyncio
import re
import math
import random
import pytz
from datetime import datetime, timedelta
lock = asyncio.Lock()

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)


TIMEZONE = "Asia/Kolkata"
from database.ia_filterdb import cache_set_field, cache_get_field, cache_save_getall, cache_get_getall, drop_fts_catalog, delete_from_fts
from database.search_engine import (
    GLOBAL_SESSION_MANAGER,
    parse_user_query,
    canonicalize_language,
    canonicalize_quality,
    LANGUAGE_MAP,
    QUALITY_MAP,
    UNIVERSAL_AUDIO_TAGS,
    build_pagination_row,
    format_button_label,
)

class PersistentDict(dict):
    """Thread-safe dictionary backed by SQLite for zero cache-loss across bot reboots."""
    def __init__(self, field_name):
        super().__init__()
        self.field_name = field_name

    def __getitem__(self, key):
        if key in self:
            return super().__getitem__(key)
        val = cache_get_field(str(key), self.field_name)
        if val is not None:
            super().__setitem__(key, val)
            return val
        raise KeyError(key)

    def get(self, key, default=None):
        if key in self:
            return super().get(key, default)
        val = cache_get_field(str(key), self.field_name)
        if val is not None:
            super().__setitem__(key, val)
            return val
        return default

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        cache_set_field(str(key), self.field_name, str(value))


# Improvement 2: Smart Aliases for Quality & Language
QUALITY_ALIASES = {
    "1080p": ["1080p", "1080", "fhd", "full hd"],
    "720p": ["720p", "720", "hd"],
    "480p": ["480p", "480", "sd"],
    "2160p": ["2160p", "2160", "4k", "uhd"],
    "4k": ["4k", "2160p", "2160", "uhd"],
    "360p": ["360p", "360"],
    "1440p": ["1440p", "1440", "2k"]
}

LANGUAGE_ALIASES = {
    "hin": ["hindi", "hin", "dual", "multi"],
    "hindi": ["hindi", "hin", "dual", "multi"],
    "eng": ["english", "eng", "dual", "multi"],
    "english": ["english", "eng", "dual", "multi"],
    "tam": ["tamil", "tam", "dual", "multi"],
    "tamil": ["tamil", "tam", "dual", "multi"],
    "tel": ["telugu", "tel", "dual", "multi"],
    "telugu": ["telugu", "tel", "dual", "multi"],
    "mal": ["malayalam", "mal", "dual", "multi"],
    "malayalam": ["malayalam", "mal", "dual", "multi"],
    "kan": ["kannada", "kan", "dual", "multi"],
    "kannada": ["kannada", "kan", "dual", "multi"],
    "ben": ["bengali", "ben"],
    "bengali": ["bengali", "ben"],
    "mar": ["marathi", "mar"],
    "marathi": ["marathi", "mar"],
    "guj": ["gujarati", "guj"],
    "gujarati": ["gujarati", "guj"],
    "punj": ["punjabi", "punj", "pb"],
    "punjabi": ["punjabi", "punj", "pb"],
    "urdu": ["urdu"]
}



# Conversational Greeting & Chat Filter Blocklist
CHAT_IGNORE_WORDS = frozenset({
    "hi", "hello", "helo", "hey", "hii", "hiii", "hlo", "hlw", "yo", "sup",
    "gm", "gn", "ga", "ge", "good morning", "good night", "good evening", "good afternoon",
    "bye", "tata", "cya", "see you", "tc", "take care",
    "ok", "okay", "okk", "k", "kk", "done", "alright", "fine", "yep", "yes", "no", "nah",
    "thanks", "thank you", "thx", "tq", "dhanyawad", "shukriya", "welcome", "wc",
    "pls", "plz", "please", "help", "admin", "owner", "mod",
    "how are you", "how r u", "kya haal", "kya haal hai", "sab badhiya",
    "lol", "lmao", "rofl", "haha", "hahaha", "xd",
    "nice", "super", "cool", "great", "awesome", "mast", "badhiya", "op",
    "bro", "bhai", "bhaiya", "yaar", "yr", "buddy", "dude", "sir", "mam", "boss",
    "kaise ho", "kya hua", "kaha ho", "kya kar rahe ho", "kuch nahi", "kuch nhi",
    "bolo", "haan", "han", "nahi", "nhi", "sahi hai", "theek hai", "thik hai"
})

CHAT_SINGLE_WORDS = frozenset({
    "hi", "hello", "helo", "hey", "hii", "hiii", "hlo", "hlw", "yo", "sup",
    "gm", "gn", "bye", "tata", "cya", "tc", "ok", "okay", "okk", "k", "kk",
    "done", "fine", "yep", "yes", "no", "nah", "thanks", "thx", "tq", "welcome",
    "wc", "pls", "plz", "please", "help", "admin", "owner", "mod", "lol", "lmao",
    "rofl", "haha", "hahaha", "xd", "nice", "super", "cool", "great", "awesome",
    "mast", "op", "bro", "bhai", "bhaiya", "yaar", "yr", "buddy", "dude", "sir",
    "mam", "boss", "bolo", "haan", "han", "nahi", "nhi"
})

def is_conversational_chat(text: str) -> bool:
    if not text:
        return True
    clean = re.sub(r"[^\w\s]", "", text.strip().lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return True
    if clean in CHAT_IGNORE_WORDS:
        return True
    if len(clean) <= 2 and clean not in {"4k", "2k", "3d", "hd", "sd"}:
        return True
    words = clean.split()
    if words and all(w in CHAT_SINGLE_WORDS for w in words):
        return True
    return False

def format_button_label(file_name: str, file_size: int, max_len: int = 58) -> str:
    """Format file button: [{size}] {clean_title} cleanly without artificial badge bloat."""
    fn = str(file_name or "").strip()
    size_str = get_size(file_size)
    prefix = f"[{size_str}]"
    avail = max_len - len(prefix) - 1
    if avail > 5 and len(fn) > avail:
        fn = fn[:avail - 1].rstrip() + "…"
    return f"{prefix} {fn}".strip()

import itertools
ACTIVE_FILTERS = {}

def get_active_filters(key: str) -> dict:
    if key in ACTIVE_FILTERS:
        return ACTIVE_FILTERS[key]
    val = cache_get_field(str(key), "active_filters")
    if val and val.startswith("{") and val.endswith("}"):
        try:
            d = json.loads(val)
            ACTIVE_FILTERS[key] = d
            return d
        except Exception:
            pass
    return {}

def set_active_filter(key: str, filter_type: str, value: str):
    f = get_active_filters(key).copy()
    if value == "homepage" or value is None:
        f.pop(filter_type, None)
    else:
        if filter_type == "quality":
            f[filter_type] = canonicalize_quality(value) or value
        elif filter_type == "language":
            f[filter_type] = canonicalize_language(value) or value
        else:
            f[filter_type] = value
    ACTIVE_FILTERS[key] = f
    cache_set_field(str(key), "active_filters", json.dumps(f))
    sess = GLOBAL_SESSION_MANAGER.get(key)
    if sess:
        sess.set_filter(filter_type, value)
    return f

def clear_active_filters(key: str):
    ACTIVE_FILTERS.pop(key, None)
    cache_set_field(str(key), "active_filters", "{}")
    sess = GLOBAL_SESSION_MANAGER.get(key)
    if sess:
        sess.reset_filters()

def get_filter_chip_label(active_filters: dict) -> str:
    chips = []
    if "season" in active_filters:
        chips.append(f"S{int(active_filters['season']):02d}")
    if "quality" in active_filters:
        chips.append(active_filters["quality"].upper())
    if "language" in active_filters:
        chips.append(active_filters["language"].title())
    return " • ".join(chips) if chips else None

def build_empty_filter_buttons(key: str, active_filter: str = None):
    """Build persistent filter control bar when a filter yields 0 results."""
    btn = []
    if active_filter:
        btn.append([
            InlineKeyboardButton(f"🎯 Filter: {active_filter}", callback_data=f"filter_info#{active_filter}"),
            InlineKeyboardButton("🔄 Reset Filters", callback_data=f"reset_filter#{key}")
        ])
    else:
        btn.append([
            InlineKeyboardButton("🔄 Reset Filters", callback_data=f"reset_filter#{key}")
        ])
    btn.append([
        InlineKeyboardButton("Qᴜᴀʟɪᴛʏ", callback_data=f"qualities#{key}"),
        InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"languages#{key}"),
        InlineKeyboardButton("Sᴇᴀsᴏɴ",  callback_data=f"seasons#{key}")
    ])
    btn.append([
        InlineKeyboardButton("↭ ɴᴏ ʀᴇsᴜʟᴛs ꜰᴏᴜɴᴅ ↭", callback_data="pages")
    ])
    return btn

def build_combined_filter_queries(base_search: str, filters_dict: dict):
    if not filters_dict:
        return base_search
    q_aliases = [None]
    if "quality" in filters_dict:
        q_val = filters_dict["quality"].lower()
        q_aliases = QUALITY_ALIASES.get(q_val, [q_val])
    l_aliases = [None]
    if "language" in filters_dict:
        l_val = filters_dict["language"].lower()
        l_aliases = LANGUAGE_ALIASES.get(l_val, [l_val])
    s_variations = [None]
    if "season" in filters_dict:
        s_num = int(filters_dict["season"])
        s_variations = [f"s{s_num:02d}", f"s{s_num}", f"season {s_num}", f"season {s_num:02d}"]
    combinations = itertools.product(q_aliases, l_aliases, s_variations)
    queries = []
    for q, l, s in combinations:
        tokens = [base_search]
        if s: tokens.append(s)
        if q: tokens.append(q)
        if l: tokens.append(l)
        queries.append(" ".join(tokens))
    return queries

def build_search_buttons(files, key, offset=0, total_results=0, req=0, settings=None, active_filter=None, current_offset=None):
    """Build uniform search results using unified engine button builder."""
    from database.search_engine import build_search_buttons as _engine_build
    return _engine_build(
        files=files,
        key=key,
        offset=offset,
        total_results=total_results,
        req=req,
        settings=settings or {},
        active_filter=active_filter,
        button_cls=InlineKeyboardButton,
        bot_username=temp.U_NAME or "bot",
        current_offset=current_offset
    )

BUTTON = {}
BUTTONS = PersistentDict("buttons_query")
FRESH = PersistentDict("fresh_query")
BUTTONS0 = {}
BUTTONS1 = {}
BUTTONS2 = {}
SPELL_CHECK = {}


async def _react_bg(message):
    try:
        await message.react(emoji=random.choice(REACTIONS), big=True)
    except Exception:
        try:
            await message.react(emoji="⚡️", big=True)
        except Exception:
            pass


@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    if EMOJI_MODE:
        asyncio.create_task(_react_bg(message))
    asyncio.create_task(mdb.update_top_messages(message.from_user.id, message.text))
    if message.chat.id != SUPPORT_CHAT_ID:
        settings = await get_settings(message.chat.id)
        try:
            if settings['auto_ffilter']:
                if re.search(r'https?://\S+|www\.\S+|t\.me/\S+', message.text):
                    if await is_check_admin(client, message.chat.id, message.from_user.id):
                        return
                    return await message.delete()
                if is_conversational_chat(message.text):
                    return
                await auto_filter(client, message)
        except KeyError:
            pass
    else:
        search = message.text
        _, _, total_results = await get_search_results(chat_id=message.chat.id, query=search.lower(), offset=0, filter=True)
        if total_results == 0:
            return
        await message.reply_text(
            f"<b>Hᴇʏ {message.from_user.mention},\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ ᴀʟʀᴇᴀᴅʏ ᴀᴠᴀɪʟᴀʙʟᴇ ✅\n\n"
            f"📂 ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ : {str(total_results)}\n"
            f"🔍 ꜱᴇᴀʀᴄʜ :</b> <code>{search}</code>\n\n"
            f"<b>‼️ ᴛʜɪs ɪs ᴀ <u>sᴜᴘᴘᴏʀᴛ ɢʀᴏᴜᴘ</u> sᴏ ᴛʜᴀᴛ ʏᴏᴜ ᴄᴀɴ'ᴛ ɢᴇᴛ ғɪʟᴇs ғʀᴏᴍ ʜᴇʀᴇ...\n\n"
            f"📝 ꜱᴇᴀʀᴄʜ ʜᴇʀᴇ : 👇</b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔍 ᴊᴏɪɴ ᴀɴᴅ ꜱᴇᴀʀᴄʜ ʜᴇʀᴇ 🔎", url=GRP_LNK)]])
        )


@Client.on_message(filters.private & filters.text & filters.incoming & ~filters.regex(r"^/"))
async def pm_text(bot, message):
    bot_id = bot.me.id
    content = message.text
    user = message.from_user.first_name
    user_id = message.from_user.id
    if EMOJI_MODE:
        asyncio.create_task(_react_bg(message))
    if content.startswith(("#")):
        return
    try:
        if not await db.check_user_access(user_id, bot_id):
            from plugins.Premium import send_paywall_alert
            await send_paywall_alert(bot, message.chat.id, message.from_user.mention)
            return
        asyncio.create_task(mdb.update_top_messages(user_id, content))
        pm_search = await db.pm_search_status(bot_id)
        if pm_search:
            await auto_filter(bot, message)
        else:
            await message.reply_text(
                text=(
                    f"<b>🙋 ʜᴇʏ {user} 😍 ,\n\n"
                    "𝒀𝒐𝒖 𝒄𝒂𝒏 𝒔𝒆𝒂𝒓𝒄𝒉 𝒇𝒐𝒓 𝒎𝒐𝒗𝒊𝒆𝒔 𝒐𝒏𝒍𝒚 𝒐𝒏 𝒐𝒖𝒓 𝑴𝒐𝒗𝒊𝒆 𝑮𝒓𝒐𝒖𝒑. 𝒀𝒐𝒖 𝒂𝒓𝒆 𝒏𝒐𝒕 𝒂𝒍𝒍𝒐𝒘𝒆𝒅 𝒕𝒐 𝒔𝒆𝒂𝒓𝒄𝒉 𝒇𝒐𝒓 𝒎𝒐𝒗𝒊𝒆𝒔 𝒐𝒏 𝑫𝒊𝒓𝒆𝒄𝒕 𝑩𝒐𝒕. 𝑷𝒍𝒆𝒂𝒔𝒆 𝒋𝒐𝒊𝒏 𝒐𝒖𝒓 𝒎𝒐𝒗𝒊𝒆 𝒈𝒓𝒐𝒖𝒑 𝒃𝒚 𝒄𝒍𝒊𝒄𝒌𝒊𝒏𝒈 𝒐𝒏 𝒕𝒉𝒆  𝑹𝑬𝑸𝑼𝑬𝑺𝑻 𝑯𝑬𝑹𝑬 𝒃𝒖𝒕𝒕𝒐𝒏 𝒈𝒊𝒗𝒆𝒏 𝒃𝒆𝒍𝒐𝒘 𝒂𝒏𝒅 𝒔𝒆𝒂𝒓𝒄𝒉 𝒚𝒐𝒖𝒓 𝒇𝒂𝒗𝒐𝒓𝒊𝒕𝒆 𝒎𝒐𝒗𝒊𝒆 𝒕𝒉𝒆𝒓𝒆 👇\n\n"
                    "<blockquote>"
                    "आप केवल हमारे 𝑴𝒐𝒗𝒊𝒆 𝑮𝒓𝒐𝒖𝒑 पर ही 𝑴𝒐𝒗𝒊𝒆 𝑺𝒆𝒂𝒓𝒄𝒉 कर सकते हो । "
                    "आपको 𝑫𝒊𝒓𝒆𝒄𝒕 𝑩𝒐𝒕 पर 𝑴𝒐𝒗𝒊𝒆 𝑺𝒆𝒂𝒓𝒄𝒉 करने की 𝑷𝒆𝒓𝒎𝒊𝒔𝒔𝒊𝒐𝒏 नहीं है कृपया नीचे दिए गए 𝑹𝑬𝑸𝑼𝑬𝑺𝑻 𝑯𝑬𝑹𝑬 वाले 𝑩𝒖𝒕𝒕𝒐𝒏 पर क्लिक करके हमारे 𝑴𝒐𝒗𝒊𝒆 𝑮𝒓𝒐𝒖𝒑 को 𝑱𝒐𝒊𝒏 करें और वहां पर अपनी मनपसंद 𝑴𝒐𝒗𝒊𝒆 𝑺𝒆𝒂𝒓𝒄𝒉 सर्च करें ।"
                    "</blockquote></b>"
                ), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 ʀᴇǫᴜᴇsᴛ ʜᴇʀᴇ ", url=GRP_LNK)]]))
            await bot.send_message(chat_id=LOG_CHANNEL,
                                   text=(
                                       f"<b>#𝐏𝐌_𝐌𝐒𝐆\n\n"
                                       f"👤 Nᴀᴍᴇ : {user}\n"
                                       f"🆔 ID : {user_id}\n"
                                       f"💬 Mᴇssᴀɢᴇ : {content}</b>"
                                   )
                                   )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^reffff"))
async def refercall(bot, query):
    btn = [[
        InlineKeyboardButton(
            'invite link', url=f'https://telegram.me/share/url?url=https://t.me/{bot.me.username}?start=reff_{query.from_user.id}&text=Hello%21%20Experience%20a%20bot%20that%20offers%20a%20vast%20library%20of%20unlimited%20movies%20and%20series.%20%F0%9F%98%83'),
        InlineKeyboardButton(
            f'⏳ {referdb.get_refer_points(query.from_user.id)}', callback_data='ref_point'),
        InlineKeyboardButton('Back', callback_data='premium_info')
    ]]
    reply_markup = InlineKeyboardMarkup(btn)
    try:
        await bot.edit_message_media(
            query.message.chat.id,
            query.message.id,
            InputMediaPhoto("https://graph.org/file/1a2e64aee3d4d10edd930.jpg")
        )
    except Exception as e:    
        pass
    await query.message.edit_text(
        text=f'Hay Your refer link:\n\nhttps://t.me/{bot.me.username}?start=reff_{query.from_user.id}\n\nShare this link with your friends, Each time they join,  you will get 10 refferal points and after 100 points you will get 1 month premium subscription.',
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )
    await query.answer()

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    ident, req, key, offset = query.data.split("_")
    curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
    try:
        offset = int(offset)
    except:
        offset = 0
    active_filters = get_active_filters(key)
    active_chip = get_filter_chip_label(active_filters)
    raw_search = get_search_query_for_key(key, query)
    if active_filters and raw_search:
        search_input = {"search": raw_search, **active_filters}
    elif raw_search:
        search_input = raw_search
    elif BUTTONS.get(key) != None:
        search_input = BUTTONS.get(key)
    else:
        search_input = FRESH.get(key)
    if not search_input:
        await query.answer(script.OLD_ALRT_TXT.format(query.from_user.first_name), show_alert=True)
        return
    sess = GLOBAL_SESSION_MANAGER.get(key)
    current_rev = sess.increment_revision() if sess else 0
    files, n_offset, total = await get_search_results(query.message.chat.id, search_input, offset=offset, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale next_page callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()

    if not files:
        return await query.answer()

    if sess:
        sess.current_offset = offset

    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    temp.SHORT[query.from_user.id] = query.message.chat.id
    settings = await get_settings(query.message.chat.id)

    btn = build_search_buttons(
        files=files,
        key=key,
        current_offset=offset,
        total_results=total,
        req=req,
        settings=settings,
        active_filter=active_chip
    )

    search_title = raw_search or (search_input.get("search", "") if isinstance(search_input, dict) else str(search_input or ""))
    dreamx_title = clean_search_text(search_title)

    if not settings.get("button"):
        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - \
            timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
        try:
            cap = await get_cap(settings, remaining_seconds, files, query, total, dreamx_title, offset=offset)
            await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
        except Exception as e:
            logger.exception("Failed to send result: %s", e)
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
        except Exception as e:
            logger.warning("next_page edit_message_reply_markup error: %s", e)
    await query.answer()


@Client.on_callback_query(filters.regex(r"^spol"))
async def advantage_spoll_choker(bot, query):
    _, id, user = query.data.split('#')
    if int(user) != 0 and query.from_user.id != int(user):
        return await query.answer(script.ALRT_TXT.format(query.from_user.first_name), show_alert=True)
    movies = await get_posterx(id, id=True) if TMDB_ON_SEARCH else await get_poster(id, id=True)
    movie = movies.get('title')
    movie = re.sub(r"[:-]", " ", movie)
    movie = re.sub(r"\s+", " ", movie).strip()
    await query.answer(script.TOP_ALRT_MSG)
    files, offset, total_results = await get_search_results(query.message.chat.id, movie, offset=0, filter=True)
    if files:
        k = (movie, files, offset, total_results)
        await auto_filter(bot, query, k)
    else:
        reqstr1 = query.from_user.id if query.from_user else 0
        reqstr = await bot.get_users(reqstr1)
        if NO_RESULTS_MSG:
            try:
                await bot.send_message(chat_id=BIN_CHANNEL, text=script.NORSLTS.format(reqstr.id, reqstr.mention, movie))
            except Exception as e:
                print(f"Error In Spol - {e}   Make Sure Bot Admin BIN CHANNEL")
        btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔰Cʟɪᴄᴋ ʜᴇʀᴇ & ʀᴇǫᴜᴇsᴛ ᴛᴏ ᴀᴅᴍɪɴ🔰", url=OWNER_LNK)]])
        k = await query.message.edit(script.MVE_NT_FND, reply_markup=btn)
        await asyncio.sleep(10)
        await k.delete()

async def edit_search_message(query: CallbackQuery, text_or_cap: str, reply_markup: InlineKeyboardMarkup):
    """Safely edit search message whether it is a photo (caption) or text message."""
    try:
        if getattr(query.message, "caption", None) or getattr(query.message, "photo", None):
            await query.message.edit_caption(
                caption=text_or_cap,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await query.message.edit_text(
                text=text_or_cap,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"edit_search_message fallback to edit_reply_markup: {e}")
        try:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except Exception:
            pass

def get_search_query_for_key(key: str, query: CallbackQuery = None) -> str:
    """Retrieve search query from cache or recover directly from the message to persist across restarts."""
    search = FRESH.get(key)
    if search:
        return str(search).replace("_", " ").strip()
    search = BUTTONS.get(key)
    if search:
        return str(search).replace("_", " ").strip()
    if query and query.message:
        if query.message.reply_to_message and query.message.reply_to_message.text:
            text = query.message.reply_to_message.text.strip()
            if not text.startswith("/") and len(text) > 1:
                FRESH[key] = text
                return text
        body = query.message.text or query.message.caption or ""
        match = re.search(r"(?:🏷\s*)?(?:TITLE|ᴛɪᴛʟᴇ)\s*:\s*`?([^\n`]+)`?", body, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            if extracted:
                FRESH[key] = extracted
                return extracted
    return ""

# Qualities
@Client.on_callback_query(filters.regex(r"^qualities#"))
async def qualities_cb_handler(client: Client, query: CallbackQuery):
    _, key = query.data.split("#")
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    btn = []
    btn.append([
        InlineKeyboardButton("Qᴜᴀʟɪᴛʏ", callback_data=f"qualities#{key}"),
        InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"languages#{key}"),
        InlineKeyboardButton("Sᴇᴀsᴏɴ",  callback_data=f"seasons#{key}"),
        InlineKeyboardButton("↭ Fɪʟᴇs ↭", callback_data=f"reset_filter#{key}")
    ])
    btn.append([InlineKeyboardButton(text="⇊ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ ⇊", callback_data="ident")])
    for i in range(0, len(QUALITIES), 2):
        q1 = QUALITIES[i]
        row = [InlineKeyboardButton(text=q1, callback_data=f"fq#{q1.lower()}#{key}")]
        if i + 1 < len(QUALITIES):
            q2 = QUALITIES[i + 1]
            row.append(InlineKeyboardButton(text=q2, callback_data=f"fq#{q2.lower()}#{key}"))
        btn.append(row)
    btn.append([
        InlineKeyboardButton(text="↭ ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇs ↭", callback_data=f"back_filter#{key}")
    ])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^fq#"))
async def filter_qualities_cb_handler(client: Client, query: CallbackQuery):
    _, qual, key = query.data.split("#")
    curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    req = query.from_user.id
    chat_id = query.message.chat.id
    message = query.message

    # Stack quality filter
    active_filters = set_active_filter(key, "quality", None if qual == "homepage" else qual.lower())
    active_chip = get_filter_chip_label(active_filters)
    query_input = {"search": search, **active_filters}

    sess = GLOBAL_SESSION_MANAGER.get(key)
    current_rev = sess.increment_revision() if sess else 0
    files, offset, total_results = await get_search_results(chat_id, query_input, offset=0, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale filter_qualities callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()
    if not files:
        dreamx_title = clean_search_text(search)
        btn = build_empty_filter_buttons(key, active_filter=active_chip)
        cap = f"🚫 <b>No files found for <code>{dreamx_title}</code> with filter [{active_chip}]</b>\n\n💡 <i>Try selecting a different filter or reset filters below:</i>"
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
        return await query.answer(f"No results for {qual.upper()}", show_alert=False)

    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    settings = await get_settings(message.chat.id)
    btn = build_search_buttons(files, key, current_offset=0, total_results=total_results, req=req, settings=settings, active_filter=active_chip)

    if not settings.get("button"):
        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - \
            timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
        dreamx_title = clean_search_text(search)
        cap = await get_cap(settings, remaining_seconds, files, query, total_results, dreamx_title, offset=0)
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
    await query.answer()

# languages


@Client.on_callback_query(filters.regex(r"^languages#"))
async def languages_cb_handler(client: Client, query: CallbackQuery):
    _, key = query.data.split("#")
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    items = list(LANGUAGES.items())
    btn = []
    btn.append([
        InlineKeyboardButton("Qᴜᴀʟɪᴛʏ", callback_data=f"qualities#{key}"),
        InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"languages#{key}"),
        InlineKeyboardButton("Sᴇᴀsᴏɴ",  callback_data=f"seasons#{key}"),
        InlineKeyboardButton("↭ Fɪʟᴇs ↭", callback_data=f"reset_filter#{key}")
    ])
    btn.append([InlineKeyboardButton(text="⇊ ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ ⇊", callback_data="ident")])
    for i in range(0, len(items), 2):
        name1, code1 = items[i]
        row = [InlineKeyboardButton(text=name1, callback_data=f"fl#{code1}#{key}")]
        if i + 1 < len(items):
            name2, code2 = items[i + 1]
            row.append(InlineKeyboardButton(text=name2, callback_data=f"fl#{code2}#{key}"))
        btn.append(row)
    btn.append([InlineKeyboardButton(text="↭ ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇs ↭", callback_data=f"back_filter#{key}")])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^fl#"))
async def filter_languages_cb_handler(client: Client, query: CallbackQuery):
    _, lang, key = query.data.split("#")
    curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    req = query.from_user.id
    chat_id = query.message.chat.id
    message = query.message

    # Stack language filter
    active_filters = set_active_filter(key, "language", None if lang == "homepage" else lang.lower())
    active_chip = get_filter_chip_label(active_filters)
    query_input = {"search": search, **active_filters}

    sess = GLOBAL_SESSION_MANAGER.get(key)
    current_rev = sess.increment_revision() if sess else 0
    files, offset, total_results = await get_search_results(chat_id, query_input, offset=0, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale filter_qualities callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()
    if not files:
        dreamx_title = clean_search_text(search)
        btn = build_empty_filter_buttons(key, active_filter=active_chip)
        cap = f"🚫 <b>No files found for <code>{dreamx_title}</code> with filter [{active_chip}]</b>\n\n💡 <i>Try selecting a different filter or reset filters below:</i>"
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
        return await query.answer(f"No results for {lang.title()}", show_alert=False)

    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    settings = await get_settings(message.chat.id)
    btn = build_search_buttons(files, key, current_offset=0, total_results=total_results, req=req, settings=settings, active_filter=active_chip)

    if not settings.get("button"):
        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - \
            timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
        dreamx_title = clean_search_text(search)
        cap = await get_cap(settings, remaining_seconds, files, query, total_results, dreamx_title, offset=0)
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^seasons#"))
async def seasons_cb_handler(client: Client, query: CallbackQuery):
    _, key = query.data.split("#")
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    req = query.from_user.id
    btn = []
    btn.append([
        InlineKeyboardButton("Qᴜᴀʟɪᴛʏ", callback_data=f"qualities#{key}"),
        InlineKeyboardButton("Lᴀɴɢᴜᴀɢᴇ", callback_data=f"languages#{key}"),
        InlineKeyboardButton("Sᴇᴀsᴏɴ",  callback_data=f"seasons#{key}"),
        InlineKeyboardButton("↭ Fɪʟᴇs ↭", callback_data=f"reset_filter#{key}")
    ])
    btn.append([InlineKeyboardButton("⇊ ꜱᴇʟᴇᴄᴛ ꜱᴇᴀꜱᴏɴ ⇊", callback_data="ident")])
    for i in range(0, len(SEASONS) - 1, 2):
        btn.append([
            InlineKeyboardButton(f"Sᴇᴀꜱᴏɴ {SEASONS[i][1:]}", callback_data=f"fs#{SEASONS[i].lower()}#{key}"),
            InlineKeyboardButton(f"Sᴇᴀꜱᴏɴ {SEASONS[i+1][1:]}", callback_data=f"fs#{SEASONS[i+1].lower()}#{key}")
        ])
    btn.append([InlineKeyboardButton(text="↭ ʙᴀᴄᴋ ᴛᴏ ꜰɪʟᴇs ↭", callback_data=f"back_filter#{key}")])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^fs#"))
async def filter_seasons_cb_handler(client: Client, query: CallbackQuery):
    curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
    _, season_tag, key = query.data.split("#")
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("⚠️ Search expired! Please search again.", show_alert=True)
    season_tag = season_tag.lower()
    req = query.from_user.id
    chat_id = query.message.chat.id
    message = query.message

    # Stack season filter
    if season_tag == "homepage":
        active_filters = set_active_filter(key, "season", None)
    else:
        season_number = int(season_tag[1:])
        active_filters = set_active_filter(key, "season", str(season_number))

    active_chip = get_filter_chip_label(active_filters)
    query_input = {"search": search, **active_filters}

    sess = GLOBAL_SESSION_MANAGER.get(key)
    current_rev = sess.increment_revision() if sess else 0
    files, offset, total_results = await get_search_results(chat_id, query_input, offset=0, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale filter_qualities callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()
    if not files:
        dreamx_title = clean_search_text(search)
        btn = build_empty_filter_buttons(key, active_filter=active_chip)
        cap = f"🚫 <b>No files found for <code>{dreamx_title}</code> with filter [{active_chip}]</b>\n\n💡 <i>Try selecting a different filter or reset filters below:</i>"
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
        return await query.answer(f"No results for {season_tag.upper()}", show_alert=False)

    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    settings = await get_settings(chat_id)
    btn = build_search_buttons(files, key, current_offset=0, total_results=total_results, req=req, settings=settings, active_filter=active_chip)

    if not settings.get("button"):
        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - \
            timedelta(hours=curr_time.hour, minutes=curr_time.minute, seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())
        dreamx_title = clean_search_text(search)
        cap = await get_cap(settings, remaining_seconds, files, query, total_results, dreamx_title, offset=0)
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
    await query.answer()

# Handlers for Reset Filters and Filter Info Chips
@Client.on_callback_query(filters.regex(r"^back_filter#"))
async def back_filter_cb_handler(client: Client, query: CallbackQuery):
    _, key = query.data.split("#")
    search = get_search_query_for_key(key, query)
    if not search:
        return await query.answer("Search expired! Please search again.", show_alert=True)
    active_filters = get_active_filters(key)
    active_chip = get_filter_chip_label(active_filters)
    query_input = {"search": search, **active_filters} if active_filters else search
    chat_id = query.message.chat.id
    req = query.from_user.id
    sess = GLOBAL_SESSION_MANAGER.get(key)
    target_offset = getattr(sess, "current_offset", 0) if sess else 0
    current_rev = sess.increment_revision() if sess else 0
    files, n_offset, total_results = await get_search_results(chat_id, query_input, offset=target_offset, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale back_filter callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()
    if not files and target_offset > 0:
        target_offset = 0
        if sess:
            sess.current_offset = 0
        files, n_offset, total_results = await get_search_results(chat_id, query_input, offset=0, filter=True, session=sess)
    if not files:
        return await query.answer("🚫 ɴᴏ ꜰɪʟᴇꜱ ᴡᴇʀᴇ ꜰᴏᴜɴᴅ 🚫", show_alert=1)
    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    settings = await get_settings(chat_id)
    btn = build_search_buttons(files, key, current_offset=target_offset, total_results=total_results, req=req, settings=settings, active_filter=active_chip)
    if not settings.get("button"):
        dreamx_title = clean_search_text(search)
        cap = await get_cap(settings, "0.10", files, query, total_results, dreamx_title, offset=target_offset)
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
    await query.answer()

@Client.on_callback_query(filters.regex(r"^reset_filter#"))
async def reset_filter_cb_handler(client: Client, query: CallbackQuery):
    _, key = query.data.split("#")
    sess = GLOBAL_SESSION_MANAGER.get(key)
    if sess and sess.search_request and sess.search_request.normalized_title:
        search = sess.search_request.normalized_title
    else:
        search = get_search_query_for_key(key, query)
        search = clean_search_text(search) if search else ""
    if not search:
        return await query.answer("Search expired! Please search again.", show_alert=True)
    search = search.replace("_", " ").strip()
    if sess:
        sess.reset_filters()
        sess.current_offset = 0
    clear_active_filters(key)
    FRESH[key] = search
    BUTTONS[key] = search
    chat_id = query.message.chat.id
    req = query.from_user.id
    current_rev = sess.increment_revision() if sess else 0
    files, n_offset, total_results = await get_search_results(chat_id, search, offset=0, filter=True, session=sess)
    if sess and sess.revision != current_rev:
        logger.info("Dropping stale reset_filter callback (rev %s vs %s)", current_rev, sess.revision)
        return await query.answer()
    if not files:
        return await query.answer("🚫 ɴᴏ ꜰɪʟᴇꜱ ᴡᴇʀᴇ ꜰᴏᴜɴᴅ 🚫", show_alert=1)
    temp.GETALL[key] = files
    cache_save_getall(key, [f.file_id for f in files])
    settings = await get_settings(chat_id)
    btn = build_search_buttons(files, key, current_offset=0, total_results=total_results, req=req, settings=settings, active_filter=None)
    if not settings.get("button"):
        dreamx_title = clean_search_text(search)
        cap = await get_cap(settings, "0.10", files, query, total_results, dreamx_title, offset=0)
        await edit_search_message(query, cap, InlineKeyboardMarkup(btn))
    else:
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass
    await query.answer("Filters reset ✅", show_alert=False)

@Client.on_callback_query(filters.regex(r"^filter_info#"))
async def filter_info_cb_handler(client: Client, query: CallbackQuery):
    tag = query.data.split("#")[1]
    await query.answer(f"🎯 Active filters: {tag}", show_alert=True)


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    DreamxData = query.data
    if DreamxData and (DreamxData.startswith(("buy_", "paywall_", "rzp_verify#")) or DreamxData == "myplan_cb"):
        return
    if query.data == "close_data":
        try:
            user = query.message.reply_to_message.from_user.id
        except:
            user = query.from_user.id
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer(script.NT_ALRT_TXT, show_alert=True)
        await query.answer("ᴛʜᴀɴᴋs ꜰᴏʀ ᴄʟᴏsᴇ 🙈")
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except:
            pass

    elif query.data == "pages":
        await query.answer("ᴛʜɪs ɪs ᴘᴀɢᴇs ʙᴜᴛᴛᴏɴ 😅")

    elif query.data == "ident":
        await query.answer()

    elif query.data == "hiding":
        await query.answer("ʙᴇᴄᴀᴜsᴇ ᴏғ ʟᴀɢᴛᴇ ғɪʟᴇs ɪɴ ᴅᴀᴛᴀʙᴀsᴇ,🙏\nɪᴛ ᴛᴀᴋᴇꜱ ʟɪᴛᴛʟᴇ ʙɪᴛ ᴛɪᴍᴇ", show_alert=True)

    elif query.data == "delallcancel":
        userid = query.from_user.id
        chat_type = query.message.chat.type
        if chat_type == enums.ChatType.PRIVATE:
            await query.message.reply_to_message.delete()
            await query.message.delete()
        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = query.message.chat.id
            st = await client.get_chat_member(grp_id, userid)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                await query.message.delete()
                try:
                    await query.message.reply_to_message.delete()
                except:
                    pass
            else:
                await query.answer("Tʜᴀᴛ's ɴᴏᴛ ғᴏʀ ʏᴏᴜ!!", show_alert=True)

    elif query.data.startswith("file"):
        ident, file_id = query.data.split("#")
        user = query.message.reply_to_message.from_user.id if query.message.reply_to_message else query.from_user.id
        # Multi-user: allow any member to fetch the file to their PM
        pass
        await query.answer(url=f"https://t.me/{temp.U_NAME}?start=file_{query.message.chat.id}_{file_id}")

    elif query.data.startswith("sendfiles"):
        clicked = query.from_user.id
        ident, key = query.data.split("#")
        settings = await get_settings(query.message.chat.id)
        # Restore temp.GETALL across bot reboots
        if key not in temp.GETALL:
            c_ids = cache_get_getall(key)
            if c_ids:
                cached_files = []
                for cid in c_ids:
                    cf = await get_file_details(cid)
                    if cf:
                        cached_files.extend(cf)
                if cached_files:
                    temp.GETALL[key] = cached_files
        try:
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=allfiles_{query.message.chat.id}_{key}")
            return
        except UserIsBlocked:
            await query.answer('Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴍᴀʜɴ !', show_alert=True)
        except PeerIdInvalid:
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles3_{key}")
        except Exception as e:
            logger.exception(e)
            await query.answer(url=f"https://telegram.me/{temp.U_NAME}?start=sendfiles4_{key}")

    elif query.data.startswith("del"):
        ident, file_id = query.data.split("#")
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('Nᴏ sᴜᴄʜ ғɪʟᴇ ᴇxɪsᴛ.')
        files = files_[0]
        title = files.file_name
        size = get_size(files.file_size)
        f_caption = files.caption
        settings = await get_settings(query.message.chat.id)
        if CUSTOM_FILE_CAPTION:
            try:
                f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                       file_size='' if size is None else size,
                                                       file_caption='' if f_caption is None else f_caption)
            except Exception as e:
                logger.exception(e)
            f_caption = f_caption
        if f_caption is None:
            f_caption = f"{files.file_name}"
        await query.answer(url=f"href='https://telegram.me/{temp.U_NAME}?start=file_{query.message.chat.id}_{file.file_id}")

    elif query.data.startswith("autofilter_delete"):
        user_id = query.from_user.id if query.from_user else 0
        if user_id not in ADMINS and str(user_id) not in [str(a) for a in ADMINS]:
            return await query.answer("You are not authorized to perform this action!", show_alert=True)
        await Media.collection.drop()
        if MULTIPLE_DB:    
            await Media2.collection.drop()
        drop_fts_catalog()
        await query.answer("Eᴠᴇʀʏᴛʜɪɴɢ's Gᴏɴᴇ")
        await query.message.edit('ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ ᴀʟʟ ɪɴᴅᴇxᴇᴅ ꜰɪʟᴇꜱ ✅')

    elif query.data.startswith("checksub"):
        try:
            ident, kk, file_id = query.data.split("#")
            btn = []
            chat = file_id.split("_")[0]
            settings = await get_settings(chat)
            fsub_channels = list(dict.fromkeys((settings.get('fsub', []) if settings else [])+ AUTH_CHANNELS)) 
            btn += await is_subscribed(client, query.from_user.id, fsub_channels)
            btn += await is_req_subscribed(client, query.from_user.id, AUTH_REQ_CHANNELS)
            if btn:
                btn.append([InlineKeyboardButton("♻️ ᴛʀʏ ᴀɢᴀɪɴ ♻️", callback_data=f"checksub#{kk}#{file_id}")])
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
                except MessageNotModified:
                    pass
                await query.answer(
                    f"👋 Hello {query.from_user.first_name},\n\n"
                    "🛑 Yᴏᴜ ʜᴀᴠᴇ ɴᴏᴛ ᴊᴏɪɴᴇᴅ ᴀʟʟ ʀᴇǫᴜɪʀᴇᴅ ᴜᴘᴅᴀᴛᴇ Cʜᴀɴɴᴇʟs.\n"
                    "👉 Pʟᴇᴀsᴇ ᴊᴏɪɴ ᴇᴀᴄʜ ᴏɴᴇ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.\n",
                    show_alert=True
                )
                return
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={kk}_{file_id}")
            await query.message.delete()
        except Exception as e:
            await log_error(client, f"❌ Error in checksub callback:\n\n{repr(e)}")
            logger.error(f"❌ Error in checksub callback:\n\n{repr(e)}")


    elif query.data.startswith("killfilesdq"):
        ident, keyword = query.data.split("#")
        await query.message.edit_text(f"<b>Fetching Files for your query {keyword} on DB... Please wait...</b>")
        files, total = await get_bad_files(keyword)
        await query.message.edit_text("<b>ꜰɪʟᴇ ᴅᴇʟᴇᴛɪᴏɴ ᴘʀᴏᴄᴇꜱꜱ ᴡɪʟʟ ꜱᴛᴀʀᴛ ɪɴ 5 ꜱᴇᴄᴏɴᴅꜱ !</b>")
        await asyncio.sleep(5)
        deleted = 0
        async with lock:
            try:
                for file in files:
                    file_ids = file.file_id
                    file_name = file.file_name
                    result = await Media.collection.delete_one({
                        '_id': file_ids,
                    })
                    if not result.deleted_count and MULTIPLE_DB:
                        result = await Media2.collection.delete_one({
                            '_id': file_ids,
                        })
                    delete_from_fts(file_id=file_ids)
                    if result.deleted_count:
                        logger.info(
                            f'ꜰɪʟᴇ ꜰᴏᴜɴᴅ ꜰᴏʀ ʏᴏᴜʀ ǫᴜᴇʀʏ {keyword}! ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {file_name} ꜰʀᴏᴍ ᴅᴀᴛᴀʙᴀꜱᴇ.')
                    deleted += 1
                    if deleted % 20 == 0:
                        await query.message.edit_text(f"<b>ᴘʀᴏᴄᴇꜱꜱ ꜱᴛᴀʀᴛᴇᴅ ꜰᴏʀ ᴅᴇʟᴇᴛɪɴɢ ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴅʙ. ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {str(deleted)} ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴅʙ ꜰᴏʀ ʏᴏᴜʀ ǫᴜᴇʀʏ {keyword} !\n\nᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ...</b>")
            except Exception as e:
                print(f"Error In killfiledq -{e}")
                await query.message.edit_text(f'Error: {e}')
            else:
                await query.message.edit_text(f"<b>ᴘʀᴏᴄᴇꜱꜱ ᴄᴏᴍᴘʟᴇᴛᴇᴅ ꜰᴏʀ ꜰɪʟᴇ ᴅᴇʟᴇᴛᴀᴛɪᴏɴ !\n\nꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ {str(deleted)} ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴅʙ ꜰᴏʀ ʏᴏᴜʀ ǫᴜᴇʀʏ {keyword}.</b>")

    elif query.data.startswith("opnsetgrp"):
        ident, grp_id = query.data.split("#")
        userid = query.from_user.id if query.from_user else None
        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            await query.answer("ʏᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ʀɪɢʜᴛꜱ ᴛᴏ ᴅᴏ ᴛʜɪꜱ !", show_alert=True)
            return
        title = query.message.chat.title
        settings = await get_settings(grp_id)
        if settings is not None:
            btn = await group_setting_buttons(int(grp_id))
            reply_markup = InlineKeyboardMarkup(btn)
            await query.message.edit_text(
                text=f"<b>ᴄʜᴀɴɢᴇ ʏᴏᴜʀ ꜱᴇᴛᴛɪɴɢꜱ ꜰᴏʀ {title} ᴀꜱ ʏᴏᴜ ᴡɪꜱʜ ⚙</b>",
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML
            )
            await query.message.edit_reply_markup(reply_markup)

    elif query.data.startswith("opnsetpm"):
        ident, grp_id = query.data.split("#")
        userid = query.from_user.id if query.from_user else None
        st = await client.get_chat_member(grp_id, userid)
        if (
                st.status != enums.ChatMemberStatus.ADMINISTRATOR
                and st.status != enums.ChatMemberStatus.OWNER
                and str(userid) not in ADMINS
        ):
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)
            return
        title = query.message.chat.title
        settings = await get_settings(grp_id)
        btn2 = [[
            InlineKeyboardButton(
                "ᴄʜᴇᴄᴋ ᴍʏ ᴅᴍ 🗳️", url=f"telegram.me/{temp.U_NAME}")
        ]]
        reply_markup = InlineKeyboardMarkup(btn2)
        await query.message.edit_text(f"<b>ʏᴏᴜʀ sᴇᴛᴛɪɴɢs ᴍᴇɴᴜ ғᴏʀ {title} ʜᴀs ʙᴇᴇɴ sᴇɴᴛ ᴛᴏ ʏᴏᴜ ʙʏ ᴅᴍ.</b>")
        await query.message.edit_reply_markup(reply_markup)
        if settings is not None:
            btn = await group_setting_buttons(int(grp_id))
            reply_markup = InlineKeyboardMarkup(btn)
            await client.send_message(
                chat_id=userid,
                text=f"<b>ᴄʜᴀɴɢᴇ ʏᴏᴜʀ ꜱᴇᴛᴛɪɴɢꜱ ꜰᴏʀ {title} ᴀꜱ ʏᴏᴜ ᴡɪꜱʜ ⚙</b>",
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=query.message.id
            )

    elif query.data.startswith("show_option"):
        ident, from_user = query.data.split("#")
        btn = [[
            InlineKeyboardButton("⚠️ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ ⚠️",
                                 callback_data=f"unavailable#{from_user}"),
            InlineKeyboardButton(
                "🟢 ᴜᴘʟᴏᴀᴅᴇᴅ 🟢", callback_data=f"uploaded#{from_user}")
        ], [
            InlineKeyboardButton("♻️ ᴀʟʀᴇᴀᴅʏ ᴀᴠᴀɪʟᴀʙʟᴇ ♻️",
                                 callback_data=f"already_available#{from_user}")
        ], [
            InlineKeyboardButton("📌 Not Released 📌",
                                 callback_data=f"Not_Released#{from_user}"),
            InlineKeyboardButton("♨️Type Correct Spelling♨️",
                                 callback_data=f"Type_Correct_Spelling#{from_user}")
        ], [
            InlineKeyboardButton("⚜️ Not Available In The Hindi ⚜️",
                                 callback_data=f"Not_Available_In_The_Hindi#{from_user}")
        ]]
        btn2 = [[
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Hᴇʀᴇ ᴀʀᴇ ᴛʜᴇ ᴏᴘᴛɪᴏɴs !")
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("unavailable"):
        ident, from_user = query.data.split("#")
        btn = [
            [InlineKeyboardButton("⚠️ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ ⚠️",
                                  callback_data=f"unalert#{from_user}")]
        ]
        btn2 = [
            [InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
             InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")]
        ]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Uɴᴀᴠᴀɪʟᴀʙʟᴇ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=f"<b>Hᴇʏ {user.mention},</b>\n\n<u>{content}</u> Hᴀs Bᴇᴇɴ Mᴀʀᴋᴇᴅ Aᴅ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ...💔\n\n#Uɴᴀᴠᴀɪʟᴀʙʟᴇ ⚠️",
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=f"<b>Hᴇʏ {user.mention},</b>\n\n<u>{content}</u> Hᴀs Bᴇᴇɴ Mᴀʀᴋᴇᴅ Aᴅ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ...💔\n\n#Uɴᴀᴠᴀɪʟᴀʙʟᴇ ⚠️\n\n<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small></b>",
                    reply_markup=InlineKeyboardMarkup(btn2)
                )

    elif query.data.startswith("Not_Released"):
        ident, from_user = query.data.split("#")
        btn = [[InlineKeyboardButton(
            "📌 Not Released 📌", callback_data=f"nralert#{from_user}")]]
        btn2 = [[
            InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Nᴏᴛ Rᴇʟᴇᴀꜱᴇᴅ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=(
                        f"<b>Hᴇʏ {user.mention}\n\n"
                        f"<code>{content}</code>, ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ\n\n"
                        f"#CᴏᴍɪɴɢSᴏᴏɴ...🕊️✌️</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=(
                        f"<u>Hᴇʏ {user.mention}</u>\n\n"
                        f"<b><code>{content}</code>, ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ\n\n"
                        f"#CᴏᴍɪɴɢSᴏᴏɴ...🕊️✌️\n\n"
                        f"<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small></b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("Type_Correct_Spelling"):
        ident, from_user = query.data.split("#")
        btn = [[
            InlineKeyboardButton("♨️ Type Correct Spelling ♨️",
                                 callback_data=f"wsalert#{from_user}")
        ]]
        btn2 = [[
            InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Cᴏʀʀᴇᴄᴛ Sᴘᴇʟʟɪɴɢ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=(
                        f"<b>Hᴇʏ {user.mention}\n\n"
                        f"Wᴇ Dᴇᴄʟɪɴᴇᴅ Yᴏᴜʀ Rᴇǫᴜᴇsᴛ <code>{content}</code>, Bᴇᴄᴀᴜsᴇ Yᴏᴜʀ Sᴘᴇʟʟɪɴɢ Wᴀs Wʀᴏɴɢ 😢\n\n"
                        f"#Wʀᴏɴɢ_Sᴘᴇʟʟɪɴɢ 😑</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=(
                        f"<u>Hᴇʏ {user.mention}</u>\n\n"
                        f"<b><code>{content}</code>, Bᴇᴄᴀᴜsᴇ Yᴏᴜʀ Sᴘᴇʟʟɪɴɢ Wᴀs Wʀᴏɴɢ 😢\n\n"
                        f"#Wʀᴏɴɢ_Sᴘᴇʟʟɪɴɢ 😑\n\n"
                        f"<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small></b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("Not_Available_In_The_Hindi"):
        ident, from_user = query.data.split("#")
        btn = [[
            InlineKeyboardButton(
                "⚜️ Not Available In The Hindi ⚜️", callback_data=f"hnalert#{from_user}")
        ]]
        btn2 = [[
            InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ Iɴ Hɪɴᴅɪ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=(
                        f"<b>Hᴇʏ {user.mention}\n\n"
                        f"Yᴏᴜʀ Rᴇǫᴜᴇsᴛ <code>{content}</code> ɪs Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ ɪɴ Hɪɴᴅɪ ʀɪɢʜᴛ ɴᴏᴡ. Sᴏ ᴏᴜʀ ᴍᴏᴅᴇʀᴀᴛᴏʀs ᴄᴀɴ'ᴛ ᴜᴘʟᴏᴀᴅ ɪᴛ\n\n"
                        f"#Hɪɴᴅɪ_ɴᴏᴛ_ᴀᴠᴀɪʟᴀʙʟᴇ ❌</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=(
                        f"<u>Hᴇʏ {user.mention}</u>\n\n"
                        f"<b><code>{content}</code> ɪs Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ ɪɴ Hɪɴᴅɪ ʀɪɢʜᴛ ɴᴏᴡ. Sᴏ ᴏᴜʀ ᴍᴏᴅᴇʀᴀᴛᴏʀs ᴄᴀɴ'ᴛ ᴜᴘʟᴏᴀᴅ ɪᴛ\n\n"
                        f"#Hɪɴᴅɪ_ɴᴏᴛ_ᴀᴠᴀɪʟᴀʙʟᴇ ❌\n\n"
                        f"<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small></b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("uploaded"):
        ident, from_user = query.data.split("#")
        btn = [[
            InlineKeyboardButton(
                "🟢 ᴜᴘʟᴏᴀᴅᴇᴅ 🟢", callback_data=f"upalert#{from_user}")
        ]]
        btn2 = [[
            InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ], [
            InlineKeyboardButton("🔍 ꜱᴇᴀʀᴄʜ ʜᴇʀᴇ 🔎", url=GRP_LNK)
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Uᴘʟᴏᴀᴅᴇᴅ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=(
                        f"<b>Hᴇʏ {user.mention},\n\n"
                        f"<u>{content}</u> Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ ʙʏ ᴏᴜʀ ᴍᴏᴅᴇʀᴀᴛᴏʀs.\n"
                        f"Kɪɴᴅʟʏ sᴇᴀʀᴄʜ ɪɴ ᴏᴜʀ Gʀᴏᴜᴘ.</b>\n\n"
                        f"#Uᴘʟᴏᴀᴅᴇᴅ✅"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=(
                        f"<u>{content}</u>\n\n"
                        f"<b>Hᴇʏ {user.mention}, Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ ʙʏ ᴏᴜʀ ᴍᴏᴅᴇʀᴀᴛᴏʀs."
                        f"Kɪɴᴅʟʏ sᴇᴀʀᴄʜ ɪɴ ᴏᴜʀ Gʀᴏᴜᴘ.</b>\n\n"
                        f"#Uᴘʟᴏᴀᴅᴇᴅ✅\n\n"
                        f"<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("already_available"):
        ident, from_user = query.data.split("#")
        btn = [[
            InlineKeyboardButton("♻️ ᴀʟʀᴇᴀᴅʏ ᴀᴠᴀɪʟᴀʙʟᴇ ♻️",
                                 callback_data=f"alalert#{from_user}")
        ]]
        btn2 = [[
            InlineKeyboardButton('ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ', url=link.invite_link),
            InlineKeyboardButton("ᴠɪᴇᴡ ꜱᴛᴀᴛᴜꜱ", url=f"{query.message.link}")
        ], [
            InlineKeyboardButton("🔍 ꜱᴇᴀʀᴄʜ ʜᴇʀᴇ 🔎", url=GRP_LNK)
        ]]
        if query.from_user.id in ADMINS:
            user = await client.get_users(from_user)
            reply_markup = InlineKeyboardMarkup(btn)
            content = query.message.text
            await query.message.edit_text(f"<b><strike>{content}</strike></b>")
            await query.message.edit_reply_markup(reply_markup)
            await query.answer("Sᴇᴛ ᴛᴏ Aʟʀᴇᴀᴅʏ Aᴠᴀɪʟᴀʙʟᴇ !")
            content = extract_request_content(query.message.text)
            try:
                await client.send_message(
                    chat_id=int(from_user),
                    text=(
                        f"<b>Hᴇʏ {user.mention},\n\n"
                        f"<u>{content}</u> Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ ᴀʟʀᴇᴀᴅʏ ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ ᴏᴜʀ ʙᴏᴛ'ꜱ ᴅᴀᴛᴀʙᴀꜱᴇ.\n"
                        f"Kɪɴᴅʟʏ sᴇᴀʀᴄʜ ɪɴ ᴏᴜʀ Gʀᴏᴜᴘ.</b>\n\n"
                        f"#Aᴠᴀɪʟᴀʙʟᴇ 💗"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
            except UserIsBlocked:
                await client.send_message(
                    chat_id=int(SUPPORT_CHAT_ID),
                    text=(
                        f"<b>Hᴇʏ {user.mention},\n\n"
                        f"<u>{content}</u> Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ ᴀʟʀᴇᴀᴅʏ ᴀᴠᴀɪʟᴀʙʟᴇ ɪɴ ᴏᴜʀ ʙᴏᴛ'ꜱ ᴅᴀᴛᴀʙᴀꜱᴇ.\n"
                        f"Kɪɴᴅʟʏ sᴇᴀʀᴄʜ ɪɴ ᴏᴜʀ Gʀᴏᴜᴘ.</b>\n\n"
                        f"#Aᴠᴀɪʟᴀʙʟᴇ 💗\n"
                        f"<small>Bʟᴏᴄᴋᴇᴅ? Uɴʙʟᴏᴄᴋ ᴛʜᴇ ʙᴏᴛ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ᴍᴇꜱꜱᴀɢᴇꜱ.</small></i>"
                    ),
                    reply_markup=InlineKeyboardMarkup(btn2)
                )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴀɴᴛ ʀɪɢᴛs ᴛᴏ ᴅᴏ ᴛʜɪs !", show_alert=True)

    elif query.data.startswith("alalert"):
        ident, from_user = query.data.split("#")
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ Aʟʀᴇᴀᴅʏ Aᴠᴀɪʟᴀʙʟᴇ ✅",
                show_alert=True
            )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴇɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs ❌", show_alert=True)

    elif query.data.startswith("upalert"):
        ident, from_user = query.data.split("#")
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ Uᴘʟᴏᴀᴅᴇᴅ 🔼",
                show_alert=True
            )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴇɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs ❌", show_alert=True)

    elif query.data.startswith("unalert"):
        ident, from_user = query.data.split("#")
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Yᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ɪꜱ Uɴᴀᴠᴀɪʟᴀʙʟᴇ ⚠️",
                show_alert=True
            )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ sᴜғғɪᴄɪᴇɴᴛ ʀɪɢʜᴛs ᴛᴏ ᴅᴏ ᴛʜɪs ❌", show_alert=True)

    elif query.data.startswith("hnalert"):
        ident, from_user = query.data.split("#")  # Hindi Not Available
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Tʜɪꜱ ɪꜱ Nᴏᴛ Aᴠᴀɪʟᴀʙʟᴇ ɪɴ Hɪɴᴅɪ ❌",
                show_alert=True
            )
        else:
            await query.answer("Nᴏᴛ ᴀʟʟᴏᴡᴇᴅ — ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴛʜᴇ ʀᴇǫᴜᴇꜱᴛᴇʀ ❌", show_alert=True)

    elif query.data.startswith("nralert"):
        ident, from_user = query.data.split("#")  # Not Released
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Tʜᴇ Mᴏᴠɪᴇ/ꜱʜᴏᴡ ɪꜱ Nᴏᴛ Rᴇʟᴇᴀꜱᴇᴅ Yᴇᴛ 🆕",
                show_alert=True
            )
        else:
            await query.answer("Yᴏᴜ ᴄᴀɴ'ᴛ ᴅᴏ ᴛʜɪꜱ ᴀꜱ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴛʜᴇ ᴏʀɪɢɪɴᴀʟ ʀᴇǫᴜᴇꜱᴛᴇʀ ❌", show_alert=True)

    elif query.data.startswith("wsalert"):
        ident, from_user = query.data.split("#")  # Wrong Spelling
        if int(query.from_user.id) == int(from_user):
            user = await client.get_users(from_user)
            await query.answer(
                f"Hᴇʏ {user.first_name}, Yᴏᴜʀ Rᴇǫᴜᴇꜱᴛ ᴡᴀꜱ ʀᴇᴊᴇᴄᴛᴇᴅ ᴅᴜᴇ ᴛᴏ ᴡʀᴏɴɢ sᴘᴇʟʟɪɴɢ ❗",
                show_alert=True
            )
        else:
            await query.answer("Yᴏᴜ ᴅᴏɴ'ᴛ ʜᴀᴠᴇ ᴘᴇʀᴍɪssɪᴏɴ ᴛᴏ sᴇᴇ ᴛʜɪꜱ ❌", show_alert=True)

    elif DreamxData.startswith("generate_stream_link"):
        _, file_id = DreamxData.split(":")
        try:
            user_id = query.from_user.id
            username = query.from_user.mention
            log_msg = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=file_id,)
            fileName = {quote_plus(get_name(log_msg))}
            dreamx_stream = f"{URL}watch/{str(log_msg.id)}/{quote_plus(get_name(log_msg))}?hash={get_hash(log_msg)}"
            dreamx_download = f"{URL}{str(log_msg.id)}/{quote_plus(get_name(log_msg))}?hash={get_hash(log_msg)}"
            await query.answer(MSG_ALRT)
            await asyncio.sleep(1)
            await log_msg.reply_text(
                text=f"•• ʟɪɴᴋ ɢᴇɴᴇʀᴀᴛᴇᴅ ꜰᴏʀ ɪᴅ #{user_id} \n•• ᴜꜱᴇʀɴᴀᴍᴇ : {username} \n\n•• ᖴᎥᒪᗴ Nᗩᗰᗴ : {fileName}",
                quote=True,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Fast Download 🚀", url=dreamx_download),  # we download Link
                                                    InlineKeyboardButton('🖥️ Watch online 🖥️', url=dreamx_stream)]])  # web stream Link
            )
            dreamcinezone = await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🚀 Download ", url=dreamx_download),
                        InlineKeyboardButton('🖥️ Watch ', url=dreamx_stream)
                    ],
                    [
                        InlineKeyboardButton('📌 ᴊᴏɪɴ ᴜᴘᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ 📌', url=UPDATE_CHNL_LNK)
                    ]
                ])
            )
            await asyncio.sleep(DELETE_TIME)
            await dreamcinezone.delete()
            return
        except Exception as e:
            print(e)
            await query.answer(f"⚠️ SOMETHING WENT WRONG STREAM LINK  \n\n{e}", show_alert=True)
            return


    elif query.data == "prestream":
        await query.answer(text=script.PRE_STREAM_ALERT, show_alert=True)
        dreamcinezone = await client.send_photo(
            chat_id=query.message.chat.id,
            photo="https://i.ibb.co/whf8xF7j/photo-2025-07-26-10-42-46-7531339305176793100.jpg",
            caption=script.PRE_STREAM,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Buy Premium 🚀", callback_data="premium_info")]
            ])
        )
        await asyncio.sleep(DELETE_TIME)
        await dreamcinezone.delete()


    elif query.data == "pagesn1":
        await query.answer(text=script.PAGE_TXT, show_alert=True)

    elif query.data == "sinfo":
        await query.answer(text=script.SINFO, show_alert=True)

    elif query.data == "start":
        buttons = [[
                    InlineKeyboardButton('🔰 ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ 🔰', url=f'http://telegram.me/{temp.U_NAME}?startgroup=true')
                ],[
                    InlineKeyboardButton(' ʜᴇʟᴘ 📢', callback_data='help'),
                    InlineKeyboardButton(' ᴀʙᴏᴜᴛ 📖', callback_data='about')
                ],[
                    InlineKeyboardButton('ᴛᴏᴘ sᴇᴀʀᴄʜɪɴɢ ⭐', callback_data="topsearch"),
                     InlineKeyboardButton('ᴜᴘɢʀᴀᴅᴇ 🎟', callback_data="premium_info"),
                ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        current_time = datetime.now(pytz.timezone(TIMEZONE))
        curr_time = current_time.hour
        if curr_time < 12:
            gtxt = "ɢᴏᴏᴅ ᴍᴏʀɴɪɴɢ 🌞"
        elif curr_time < 17:
            gtxt = "ɢᴏᴏᴅ ᴀғᴛᴇʀɴᴏᴏɴ 🌓"
        elif curr_time < 21:
            gtxt = "ɢᴏᴏᴅ ᴇᴠᴇɴɪɴɢ 🌘"
        else:
            gtxt = "ɢᴏᴏᴅ ɴɪɢʜᴛ 🌑"
        try:
            await client.edit_message_media(
                query.message.chat.id,
                query.message.id,
                InputMediaPhoto(random.choice(PICS))
            )
        except Exception as e:
            pass
        await query.message.edit_text(
            text=script.START_TXT.format(query.from_user.mention, gtxt, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer(MSG_ALRT)

    elif query.data == "donation":
        buttons = [[
                InlineKeyboardButton('🌲 Sᴇɴᴅ Dᴏɴᴀᴛᴇ Sᴄʀᴇᴇɴsʜᴏᴛ Hᴇʀᴇ', url=OWNER_LNK)
            ],[
                InlineKeyboardButton('⇍ ʙᴀᴄᴋ ⇏', callback_data='about')
            ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(text="● ◌ ◌")
        await query.message.edit_text(text="● ● ◌")
        await query.message.edit_text(text="● ● ●")
        reply_markup = InlineKeyboardMarkup(buttons)
        await client.edit_message_media(
            query.message.chat.id,
            query.message.id,
            InputMediaPhoto('https://graph.org/file/99eebf5dbe8a134f548e0.jpg')
        )
        await query.message.edit_text(
            text=script.DREAMXBOTZ_DONATION.format(query.from_user.mention, QR_CODE, OWNER_UPI_ID),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "help":
        buttons = [[
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ʜᴏᴍᴇ ⇋', callback_data='start')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.HELP_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "about":
        buttons = [[
            InlineKeyboardButton('‼️ ᴅɪꜱᴄʟᴀɪᴍᴇʀ ‼️', callback_data='disclaimer'),
            InlineKeyboardButton ('🪔 sᴏᴜʀᴄᴇ', callback_data='source'),
        ],[
            InlineKeyboardButton('ᴅᴏɴᴀᴛɪᴏɴ 💰', callback_data='donation'),
        ],[
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ʜᴏᴍᴇ ⇋', callback_data='start')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ABOUT_TXT.format(temp.U_NAME, temp.B_NAME, OWNER_LNK),
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "give_trial":
        try:
            user_id = query.from_user.id
            has_free_trial = await db.check_trial_status(user_id)
            if has_free_trial:
                await query.answer(
                    "🚸 ʏᴏᴜ'ᴠᴇ ᴀʟʀᴇᴀᴅʏ ᴄʟᴀɪᴍᴇᴅ ʏᴏᴜʀ ꜰʀᴇᴇ ᴛʀɪᴀʟ ᴏɴᴄᴇ !\n\n📌 ᴄʜᴇᴄᴋᴏᴜᴛ ᴏᴜʀ ᴘʟᴀɴꜱ ʙʏ : /plan",
                    show_alert=True
                )
                return
            else:
                await db.give_free_trial(user_id)
                await query.answer("✅ Trial activated!", show_alert=True)

                msg = await client.send_photo(
                    chat_id=query.message.chat.id,
                    photo="https://i.ibb.co/0jC8MSDZ/photo-2025-07-26-10-42-36-7531339283701956616.jpg",
                    caption=(
                        "<b>🥳 ᴄᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴꜱ\n\n"
                        "🎉 ʏᴏᴜ ᴄᴀɴ ᴜsᴇ ꜰʀᴇᴇ ᴛʀᴀɪʟ ꜰᴏʀ <u>5 ᴍɪɴᴜᴛᴇs</u> ꜰʀᴏᴍ ɴᴏᴡ !\n\n"
                        "ɴᴇᴇᴅ ᴘʀᴇᴍɪᴜᴍ 👉🏻 /plan</b>"
                    ),
                    parse_mode=enums.ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🚀 Buy Premium 🚀", callback_data="premium_info")
                    ]])
                )
                await asyncio.sleep(DELETE_TIME)
                return await msg.delete()
        except Exception as e:
            logging.exception("Error in give_trial callback")



    elif query.data == "source":
        buttons = [[
            InlineKeyboardButton('Source Code 📜', url='https://t.me/royalkrrishna'),
            InlineKeyboardButton('⇋ ʙᴀᴄᴋ ⇋', callback_data='about')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.SOURCE_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )

    elif query.data == "ref_point":
        await query.answer(f'You Have: {referdb.get_refer_points(query.from_user.id)} Refferal points.', show_alert=True)

    elif query.data == "disclaimer":
            btn = [[
                    InlineKeyboardButton("⇋ ʙᴀᴄᴋ ⇋", callback_data="about")
                  ]]
            reply_markup = InlineKeyboardMarkup(btn)
            await query.message.edit_text(
                text=(script.DISCLAIMER_TXT),
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML
            )

    elif query.data == "premium_info":
        try:
            from plugins.Premium import format_plan_label
            rzp_rows = [
                [InlineKeyboardButton(f"💳 {format_plan_label(duration)} Pʀᴇᴍɪᴜᴍ — ₹{amount}", callback_data=f"buy_{amount}")]
                for amount, duration in RAZORPAY_PLANS.items()
            ]
            btn = rzp_rows + [
                [
                    InlineKeyboardButton('• ʀᴇꜰᴇʀ ꜰʀɪᴇɴᴅꜱ', callback_data='reffff'),
                    InlineKeyboardButton('ꜰʀᴇᴇ ᴛʀɪᴀʟ •', callback_data='give_trial')
                ],
                [
                    InlineKeyboardButton('💳 ᴜᴘɪ / ᴏᴛʜᴇʀ', callback_data='upi_info'),
                    InlineKeyboardButton('📋 ᴍʏ ᴘʟᴀɴ', callback_data='myplan_cb')
                ],
                [
                    InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ʜᴏᴍᴇ ⇋', callback_data='start')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(btn)
            await client.edit_message_media(
                chat_id=query.message.chat.id,
                message_id=query.message.id,
                media=InputMediaPhoto(media=SUBSCRIPTION, caption=script.BPREMIUM_TXT, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.exception("Exception in 'premium_info' callback")


    elif query.data == "buy_info":
        try:
            from plugins.Premium import format_plan_label
            rzp_rows = [
                [InlineKeyboardButton(f"💳 {format_plan_label(duration)} Pʀᴇᴍɪᴜᴍ — ₹{amount}", callback_data=f"buy_{amount}")]
                for amount, duration in RAZORPAY_PLANS.items()
            ]
            btn = rzp_rows + [
                [
                    InlineKeyboardButton('💳 ʀᴀᴢᴏʀᴘᴀʏ ɪɴꜰᴏ', callback_data='star_info'),
                    InlineKeyboardButton('🏦 ᴜᴘɪ', callback_data='upi_info')
                ],
                [
                    InlineKeyboardButton('⇋ ʙᴀᴄᴋ ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ⇋', callback_data='premium_info')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(btn)
            await client.edit_message_media(
                chat_id=query.message.chat.id,
                message_id=query.message.id,
                media=InputMediaPhoto(media=SUBSCRIPTION, caption=script.PREMIUM_TEXT, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.exception("Exception in 'buy_info' callback")

    elif query.data == "upi_info":
        try:
            btn = [[
                InlineKeyboardButton('💳 ɪɴsᴛᴀɴᴛ ᴀᴜᴛᴏ-ʙᴜʏ (ʀᴀᴢᴏʀᴘᴀʏ)', callback_data='star_info'),
            ],[
                InlineKeyboardButton('• ꜱᴇɴᴅ  ᴘᴀʏᴍᴇɴᴛ ꜱᴄʀᴇᴇɴꜱʜᴏᴛ •', url=OWNER_LNK),
            ],[
                InlineKeyboardButton('⇋ ʙᴀᴄᴋ ⇋', callback_data='buy_info')
            ]]
            reply_markup = InlineKeyboardMarkup(btn)
            await client.edit_message_media(
                chat_id=query.message.chat.id,
                message_id=query.message.id,
                media=InputMediaPhoto(media=SUBSCRIPTION, caption=script.PREMIUM_UPI_TEXT.format(OWNER_UPI_ID), parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.exception("Exception in 'upi_info' callback")

    elif query.data in ("star_info", "razorpay_info"):
        try:
            from plugins.Premium import format_plan_label
            buttons = [
                [InlineKeyboardButton(f"💳 {format_plan_label(days)} Pʀᴇᴍɪᴜᴍ — ₹{amount}", callback_data=f"buy_{amount}")]
                for amount, days in RAZORPAY_PLANS.items()
            ]
            buttons.append([InlineKeyboardButton("⋞ ʙᴀᴄᴋ", callback_data="buy_info")])
            reply_markup = InlineKeyboardMarkup(buttons)
            await client.edit_message_media(
                chat_id=query.message.chat.id,
                message_id=query.message.id,
                media=InputMediaPhoto(media=SUBSCRIPTION, caption=script.PREMIUM_RAZORPAY_TEXT, parse_mode=enums.ParseMode.HTML),
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.exception("Exception in 'razorpay_info' callback")


    elif query.data.startswith("grp_pm"):
        _, grp_id = query.data.split("#")
        user_id = query.from_user.id if query.from_user else None
        if not await is_check_admin(client, int(grp_id), user_id):
            return await query.answer(script.NT_ADMIN_ALRT_TXT, show_alert=True)

        btn = await group_setting_buttons(int(grp_id))
        dreamx = await client.get_chat(int(grp_id))
        await query.message.edit(text=f"ᴄʜᴀɴɢᴇ ʏᴏᴜʀ ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ ✅\nɢʀᴏᴜᴘ ɴᴀᴍᴇ - '{dreamx.title}'</b>⚙", reply_markup=InlineKeyboardMarkup(btn))

    elif query.data.startswith("removegrp"):
        user_id = query.from_user.id
        data = query.data
        grp_id = int(data.split("#")[1])
        if not await is_check_admin(client, grp_id, query.from_user.id):
            return await query.answer(script.NT_ADMIN_ALRT_TXT, show_alert=True)
        await db.remove_group_connection(grp_id, user_id)
        await query.answer("Group removed from your connections.", show_alert=True)
        connected_groups = await db.get_connected_grps(user_id)
        if not connected_groups:
            await query.edit_message_text("Nᴏ Cᴏɴɴᴇᴄᴛᴇᴅ Gʀᴏᴜᴘs Fᴏᴜɴᴅ .")
            return
        group_list = []
        for group in connected_groups:
            try:
                Chat = await client.get_chat(group)
                group_list.append([
                    InlineKeyboardButton(
                        text=Chat.title, callback_data=f"grp_pm#{Chat.id}")
                ])
            except Exception as e:
                print(f"Error In PM Settings Button - {e}")
                pass
        await query.edit_message_text(
            "⚠️ ꜱᴇʟᴇᴄᴛ ᴛʜᴇ ɢʀᴏᴜᴘ ᴡʜᴏꜱᴇ ꜱᴇᴛᴛɪɴɢꜱ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ.\n\n"
            "ɪꜰ ʏᴏᴜʀ ɢʀᴏᴜᴘ ɪꜱ ɴᴏᴛ ꜱʜᴏᴡɪɴɢ ʜᴇʀᴇ,\n"
            "ᴜꜱᴇ /reload ɪɴ ᴛʜᴀᴛ ɢʀᴏᴜᴘ ᴀɴᴅ ɪᴛ ᴡɪʟʟ ᴀᴘᴘᴇᴀʀ ʜᴇʀᴇ.",
            reply_markup=InlineKeyboardMarkup(group_list)
        )

    elif query.data.startswith("setgs"):
        ident, set_type, status, grp_id = query.data.split("#")
        userid = query.from_user.id if query.from_user else None
        if not await is_check_admin(client, int(grp_id), userid):
            await query.answer(script.NT_ADMIN_ALRT_TXT, show_alert=True)
            return
        if status == "True":
            await save_group_settings(int(grp_id), set_type, False)
            await query.answer("ᴏꜰꜰ ✗")
        else:
            await save_group_settings(int(grp_id), set_type, True)
            await query.answer("ᴏɴ ✓")
        settings = await get_settings(int(grp_id))
        if settings is not None:
            btn = await group_setting_buttons(int(grp_id))
            reply_markup = InlineKeyboardMarkup(btn)
            await query.message.edit_reply_markup(reply_markup)
    await query.answer(MSG_ALRT)


async def auto_filter(client, msg, spoll=False):
    """
    Core auto_filter logic with timing/debug logging removed.
    """
    curr_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()

    async def _schedule_delete(sent_obj, orig_msg, delay):
        try:
            await asyncio.sleep(delay)
            try:
                await sent_obj.delete()
            except Exception:
                pass
            # Keep user/group member messages intact; only delete bot message
        except Exception:
            pass
    m = None

    try:
        if not spoll:
            message = msg
            if message.text.startswith("/"):
                return
            if re.findall(r"((^\/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text):
                return
            if is_conversational_chat(message.text):
                return
            if len(message.text) < 100:
                message_text = message.text or ""
                parsed = parse_user_query(message_text)
                search = parsed.get("title") or message_text.strip()
                search = re.sub(r"\s+", " ", search).strip()
                if not search:
                    return

                stick_id = "CAACAgIAAxkBAAEPhm5o439f8A4sUGO2VcnBFZRRYxAxmQACtCMAAphLKUjeub7NKlvk2TYE"
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton(f'🔎 sᴇᴀʀᴄʜɪɴɢ {search}', callback_data="hiding")]]
                )
                try:
                    m = await message.reply_sticker(sticker=stick_id, reply_markup=keyboard)
                except Exception as e:
                    logger.exception("reply_sticker failed: %s", e)

                key = f"{message.chat.id}-{message.id}"
                user_id = message.from_user.id if message.from_user else 0
                sess = GLOBAL_SESSION_MANAGER.get_or_create(key, message_text, message.chat.id, user_id)
                if sess.active_filters:
                    ACTIVE_FILTERS[key] = sess.active_filters.copy()
                    cache_set_field(str(key), "buttons_query", json.dumps(sess.active_filters))
                else:
                    clear_active_filters(key)

                query_input = sess.get_query_input() if sess.active_filters else search

                files, offset, total_results = await get_search_results(message.chat.id, query_input, offset=0, filter=True, session=sess)

                settings = await get_settings(message.chat.id)
                if not files:
                    if settings.get("spell_check"):
                        ai_sts = await m.edit('🤖 ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ, ᴀɪ ɪꜱ ᴄʜᴇᴄᴋɪɴɢ ʏᴏᴜʀ ꜱᴘᴇʟʟɪɴɢ...')
                        is_misspelled = await ai_spell_check(chat_id=message.chat.id, wrong_name=search)

                        if is_misspelled:
                            await ai_sts.edit(f'✅ Aɪ Sᴜɢɢᴇsᴛᴇᴅ: <code>{is_misspelled}</code>\n🔍 Searching for it...')
                            message.text = is_misspelled
                            await ai_sts.delete()
                            return await auto_filter(client, message)
                        await ai_sts.delete()
                        result = await advantage_spell_chok(client, message)
                        return result
                    else:
                        try:
                            if m:
                                await m.delete()
                        except Exception:
                            pass
                        result = await advantage_spell_chok(client, message)
                        return result
            else:
                return
        else:
            # spoll branch
            message = msg.message.reply_to_message
            search, files, offset, total_results = spoll
            m = await message.reply_text(f'🔎 sᴇᴀʀᴄʜɪɴɢ {search}', reply_to_message_id=message.id)
            settings = await get_settings(message.chat.id)
            await msg.message.delete()

        key = f"{message.chat.id}-{message.id}"
        FRESH[key] = search
        temp.GETALL[key] = files
        cache_save_getall(key, [f.file_id for f in files])
        temp.SHORT[message.from_user.id] = message.chat.id

        active_chip = sess.get_filter_chip() if 'sess' in locals() and sess else get_filter_chip_label(get_active_filters(key))
        req = message.from_user.id if message.from_user else 0
        btn = build_search_buttons(files, key, current_offset=0, total_results=total_results, req=req, settings=settings, active_filter=active_chip)

        if settings.get('imdb'):
            imdb = await get_posterx(search, file=(files[0]).file_name) if TMDB_POSTERS else await get_poster(search, file=(files[0]).file_name)
        else:
            imdb = None

        cur_time = datetime.now(pytz.timezone('Asia/Kolkata')).time()
        time_difference = timedelta(hours=cur_time.hour, minutes=cur_time.minute, seconds=(cur_time.second+(cur_time.microsecond/1000000))) - \
            timedelta(hours=curr_time.hour, minutes=curr_time.minute,
                      seconds=(curr_time.second+(curr_time.microsecond/1000000)))
        remaining_seconds = "{:.2f}".format(time_difference.total_seconds())

        TEMPLATE = script.IMDB_TEMPLATE_TXT
        settings = await get_settings(message.chat.id)
        if settings.get('template'):
            TEMPLATE = settings['template']

        if imdb:
            cap = TEMPLATE.format(
                query=search,
                title=imdb['title'],
                votes=imdb['votes'],
                aka=imdb["aka"],
                seasons=imdb["seasons"],
                box_office=imdb['box_office'],
                localized_title=imdb['localized_title'],
                kind=imdb['kind'],
                imdb_id=imdb["imdb_id"],
                cast=imdb['cast'],
                runtime=imdb['runtime'],
                countries=imdb['countries'],
                certificates=imdb['certificates'],
                languages=imdb['languages'],
                director=imdb['director'],
                writer=imdb['writer'],
                producer=imdb['producer'],
                composer=imdb['composer'],
                cinematographer=imdb['cinematographer'],
                music_team=imdb['music_team'],
                distributors=imdb['distributors'],
                release_date=imdb['release_date'],
                year=imdb['year'],
                genres=imdb['genres'],
                poster=imdb['poster'],
                plot=imdb['plot'] if settings.get('button') else "N/A",
                rating=imdb['rating'],
                url=imdb['url'],
                **locals()
            )
            temp.IMDB_CAP[message.from_user.id] = cap
            if not settings.get('button'):
                cap += "\n\n<b><u>Your Requested Files Are Here</u></b>\n\n"
                for idx, file in enumerate(files, start=1):
                    cap += f"<b>\n{idx}. <a href='https://telegram.me/{temp.U_NAME}?start=file_{message.chat.id}_{file.file_id}'>[{get_size(file.file_size)}] {format_clean_file_item(file, max_len=0)}\n</a></b>"
        else:
            temp.IMDB_CAP[message.from_user.id] = None
            if ULTRA_FAST_MODE:
                if settings.get('button'):
                    cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {message.from_user.mention}\n⚜️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ : ⚡ {message.chat.title or temp.B_LINK or 'iP Update'} \n\n<u>Your Requested Files Are Here</u> \n\n</b>"
                else:
                    cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {message.from_user.mention}\n⚜️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ : ⚡ {message.chat.title or temp.B_LINK or 'iP Update'} \n\n<u>Your Requested Files Are Here</u> \n\n</b>"
                    for idx, file in enumerate(files, start=1):
                        cap += f"<b>\n{idx}. <a href='https://telegram.me/{temp.U_NAME}?start=file_{message.chat.id}_{file.file_id}'>[{get_size(file.file_size)}] {format_clean_file_item(file, max_len=0)}\n</a></b>"
            else:
                if settings.get('button'):
                    cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n🧱 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {message.from_user.mention}\n⚜️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ : ⚡ {message.chat.title or temp.B_LINK or 'iP Update'} \n\n<u>Your Requested Files Are Here</u> \n\n</b>"
                else:
                    cap = f"<b>🏷 ᴛɪᴛʟᴇ : <code>{search}</code>\n🧱 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ : <code>{total_results}</code>\n⏰ ʀᴇsᴜʟᴛ ɪɴ : <code>{remaining_seconds} Sᴇᴄᴏɴᴅs</code>\n\n📝 ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : {message.from_user.mention}\n⚜️ ᴘᴏᴡᴇʀᴇᴅ ʙʏ : ⚡ {message.chat.title or temp.B_LINK or 'iP Update'} \n\n<u>Your Requested Files Are Here</u> \n\n</b>"

                    for idx, file in enumerate(files, start=1):
                        cap += f"<b>\n{idx}. <a href='https://telegram.me/{temp.U_NAME}?start=file_{message.chat.id}_{file.file_id}'>[{get_size(file.file_size)}] {format_clean_file_item(file, max_len=0)}\n</a></b>"

        sent = None
        try:
            if imdb and imdb.get('poster'):
                try:
                    if TMDB_POSTERS:
                        photo = imdb.get('backdrop') if imdb.get('backdrop') and LANDSCAPE_POSTER else imdb.get('poster')
                    else:
                        photo = imdb.get('poster')
                    sent = await message.reply_photo(photo=photo, caption=cap, reply_markup=InlineKeyboardMarkup(btn), parse_mode=enums.ParseMode.HTML)
                    if m:
                        await m.delete()
                except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                    pic = imdb.get('poster')
                    poster = pic.replace('.jpg', "._V1_UX360.jpg")
                    sent = await message.reply_photo(photo=poster, caption=cap, reply_markup=InlineKeyboardMarkup(btn), parse_mode=enums.ParseMode.HTML)
                    if m:
                        await m.delete()
                except Exception as e:
                    logger.exception(e)
                    sent = await message.reply_text(text=cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
            else:
                sent = await message.reply_text(text=cap, reply_markup=InlineKeyboardMarkup(btn), disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML)
                if m:
                    await m.delete()
        except Exception as e:
            logger.exception("Failed to send result: %s", e)
            return

        try:
            if settings.get('auto_delete'):
                asyncio.create_task(_schedule_delete(sent, message, DELETE_TIME))
        except KeyError:
            try:
                await save_group_settings(message.chat.id, 'auto_delete', True)
            except Exception:
                pass
            asyncio.create_task(_schedule_delete(sent, message, DELETE_TIME))
        return

    except Exception as e:
        logger.exception(e)
        return

async def ai_spell_check(chat_id, wrong_name):
    async def search_movie(wrong_name):
        search_results = imdb.search_movie(wrong_name)
        movie_list = [movie['title'] for movie in search_results]
        return movie_list
    movie_list = await search_movie(wrong_name)
    if not movie_list:
        return
    for _ in range(5):
        closest_match = process.extractOne(wrong_name, movie_list)
        if not closest_match or closest_match[1] <= 80:
            return
        movie = closest_match[0]
        files, _, _ = await get_search_results(chat_id=chat_id, query=movie)
        if files:
            return movie
        movie_list.remove(movie)


async def advantage_spell_chok(client, message):
    mv_id = message.id
    search = message.text
    chat_id = message.chat.id
    settings = await get_settings(chat_id)
    query = re.sub(
        r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
        "", message.text, flags=re.IGNORECASE)
    query = query.strip() + " movie"
    try:
        movies = await get_poster(search, bulk=True)
    except:
        k = await message.reply(script.I_CUDNT.format(message.from_user.mention))
        await asyncio.sleep(60)
        try:
            await k.delete()
        except Exception:
            pass
        return
    if not movies:
        google = search.replace(" ", "+")
        button = [[InlineKeyboardButton(
            "🔍 ᴄʜᴇᴄᴋ sᴘᴇʟʟɪɴɢ ᴏɴ ɢᴏᴏɢʟᴇ 🔍", url=f"https://www.google.com/search?q={google}")]]
        k = await message.reply_text(text=script.I_CUDNT.format(search), reply_markup=InlineKeyboardMarkup(button))
        await asyncio.sleep(60)
        try:
            await k.delete()
        except Exception:
            pass
        return
    user = message.from_user.id if message.from_user else 0
    buttons = [
        [InlineKeyboardButton(text=movie.get('title'), callback_data=f"spol#{movie.movieID}#{user}")
         ] for movie in movies]

    buttons.append([InlineKeyboardButton(
        text="🚫 ᴄʟᴏsᴇ 🚫", callback_data='close_data')])
    d = await message.reply_text(text=script.CUDNT_FND.format(message.from_user.mention), reply_markup=InlineKeyboardMarkup(buttons), reply_to_message_id=message.id)
    await asyncio.sleep(60)
    try:
        await d.delete()
    except Exception:
        pass
