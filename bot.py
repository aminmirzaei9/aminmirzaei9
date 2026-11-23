"""بات تلگرام «غفون» — حکم با اعلام دست (۴ نفره، تیمی).

اجرا:
    export BOT_TOKEN=توکن_ربات
    python bot.py
یا توکن را در config.json بگذارید.
"""
from __future__ import annotations

import html
import json
import logging
import os
import random
import time

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                      MenuButton, WebAppInfo)
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler, ContextTypes,
                          MessageHandler, filters)
from aiohttp import web as aiohttp_web

import graphics as G
from engine import (Room, GameError, card_name, card_suit, card_rank, SUITS, SUIT_SYMBOLS,
                    TEAM_NAMES, TEAM_COLORS, TEAM_EMOJI)

BASE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(BASE, "assets", "tmp")
os.makedirs(TMP, exist_ok=True)
SAVE_PATH = os.path.join(BASE, "rooms.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ghafoon")

ROOMS: dict[int, Room] = {}
RT: dict[int, dict] = {}
UID_ROOM: dict[int, int] = {}

# ---------------- مینی‌اپ (نسخه وب) ----------------
WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEB_DIR = os.path.join(BASE, "web")
APP: Application | None = None
WEB_RUNNER = None
EVENTS: dict[int, list] = {}
EVENT_SEQ: dict[int, int] = {}


# ---------------- ابزارها ----------------
def esc(s) -> str:
    return html.escape(str(s))


def get_token() -> str | None:
    t = os.environ.get("BOT_TOKEN")
    if t:
        return t
    cfg = os.path.join(BASE, "config.json")
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as f:
                return json.load(f).get("token")
        except Exception:
            return None
    return None


def save_rooms():
    try:
        data = {str(c): r.to_dict() for c, r in ROOMS.items()}
        with open(SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        log.warning("save_rooms: %s", e)


def load_rooms():
    if not os.path.exists(SAVE_PATH):
        return
    try:
        with open(SAVE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for c, d in data.items():
            ROOMS[int(c)] = Room.from_dict(d)
    except Exception as e:
        log.warning("load_rooms: %s", e)


def rt(chat_id: int) -> dict:
    return RT.setdefault(chat_id, {"jobs": [], "table_msg": None, "hand_msg": {},
                                   "bid_msg": {}, "lobby_msg": None, "trump_msg": None,
                                   "swap_seat": None})


def cancel_jobs(chat_id: int):
    for j in RT.get(chat_id, {}).get("jobs", []):
        try:
            j.schedule_removal()
        except Exception:
            pass
    RT.setdefault(chat_id, {})["jobs"] = []


def add_job(context, chat_id: int, job):
    rt(chat_id)["jobs"].append(job)


def seat_name(room: Room, seat: int) -> str:
    uid = room.seats[seat]
    return room.players.get(uid, "؟") if uid else "؟"


def names_map(room: Room) -> dict:
    return {s: seat_name(room, s) for s in range(4)}


def find_room_for_user(uid: int) -> Room | None:
    cid = UID_ROOM.get(uid)
    return ROOMS.get(cid) if cid is not None else None


# ---------------- حالت وب / مینی‌اپ تلگرام ----------------
def parse_init_user(init_data: str) -> int | None:
    """شناسه‌ی کاربر را از initData وب‌اپ استخراج می‌کند (بدون تایید امضا برای سادگی)."""
    try:
        from urllib.parse import parse_qs
        params = parse_qs(init_data or "")
        user_json = params.get("user", [None])[0]
        if not user_json:
            return None
        import json as _json
        user = _json.loads(user_json)
        return int(user["id"])
    except Exception:
        return None


async def web_ensure_room(uid: int, name: str) -> Room:
    """اتاق وب برای کاربر را پیدا می‌کند یا می‌سازد."""
    room = find_room_for_user(uid)
    if room:
        return room
    chat_id = uid  # برای وب، chat_id برابر uid است (چت مجازی)
    room = Room(chat_id, uid, single=True)
    room.web = True
    room.add_player(uid, name)
    for i in range(3):
        room.add_bot(f"ربات {G.fa(i + 1)}")
    ROOMS[chat_id] = room
    UID_ROOM[uid] = chat_id
    save_rooms()
    return room


# ---------------- وضعیت برای مینی‌اپ وب ----------------
def room_web_state(room: Room, seat: int | None) -> dict:
    """چینش اتاق را به دیکشنری برای کلاینت وب تبدیل می‌کند."""
    names = names_map(room)
    legal = []
    if seat is not None and room.state == "play" and room.turn == seat:
        legal = room.legal_cards(seat)
    return {
        "state": room.state,
        "seat": seat,
        "scores": room.scores,
        "round": room.round_no,
        "target": room.target,
        "names": [names[i] for i in range(4)],
        "trump": room.trump,
        "bid_max": room.bid_max,
        "bid_value": room.bid_value,
        "ruler": room.ruler,
        "turn": room.turn,
        "current_bidder": room.current_bidder(),
        "played": [{"seat": s, "card": c} for s, c in room.played],
        "hand": list(room.hands[seat]) if seat is not None else [],
        "legal": legal,
    }


def web_room_for_user(uid: int) -> Room | None:
    """اتاق وب مربوط به کاربر را پیدا می‌کند (بر اساس UID_ROOM)."""
    return find_room_for_user(uid)


# ---------------- ارسال/ویرایش پیام ----------------
def is_web(chat_id: int) -> bool:
    room = ROOMS.get(chat_id)
    return bool(room and getattr(room, "web", False))


def push_event(chat_id: int, text: str):
    """در حالت وب، به‌جای ارسال پیام تلگرام، رویداد برای مینی‌اپ ذخیره می‌شود."""
    seq = EVENT_SEQ.get(chat_id, 0) + 1
    EVENT_SEQ[chat_id] = seq
    EVENTS.setdefault(chat_id, []).append({"seq": seq, "text": text})
    if len(EVENTS[chat_id]) > 200:
        EVENTS[chat_id] = EVENTS[chat_id][-200:]
    log.info("رویداد %s: %s", chat_id, text)


def events_since(chat_id: int, seq: int) -> list:
    return [e for e in EVENTS.get(chat_id, []) if e["seq"] > seq]


async def say(context, chat_id: int, text: str):
    """ارسال پیام؛ در حالت وب به رویداد تبدیل می‌شود."""
    if is_web(chat_id):
        push_event(chat_id, text)
        return
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        log.debug("say %s: %s", chat_id, e)


async def send_photo(context, chat_id: int, img, caption: str | None = None, kb=None):
    if is_web(chat_id):
        return None
    path = os.path.join(TMP, f"s{chat_id}_{int(time.time() * 1000)}_{random.randint(0, 9999)}.png")
    img.save(path)
    try:
        with open(path, "rb") as f:
            return await context.bot.send_photo(chat_id=chat_id, photo=f, caption=caption, reply_markup=kb)
    except Exception as e:
        log.warning("send_photo %s: %s", chat_id, e)
        return None


async def edit_photo(context, chat_id: int, msg_id: int | None, img, caption: str | None = None, kb=None):
    if is_web(chat_id) or not msg_id:
        return
    path = os.path.join(TMP, f"e{chat_id}_{msg_id}.png")
    img.save(path)
    try:
        media = InputMediaPhoto(media=open(path, "rb"), caption=caption)
        await context.bot.edit_message_media(chat_id=chat_id, message_id=msg_id, media=media, reply_markup=kb)
    except Exception as e:
        log.debug("edit_photo %s/%s: %s", chat_id, msg_id, e)


async def edit_text(context, chat_id: int, msg_id: int | None, text: str, kb=None):
    if not msg_id:
        return
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text,
                                            parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        log.debug("edit_text %s/%s: %s", chat_id, msg_id, e)


# ---------------- نقشه‌ی اتاق‌ها برای مینی‌اپ (room_id -> chat_id) ----------------
ROOM_MAP: dict[str, int] = {}


def room_from_room_id(room_id: str) -> Room | None:
    chat_id = ROOM_MAP.get(room_id)
    return ROOMS.get(chat_id) if chat_id is not None else None


def web_ensure_room_for_user(uid: int, name: str, room_id: str | None = None) -> tuple[Room, bool]:
    """اتاق را پیدا می‌کند یا می‌سازد. خروجی: (اتاق، آیا_جدید_است؟)"""
    if room_id:
        room = room_from_room_id(room_id)
        if room and uid not in room.players and len(room.players) < 4:
            room.add_player(uid, name)
            UID_ROOM[uid] = room.chat_id
            save_rooms()
            push_event(room.chat_id, f"👤 {esc(name)} به بازی پیوست.")
            return room, False
        if room:
            return room, False  # قبلاً عضو است
    # جستجو در اتاق‌های موجود که کاربر عضوشان است
    chat_id = UID_ROOM.get(uid)
    if chat_id and chat_id in ROOMS:
        return ROOMS[chat_id], False
    # ساخت اتاق جدید
    chat_id = uid
    room = Room(chat_id, uid, single=False, room_id=room_id)
    room.web = True
    room.add_player(uid, name)
    ROOMS[chat_id] = room
    UID_ROOM[uid] = chat_id
    if room.room_id:
        ROOM_MAP[room.room_id] = chat_id
    save_rooms()
    return room, True


# ---------------- API مینی‌اپ وب ----------------
async def web_init(request: aiohttp_web.Request) -> aiohttp_web.Response:
    init_data = request.query.get("initData", "")
    uid = parse_init_user(init_data)
    if uid is None:
        return aiohttp_web.json_response({"ok": False, "error": "no_user"}, status=401)
    try:
        from urllib.parse import parse_qs
        import json as _json
        params = parse_qs(init_data or "")
        user_json = params.get("user", [None])[0]
        name = "کاربر"
        if user_json:
            user = _json.loads(user_json)
            name = user.get("first_name", "کاربر")
    except Exception:
        name = "کاربر"
    room_id = request.query.get("room_id") or None
    room, is_new = web_ensure_room_for_user(uid, name, room_id)
    seat = room.seat_of(uid)
    state = room_web_state(room, seat)
    seq = EVENT_SEQ.get(room.chat_id, 0)
    share_url = ""
    try:
        base = os.environ.get("WEB_URL", "")
        if base:
            share_url = f"{base}?room_id={room.room_id}"
    except Exception:
        pass
    return aiohttp_web.json_response({
        "ok": True, "uid": uid, "seat": seat, "room_id": room.room_id,
        "is_host": uid == room.host_id, "is_new": is_new,
        "state": state, "seq": seq, "share_url": share_url,
    })


async def web_state(request: aiohttp_web.Request) -> aiohttp_web.Response:
    init_data = request.query.get("initData", "")
    uid = parse_init_user(init_data)
    if uid is None:
        return aiohttp_web.json_response({"ok": False, "error": "no_user"}, status=401)
    try:
        seq = int(request.query.get("seq", "0"))
    except ValueError:
        seq = 0
    room_id = request.query.get("room_id") or None
    room = None
    if room_id:
        room = room_from_room_id(room_id)
    if not room:
        chat_id = UID_ROOM.get(uid)
        if chat_id and chat_id in ROOMS:
            room = ROOMS[chat_id]
    if not room:
        return aiohttp_web.json_response({"ok": False, "error": "no_room"}, status=404)
    seat = room.seat_of(uid)
    return aiohttp_web.json_response({
        "ok": True, "state": room_web_state(room, seat),
        "seq": EVENT_SEQ.get(room.chat_id, 0),
        "events": events_since(room.chat_id, seq),
    })


async def web_action(request: aiohttp_web.Request) -> aiohttp_web.Response:
    try:
        body = await request.json()
    except Exception:
        return aiohttp_web.json_response({"ok": False, "error": "bad_json"}, status=400)
    init_data = body.get("initData", "")
    uid = parse_init_user(init_data)
    if uid is None:
        return aiohttp_web.json_response({"ok": False, "error": "no_user"}, status=401)
    action = body.get("action", "")
    payload = body.get("payload", {}) or {}
    room_id = body.get("room_id") or None
    room = None
    if room_id:
        room = room_from_room_id(room_id)
    if not room:
        chat_id = UID_ROOM.get(uid)
        if chat_id and chat_id in ROOMS:
            room = ROOMS[chat_id]
    if not room:
        return aiohttp_web.json_response({"ok": False, "error": "no_room"}, status=404)
    chat_id = room.chat_id
    seat = room.seat_of(uid)
    is_host = (uid == room.host_id)

    try:
        if action == "create-room":
            if not is_host:
                return aiohttp_web.json_response({"ok": False, "error": "not_host"}, status=403)
            if room.state != "lobby":
                return aiohttp_web.json_response({"ok": False, "error": "game_started"}, status=400)
            # تنظیمات اولیه از سمت میزبان
            tgt = int(payload.get("target", 100))
            room.target = tgt
            save_rooms()
            push_event(chat_id, f"⚙️ میزبان امتیاز هدف را {G.fa(tgt)} تنظیم کرد.")
            return aiohttp_web.json_response({
                "ok": True, "room_id": room.room_id,
                "state": room_web_state(room, seat),
                "seq": EVENT_SEQ.get(chat_id, 0),
                "events": events_since(chat_id, 0),
            })

        if action == "join-room":
            if not room_id:
                return aiohttp_web.json_response({"ok": False, "error": "no_room_id"}, status=400)
            target_room = room_from_room_id(room_id)
            if not target_room:
                return aiohttp_web.json_response({"ok": False, "error": "room_not_found"}, status=404)
            if uid in target_room.players:
                return aiohttp_web.json_response({"ok": False, "error": "already_joined"}, status=400)
            if len(target_room.players) >= 4:
                return aiohttp_web.json_response({"ok": False, "error": "room_full"}, status=400)
            target_room.add_player(uid, q_from_user_name(uid, init_data) or "کاربر")
            UID_ROOM[uid] = target_room.chat_id
            save_rooms()
            push_event(target_room.chat_id, f"👤 {esc(target_room.players[uid])} به بازی پیوست.")
            state = room_web_state(target_room, target_room.seat_of(uid))
            return aiohttp_web.json_response({
                "ok": True, "room_id": target_room.room_id, "seat": target_room.seat_of(uid),
                "state": state, "seq": EVENT_SEQ.get(target_room.chat_id, 0),
                "events": events_since(target_room.chat_id, 0),
                "is_host": uid == target_room.host_id,
            })

        if action == "start":
            if not is_host:
                return aiohttp_web.json_response({"ok": False, "error": "not_host"}, status=403)
            if room.state != "lobby":
                return aiohttp_web.json_response({"ok": False, "error": "already_started"}, status=400)
            # اگر تعداد بازیکن کمتر از ۴ است، جای خالی را با ربات پر می‌کند
            while len(room.players) < 4:
                room.add_bot(f"ربات {G.fa(len(room.players) + 1)}")
            err = room.start()
            if err:
                return aiohttp_web.json_response({"ok": False, "error": err}, status=400)
            cancel_jobs(chat_id)
            RT[chat_id] = {"jobs": [], "table_msg": None, "hand_msg": {},
                           "bid_msg": {}, "lobby_msg": None, "trump_msg": None,
                           "swap_seat": None}
            for u in room.seats:
                if u is not None:
                    UID_ROOM[u] = chat_id
            save_rooms()
            push_event(chat_id, "🎮 بازی شروع شد!")
            await web_start_round(chat_id)
            return aiohttp_web.json_response({
                "ok": True, "state": room_web_state(room, seat),
                "seq": EVENT_SEQ.get(chat_id, 0),
                "events": events_since(chat_id, 0),
            })

        if action == "swap":
            if not is_host:
                return aiohttp_web.json_response({"ok": False, "error": "not_host"}, status=403)
            if room.state != "lobby":
                return aiohttp_web.json_response({"ok": False, "error": "game_started"}, status=400)
            a = int(payload.get("a", -1)); b = int(payload.get("b", -1))
            room.swap_seats(a, b)
            save_rooms()
            push_event(chat_id, f"🪑 صندلی {G.fa(a+1)} و {G.fa(b+1)} جابه‌جا شدند.")
            return aiohttp_web.json_response({
                "ok": True, "state": room_web_state(room, seat),
                "seq": EVENT_SEQ.get(chat_id, 0),
                "events": events_since(chat_id, 0),
            })

        if action == "again":
            if not is_host:
                return aiohttp_web.json_response({"ok": False, "error": "not_host"}, status=403)
            room.scores = [0, 0]
            room.round_log = []
            room.round_no = 0
            room.state = "lobby"
            save_rooms()
            push_event(chat_id, "🔄 بازی جدید آماده است!")
            return aiohttp_web.json_response({
                "ok": True, "state": room_web_state(room, seat),
                "seq": EVENT_SEQ.get(chat_id, 0),
                "events": events_since(chat_id, 0),
            })

        if seat is None:
            return aiohttp_web.json_response({"ok": False, "error": "not_seated"}, status=400)

        if action == "bid":
            if room.state != "bid":
                return aiohttp_web.json_response({"ok": False, "error": "not_bid_phase"}, status=400)
            if seat != room.current_bidder():
                return aiohttp_web.json_response({"ok": False, "error": "not_your_turn"}, status=400)
            value = int(payload.get("value", 0))
            room.place_bid(seat, value)
            push_event(chat_id, f"{names_map(room)[seat]} بید {G.fa(value) if value else 'پاس'} زد.")
            save_rooms()
            await web_advance(chat_id)

        elif action == "trump":
            if room.state != "trump":
                return aiohttp_web.json_response({"ok": False, "error": "not_trump_phase"}, status=400)
            if seat != room.ruler:
                return aiohttp_web.json_response({"ok": False, "error": "not_ruler"}, status=400)
            suit = int(payload.get("suit", 0))
            room.set_trump(seat, suit)
            push_event(chat_id, f"👑 {names_map(room)[seat]} حکم «{SUITS[suit]}» انتخاب کرد.")
            save_rooms()
            await web_begin_turn(None, chat_id)

        elif action == "play":
            if room.state != "play":
                return aiohttp_web.json_response({"ok": False, "error": "not_play_phase"}, status=400)
            if seat != room.turn:
                return aiohttp_web.json_response({"ok": False, "error": "not_your_turn"}, status=400)
            card = int(payload.get("card", -1))
            res = room.play_card(seat, card)
            save_rooms()
            await web_advance(chat_id, trick_result=res)

        elif action == "end":
            if not is_host:
                return aiohttp_web.json_response({"ok": False, "error": "not_host"}, status=403)
            cleanup_room(None, room)
            ROOM_MAP.pop(room.room_id, None)
            return aiohttp_web.json_response({"ok": True, "state": None})

        else:
            return aiohttp_web.json_response({"ok": False, "error": "unknown_action"}, status=400)

    except GameError as e:
        return aiohttp_web.json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        log.exception("web_action error")
        return aiohttp_web.json_response({"ok": False, "error": str(e)}, status=500)

    state = room_web_state(room, room.seat_of(uid)) if room.chat_id in ROOMS else None
    return aiohttp_web.json_response({
        "ok": True, "state": state,
        "seq": EVENT_SEQ.get(chat_id, 0),
        "events": events_since(chat_id, 0),
    })


def q_from_user_name(uid: int, init_data: str) -> str | None:
    """نام کاربر را از initData استخراج می‌کند."""
    try:
        from urllib.parse import parse_qs
        import json as _json
        params = parse_qs(init_data or "")
        user_json = params.get("user", [None])[0]
        if user_json:
            user = _json.loads(user_json)
            return user.get("first_name")
    except Exception:
        pass
    return None


# ---------------- رون stoke هوش مصنوعی در حالت وب ----------------
async def web_advance(chat_id: int, trick_result=None):
    room = ROOMS.get(chat_id)
    if not room:
        return
    if trick_result and trick_result[0] == "trick":
        winner = trick_result[1]
        push_event(chat_id, f"🎯 دست را {names_map(room)[winner]} برد!")
    if room.state == "round_end":
        await web_end_round(chat_id)
        return
    if room.state == "finished":
        await web_finish(chat_id)
        return
    if room.state == "bid":
        seat = room.current_bidder()
        if seat is not None and room.seats[seat] is not None and room.seats[seat] < 0:
            await web_ai_bid(chat_id, seat)
        return
    if room.state == "trump":
        seat = room.ruler
        if seat is not None and room.seats[seat] is not None and room.seats[seat] < 0:
            await web_ai_trump(chat_id)
        return
    if room.state == "play":
        seat = room.turn
        if seat is not None and room.seats[seat] is not None and room.seats[seat] < 0:
            await web_ai_play(chat_id, seat)
        return


async def web_ai_bid(chat_id: int, seat: int):
    room = ROOMS.get(chat_id)
    if not room or room.state != "bid" or room.current_bidder() != seat:
        return
    strength = sum(1 for c in room.hands[seat] if card_rank(c) >= 10)
    want = min(13, max(1, strength))
    if want > room.bid_max and random.random() < 0.8:
        value = want
    elif random.random() < 0.25:
        vals = list(range(room.bid_max + 1, 14))
        value = random.choice(vals) if vals else 0
    else:
        value = 0
    room.place_bid(seat, value)
    push_event(chat_id, f"🤖 {names_map(room)[seat]} {G.fa(value) if value else 'پاس'}.")
    save_rooms()
    await web_advance(chat_id)


async def web_ai_trump(chat_id: int):
    room = ROOMS.get(chat_id)
    if not room or room.state != "trump":
        return
    seat = room.ruler
    counts = [sum(1 for c in room.hands[seat] if card_suit(c) == s) for s in range(4)]
    suit = max(range(4), key=lambda s: (counts[s], -s))
    room.set_trump(seat, suit)
    push_event(chat_id, f"👑 {names_map(room)[seat]} حکم «{SUITS[suit]}» انتخاب کرد.")
    save_rooms()
    await web_begin_turn(None, chat_id)


async def web_ai_play(chat_id: int, seat: int):
    room = ROOMS.get(chat_id)
    if not room or room.state != "play" or room.turn != seat:
        return
    legal = room.legal_cards(seat)
    card = ai_pick(room, seat, legal)
    res = room.play_card(seat, card)
    push_event(chat_id, f"🤖 {names_map(room)[seat]} «{card_name(card)}» بازی کرد.")
    save_rooms()
    await web_advance(chat_id, trick_result=res)


async def web_begin_turn(context, chat_id: int):
    room = ROOMS.get(chat_id)
    if not room:
        return
    if room.round_over():
        await web_end_round(chat_id)
        return
    seat = room.turn
    if seat is not None and room.seats[seat] is not None and room.seats[seat] < 0:
        await web_ai_play(chat_id, seat)


async def web_end_round(chat_id: int):
    room = ROOMS.get(chat_id)
    if not room:
        return
    res = room.score_round()
    save_rooms()
    team_name = TEAM_NAMES[res[0]]
    if res[3]:
        push_event(chat_id, f"✅ تیم {team_name} به اعلام {G.fa(res[2])} رسید ({G.fa(res[1])} دست).")
    else:
        push_event(chat_id, f"❌ تیم حاکم ناکارآمد بود. تیم {team_name} {G.fa(2 * res[2])} گرفت.")
    if room.state == "finished":
        await web_finish(chat_id)
    else:
        import asyncio as _asyncio
        await _asyncio.sleep(3)
        await web_start_round(chat_id)


async def web_finish(chat_id: int):
    room = ROOMS.get(chat_id)
    if not room:
        return
    winner = 0 if room.scores[0] >= room.scores[1] else 1
    push_event(chat_id, f"🏆 پایان بازی! برنده: تیم {TEAM_NAMES[winner]} "
                        f"({G.fa(room.scores[0])} - {G.fa(room.scores[1])})")


async def web_start_round(chat_id: int):
    room = ROOMS.get(chat_id)
    if not room:
        return
    room.new_round()
    save_rooms()
    await web_advance(chat_id)


# ---------------- سرور وب ----------------
async def _web_file(request: aiohttp_web.Request) -> aiohttp_web.Response:
    import pathlib
    path = pathlib.Path(WEB_DIR) / request.match_info["filename"]
    if not path.exists() or not path.is_file():
        return aiohttp_web.Response(status=404)
    content_type = "text/html" if path.suffix == ".html" else \
                   "text/css" if path.suffix == ".css" else \
                   "application/javascript" if path.suffix == ".js" else \
                   "image/png" if path.suffix == ".png" else "application/octet-stream"
    return aiohttp_web.Response(body=path.read_bytes(), content_type=content_type)


async def start_web_server():
    global WEB_RUNNER
    app = aiohttp_web.Application()
    app.router.add_get("/api/init", web_init)
    app.router.add_get("/api/state", web_state)
    app.router.add_post("/api/action", web_action)
    app.router.add_get("/{filename:.*}", _web_file)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    site = aiohttp_web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    WEB_RUNNER = runner
    log.info("مینی‌اپ وب روی پورت %d راه‌اندازی شد", WEB_PORT)


async def stop_web_server(app=None):
    global WEB_RUNNER
    if WEB_RUNNER:
        await WEB_RUNNER.cleanup()
        WEB_RUNNER = None


# ---------------- متن‌ها و کیبوردها ----------------
def lobby_text(room: Room) -> str:
    players = "\n".join(f"• {esc(v)}" for v in room.players.values()) or "• —"
    mode = ("🎮 <b>حالت تک‌فره</b> — شما + ۳ ربات\n\n" if room.single else "")
    return (f"🎴 <b>بازی غفون — حکم با اعلام دست</b>\n\n"
            f"{mode}"
            f"👥 بازیکنان ({len(room.players)}/۴):\n{players}\n\n"
            f"🎯 امتیاز برد: <b>{room.target}</b>\n"
            f"⏱ کارت‌اندازی: ۱۰ ثانیه  |  اعلام دست: ۳۰ ثانیه\n\n"
            + (f"▶️ «شروع بازی» را بزنید.\n"
               f"🪑 برای جابه‌جایی صندلی‌ها (جای ربات‌ها) هم می‌توانید استفاده کنید.\n"
               if room.single else
               f"▶️ «شروع بازی» برای ۴ نفر حقيقی.\n"
               f"🤖 اگر ۴ نفر نداری، «بازی با ربات» را بزن تا جای خالی ربات‌ها پر شود.\n"
               f"🪑 «چیدن صندلی» برای جابه‌جایی جای بازیکنان و ربات‌ها.\n"
               f"⌨️ میزبان می‌تواند به‌جای دکمه بنویسد: /play"))


def lobby_kb(room: Room):
    if room.single:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ شروع بازی (تک‌فره)", callback_data="start")],
            [InlineKeyboardButton("🪑 چیدن صندلی", callback_data="seatmenu")],
            [InlineKeyboardButton("✖️ پایان", callback_data="end")],
        ])
    rows = [[InlineKeyboardButton("➕ عضو شو", callback_data="join")]]
    rows.append([InlineKeyboardButton(f"🎯 {t}", callback_data=f"tgt:{t}") for t in (50, 100, 124, 200)])
    rows.append([InlineKeyboardButton("▶️ شروع بازی (۴ نفر)", callback_data="start")])
    rows.append([InlineKeyboardButton("🤖 بازی با ربات", callback_data="startai"),
                 InlineKeyboardButton("🪑 چیدن صندلی", callback_data="seatmenu")])
    rows.append([InlineKeyboardButton("✖️ پایان", callback_data="end")])
    return InlineKeyboardMarkup(rows)


def seat_menu_text(room: Room, pending: int | None) -> str:
    lines = ["🪑 <b>چیدن صندلی</b>\n\n"]
    for s in range(4):
        mark = " 👈 انتخاب شد" if pending == s else ""
        lines.append(f"صندلی {G.fa(s + 1)}: {esc(seat_name(room, s))}{mark}")
    lines.append("\nبرای جابه‌جایی، دو صندلی را پشت سر هم بزنید.")
    return "\n".join(lines)


def seat_menu_kb(room: Room):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"صندلی {G.fa(s + 1)}", callback_data=f"seat:{s}") for s in range(4)],
        [InlineKeyboardButton("↩️ بازگشت به لابی", callback_data="seatback")],
    ])


async def show_seats(context, room: Room):
    pending = rt(room.chat_id).get("swap_seat")
    await edit_text(context, room.chat_id, rt(room.chat_id).get("lobby_msg"),
                    seat_menu_text(room, pending), seat_menu_kb(room))


def bid_kb(room: Room):
    vals = list(range(room.bid_max + 1, 14))
    rows, row = [], []
    for v in vals:
        row.append(InlineKeyboardButton(G.fa(v), callback_data=f"bid:{v}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("پاس", callback_data="bid:0")])
    return InlineKeyboardMarkup(rows)


def trump_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{SUIT_SYMBOLS[s]} {SUITS[s]}", callback_data=f"trump:{s}") for s in range(4)
    ]])


def play_kb(legal):
    rows, row = [], []
    for c in legal:
        row.append(InlineKeyboardButton(card_name(c), callback_data=f"play:{c}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def table_caption(room: Room) -> str:
    base = (f"🔵 {TEAM_NAMES[0]}: {G.fa(room.scores[0])}   |   "
            f"🔴 {TEAM_NAMES[1]}: {G.fa(room.scores[1])}")
    if room.state == "bid":
        return f"🎴 <b>دور {G.fa(room.round_no)}</b> — مرحله اعلام دست\n{base}\nبیشترین بید: {G.fa(room.bid_max)}"
    if room.state == "trump":
        return f"🎴 <b>دور {G.fa(room.round_no)}</b> — حاکم در حال انتخاب خال حکم…\n{base}"
    if room.state == "play":
        return (f"🎴 <b>دور {G.fa(room.round_no)}</b> — نوبت: {esc(seat_name(room, room.turn))}\n"
                f"{base}\nحکم: {SUITS[room.trump]} | اعلام: {G.fa(room.bid_value)} | "
                f"دست‌ها: {G.fa(room.tricks[0])}-{G.fa(room.tricks[1])}")
    if room.state == "round_end":
        return f"🎴 <b>دور {G.fa(room.round_no)}</b> — پایان دور\n{base}"
    return f"🎴 <b>دور {G.fa(room.round_no)}</b>\n{base}"


# ---------------- لابی ----------------
async def send_lobby(context, room: Room):
    await send_photo(context, room.chat_id, G.make_lobby_banner())
    msg = await context.bot.send_message(chat_id=room.chat_id, text=lobby_text(room),
                                         parse_mode=ParseMode.HTML, reply_markup=lobby_kb(room))
    rt(room.chat_id)["lobby_msg"] = msg.message_id


async def refresh_lobby(context, room: Room):
    await edit_text(context, room.chat_id, rt(room.chat_id).get("lobby_msg"), lobby_text(room), lobby_kb(room))


# ---------------- جریان بازی ----------------
async def start_match(context, chat_id: int):
    room = ROOMS[chat_id]
    err = room.start()
    if err:
        await context.bot.send_message(chat_id=chat_id, text=err)
        return
    cancel_jobs(chat_id)
    RT[chat_id] = {"jobs": [], "table_msg": None, "hand_msg": {}, "bid_msg": {},
                   "lobby_msg": rt(chat_id).get("lobby_msg"), "trump_msg": None,
                   "swap_seat": None}
    for uid in room.seats:
        UID_ROOM[uid] = chat_id
    save_rooms()
    # معرفی در خصوصی
    for seat, uid in enumerate(room.seats):
        if uid is None or uid < 0:
            continue
        partner = (seat + 2) % 4
        team = room.team_of(seat)
        txt = (f"🎴 <b>غفون</b>\n\n"
               f"🪑 صندلی شما: {G.fa(seat + 1)}\n"
               f"تیم شما: {TEAM_EMOJI[team]} {TEAM_NAMES[team]}\n"
               f"🤝 هم‌تیمی شما: {esc(room.players[room.seats[partner]])}\n\n"
               f"کارت‌ها و نوبت‌ها در همین چت خصوصی ارسال می‌شود.")
        try:
            await context.bot.send_message(chat_id=uid, text=txt, parse_mode=ParseMode.HTML)
        except Exception:
            await context.bot.send_message(chat_id=chat_id,
                                           text=f"⚠️ {esc(room.players[uid])} ربات را در خصوصی استارت نکرده است؛ "
                                                f"لطفاً ابتدا به ربات پیام بدهید و دوباره شروع کنید.")
            room.state = "lobby"
            return
    msg = await send_photo(context, chat_id, G.make_table_image(room, names_map(room)),
                           caption=table_caption(room))
    if msg:
        RT[chat_id]["table_msg"] = msg.message_id
    await start_round(context, chat_id)


async def start_round(context, chat_id: int):
    room = ROOMS[chat_id]
    cancel_jobs(chat_id)
    room.new_round()
    await update_table(context, chat_id)
    for seat, uid in enumerate(room.seats):
        if uid is None or uid < 0:
            continue
        img = G.make_hand_image(room.hands[seat], [], False, f"دست شما — دور {G.fa(room.round_no)}")
        msg = await send_photo(context, uid, img, caption="دست شما آماده است؛ منتظر مرحله اعلام دست بمانید.")
        if msg is None:
            await context.bot.send_message(chat_id=chat_id,
                                           text=f"⚠️ ارسال کارت به {esc(room.players[uid])} ممکن نشد.")
            room.state = "lobby"
            return
        RT[chat_id]["hand_msg"][seat] = msg.message_id
    await start_bidding(context, chat_id)


async def start_bidding(context, chat_id: int):
    room = ROOMS[chat_id]
    seat = room.current_bidder()
    uid = room.seats[seat]
    if uid is None or uid < 0:
        await update_table(context, chat_id)
        job = context.application.job_queue.run_once(ai_bid_job, when=2.5,
                                                     data={"chat": chat_id, "seat": seat})
        add_job(context, chat_id, job)
        return
    txt = (f"🔊 <b>مرحله اعلام دست</b>\nنوبت شماست {esc(room.players[uid])}!\n"
           f"بیشترین بید تا الآن: {G.fa(room.bid_max)}\nعددی بالاتر انتخاب کنید یا پاس دهید.")
    msg = await context.bot.send_message(chat_id=uid, text=txt, parse_mode=ParseMode.HTML, reply_markup=bid_kb(room))
    if msg:
        RT[chat_id]["bid_msg"][seat] = msg.message_id
    await update_table(context, chat_id)
    job = context.application.job_queue.run_once(bid_timeout_job, when=30,
                                                 data={"chat": chat_id, "seat": seat})
    add_job(context, chat_id, job)


async def do_bid(context, chat_id: int, seat: int, value: int):
    room = ROOMS[chat_id]
    try:
        res = room.place_bid(seat, value)
    except GameError:
        return
    bid_msg = RT[chat_id]["bid_msg"].get(seat)
    await edit_text(context, room.seats[seat], bid_msg,
                    f"بید شما: {G.fa(value) if value else 'پاس'}", kb=InlineKeyboardMarkup([]))
    if res == "redeal":
        await context.bot.send_message(chat_id=chat_id, text="🔄 همه پاس کردند؛ دوباره کارت می‌دهیم.")
        await start_round(context, chat_id)
        return
    if res == "trump":
        await ask_trump(context, chat_id)
        return
    await start_bidding(context, chat_id)


async def ask_trump(context, chat_id: int):
    room = ROOMS[chat_id]
    uid = room.seats[room.ruler]
    if uid is None or uid < 0:
        await update_table(context, chat_id)
        job = context.application.job_queue.run_once(ai_trump_job, when=2.5, data={"chat": chat_id})
        add_job(context, chat_id, job)
        return
    txt = (f"👑 <b>شما حاکم هستید!</b>\nاعلام شما: {G.fa(room.bid_value)} دست\n"
           f"خال حکم را انتخاب کنید:")
    msg = await context.bot.send_message(chat_id=uid, text=txt, parse_mode=ParseMode.HTML, reply_markup=trump_kb())
    if msg:
        RT[chat_id]["trump_msg"] = msg.message_id
    await update_table(context, chat_id)
    job = context.application.job_queue.run_once(trump_timeout_job, when=30, data={"chat": chat_id})
    add_job(context, chat_id, job)


async def begin_turn(context, chat_id: int):
    room = ROOMS[chat_id]
    cancel_jobs(chat_id)
    if room.round_over():
        await end_round(context, chat_id)
        return
    seat = room.turn
    await update_table(context, chat_id)
    if room.seats[seat] is None or room.seats[seat] < 0:
        job = context.application.job_queue.run_once(ai_play_job, when=2.5,
                                                     data={"chat": chat_id, "seat": seat})
        add_job(context, chat_id, job)
        return
    await update_hands(context, chat_id)
    job = context.application.job_queue.run_once(play_timeout_job, when=10,
                                                 data={"chat": chat_id, "seat": seat})
    add_job(context, chat_id, job)


async def update_hands(context, chat_id: int):
    room = ROOMS[chat_id]
    names = names_map(room)
    for seat, uid in enumerate(room.seats):
        if uid is None or uid < 0:
            continue
        is_turn = (room.state == "play" and room.turn == seat)
        legal = room.legal_cards(seat) if is_turn else []
        if is_turn:
            title = "🟢 نوبت شماست! کارت بازی کنید"
            caption = "نوبت شماست — یک کارت انتخاب کنید."
        elif room.state == "play":
            title = f"دست شما — نوبت {names[room.turn]}"
            caption = f"نوبت: {names[room.turn]}"
        else:
            title = f"دست شما — دور {G.fa(room.round_no)}"
            caption = "منتظر بمانید…"
        img = G.make_hand_image(room.hands[seat], legal, is_turn, title)
        kb = play_kb(legal) if is_turn else InlineKeyboardMarkup([])
        await edit_photo(context, uid, RT[chat_id]["hand_msg"].get(seat), img, caption=caption, kb=kb)


async def update_table(context, chat_id: int):
    room = ROOMS[chat_id]
    img = G.make_table_image(room, names_map(room))
    msg_id = RT[chat_id].get("table_msg")
    if msg_id:
        await edit_photo(context, chat_id, msg_id, img, caption=table_caption(room))
    else:
        msg = await send_photo(context, chat_id, img, caption=table_caption(room))
        if msg:
            RT[chat_id]["table_msg"] = msg.message_id


async def end_round(context, chat_id: int):
    room = ROOMS[chat_id]
    cancel_jobs(chat_id)
    res = room.score_round()
    await update_table(context, chat_id)
    await edit_photo(context, chat_id, RT[chat_id].get("table_msg"),
                     G.make_result_image(room, names_map(room), res),
                     caption=table_caption(room))
    save_rooms()
    if room.state == "finished":
        winner = 0 if room.scores[0] >= room.scores[1] else 1
        await send_photo(context, chat_id, G.make_winner(winner, room.scores), caption="🏆 پایان بازی!")
        await context.bot.send_message(chat_id=chat_id, text="🎉 آفرین! برای بازی دوباره:",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("🔄 بازی دوباره", callback_data="again")]]))
        return
    job = context.application.job_queue.run_once(next_round_job, when=5, data={"chat": chat_id})
    add_job(context, chat_id, job)


# ---------------- جاب‌ها ----------------
async def bid_timeout_job(context):
    data = context.job.data
    chat_id, seat = data["chat"], data["seat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "bid" or room.current_bidder() != seat:
        return
    await context.bot.send_message(chat_id=chat_id, text=f"⏰ {esc(seat_name(room, seat))} پاس کرد (تمام شدن وقت).")
    await do_bid(context, chat_id, seat, 0)


async def trump_timeout_job(context):
    chat_id = context.job.data["chat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "trump":
        return
    suit = random.randint(0, 3)
    room.set_trump(room.ruler, suit)
    await context.bot.send_message(chat_id=chat_id,
                                   text=f"⏰ خال حکم به صورت تصادفی «{SUITS[suit]}» انتخاب شد.")
    await begin_turn(context, chat_id)


async def play_timeout_job(context):
    data = context.job.data
    chat_id, seat = data["chat"], data["seat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "play" or room.turn != seat:
        return
    legal = room.legal_cards(seat)
    card = random.choice(legal)
    res = room.play_card(seat, card)
    await context.bot.send_message(chat_id=chat_id, text=f"⏰ تمام شدن وقت؛ «{card_name(card)}» بازی شد.")
    await update_table(context, chat_id)
    if res and res[0] == "trick":
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"🎯 دست را {esc(seat_name(room, res[1]))} برد!")
    await begin_turn(context, chat_id)


async def next_round_job(context):
    await start_round(context, context.job.data["chat"])


# ---------------- ربات‌های هوشمند ----------------
async def ai_bid_job(context):
    chat_id = context.job.data["chat"]
    seat = context.job.data["seat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "bid" or room.current_bidder() != seat:
        return
    strength = sum(1 for c in room.hands[seat] if card_rank(c) >= 10)
    want = min(13, max(1, strength))
    if want > room.bid_max and random.random() < 0.8:
        value = want
    elif random.random() < 0.25:
        vals = list(range(room.bid_max + 1, 14))
        value = random.choice(vals) if vals else 0
    else:
        value = 0
    await context.bot.send_message(chat_id=chat_id,
                                   text=f"🤖 {esc(seat_name(room, seat))} {G.fa(value) if value else 'پاس'}")
    await do_bid(context, chat_id, seat, value)


async def ai_trump_job(context):
    chat_id = context.job.data["chat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "trump":
        return
    counts = [sum(1 for c in room.hands[room.ruler] if card_suit(c) == s) for s in range(4)]
    suit = max(range(4), key=lambda s: (counts[s], -s))
    room.set_trump(room.ruler, suit)
    await context.bot.send_message(chat_id=chat_id,
                                   text=f"👑 {esc(seat_name(room, room.ruler))} حاکم شد | "
                                        f"حکم: {SUIT_SYMBOLS[suit]} {SUITS[suit]}")
    await begin_turn(context, chat_id)


async def ai_play_job(context):
    chat_id = context.job.data["chat"]
    seat = context.job.data["seat"]
    room = ROOMS.get(chat_id)
    if not room or room.state != "play" or room.turn != seat:
        return
    legal = room.legal_cards(seat)
    card = ai_pick(room, seat, legal)
    res = room.play_card(seat, card)
    await context.bot.send_message(chat_id=chat_id,
                                   text=f"🤖 {esc(seat_name(room, seat))} «{card_name(card)}» بازی کرد.")
    await update_table(context, chat_id)
    if res and res[0] == "trick":
        await context.bot.send_message(chat_id=chat_id,
                                       text=f"🎯 دست را {esc(seat_name(room, res[1]))} برد!")
    await begin_turn(context, chat_id)


def ai_pick(room, seat, legal):
    if not room.played:
        return random.choice(legal)
    lead_suit = card_suit(room.played[0][1])
    best_seat, best_card = room.played[0]
    for s, c in room.played[1:]:
        if room._beats(c, best_card, lead_suit):
            best_seat, best_card = s, c
    if room.team_of(best_seat) == room.team_of(seat):
        return min(legal, key=lambda c: card_rank(c))
    winners = [c for c in legal if room._beats(c, best_card, lead_suit)]
    if winners:
        return min(winners, key=lambda c: card_rank(c))
    return min(legal, key=lambda c: card_rank(c))


# ---------------- دستورات ----------------
async def open_single_lobby(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ساخت/بازکردن لابی تک‌فره در چت خصوصی (شامل زدن Start)."""
    chat = update.effective_chat
    user = update.effective_user
    room = ROOMS.get(chat.id)
    if room and room.state != "finished":
        await refresh_lobby(context, room)
        await update.message.reply_text("🎮 بازی تک‌فره‌ی شما آماده است 👆")
        return
    room = Room(chat.id, user.id, single=True)
    room.add_player(user.id, user.full_name)
    for i in range(3):
        room.add_bot(f"ربات {G.fa(i + 1)}")
    ROOMS[chat.id] = room
    save_rooms()
    await send_lobby(context, room)
    await update.message.reply_text("🎮 بازی تک‌فره آماده است! صندلی‌ها را بچین و «شروع بازی» را بزن.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await open_single_lobby(update, context)
        return
    txt = ("🎴 <b>به بات غفون خوش آمدید!</b>\n\n"
           "این بات بازی <b>حکم با اعلام دست</b> را برای ۴ نفر و به صورت تیمی اجرا می‌کند.\n\n"
           "🔹 <b>روش بازی:</b>\n"
           "👥 <b>گروهی:</b> ربات را به گروه اضافه کنید، /startgame بزنید، ۴ نفر عضو شوید و میزبان شروع کند.\n"
           "🎮 <b>تک‌فره:</b> اینجا در چت خصوصی /startgame بزنید تا با ۳ ربات بازی کنید.\n"
           "🪑 برای جابه‌جایی جای ربات‌ها از دکمه‌ی «چیدن صندلی» استفاده کنید.\n\n"
           "⏱ کارت‌اندازی: ۱۰ ثانیه  |  اعلام دست: ۳۰ ثانیه\n"
           "📋 قوانین: هر دور تا رسیدن به امتیاز اعلام‌شده؛ اگر حاکم نفُکند، حریف ۲×اعلام می‌گیرد.")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        # حالت تک‌فره: بازی کامل در همین چت خصوصی، با ۳ ربات
        await open_single_lobby(update, context)
        return
    room = ROOMS.get(chat.id)
    if room and room.state != "finished":
        await send_lobby(context, room)
        await update.message.reply_text("لابی بازی آماده است 👆")
        return
    room = Room(chat.id, update.effective_user.id)
    room.add_player(update.effective_user.id, update.effective_user.full_name)
    ROOMS[chat.id] = room
    save_rooms()
    await send_lobby(context, room)


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    room = ROOMS.get(chat.id)
    if not room:
        await update.message.reply_text("بازی‌ای نیست؛ با /startgame بسازید.")
        return
    err = room.add_player(update.effective_user.id, update.effective_user.full_name)
    if err:
        await update.message.reply_text(err)
        return
    save_rooms()
    await refresh_lobby(context, room)


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع سریع توسط میزبان (با ربات برای جای خالی)."""
    chat = update.effective_chat
    room = ROOMS.get(chat.id)
    if not room:
        await update.message.reply_text("بازی‌ای نیست؛ با /startgame بساز.")
        return
    if update.effective_user.id != room.host_id:
        await update.message.reply_text("فقط میزبان می‌تواند شروع کند.")
        return
    if room.state != "lobby":
        await update.message.reply_text("بازی از قبل در جریان است.")
        return
    for i in range(4 - len(room.players)):
        room.add_bot(f"ربات {G.fa(i + 1)}")
    save_rooms()
    await start_match(context, chat.id)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    room = ROOMS.get(chat.id)
    if not room:
        return
    if update.effective_user.id != room.host_id:
        await update.message.reply_text("فقط میزبان می‌تواند بازی را پایان دهد.")
        return
    await cleanup_room(context, room)
    await update.message.reply_text("❌ بازی پاک شد.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>راهنمای غفون</b>\n\n"
        "• /startgame — ساخت بازی (در گروه: ۴ نفر حقيقی | در خصوصی: تک‌فره با ربات)\n"
        "• /join — عضو شدن\n"
        "• /play — شروع سریع میزبان (با ربات برای جای خالی)\n"
        "• /cancel — پایان بازی (میزبان)\n"
        "• /help — همین راهنما\n\n"
        "🎮 در چت خصوصی ربات می‌توانید کاملاً تک‌فره بازی کنید.\n"
        "🪑 دکمه‌ی «چیدن صندلی» برای جابه‌جایی جای بازیکنان و ربات‌هاست.\n"
        "کارت‌ها در چت خصوصی ربات برای شما ارسال می‌شود.", parse_mode=ParseMode.HTML)


async def cmd_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    web_url = os.environ.get("WEB_URL", "")
    if not web_url:
        await update.message.reply_text("آدرس مینی‌اپ هنوز تنظیم نشده است.")
        return
    await update.message.reply_text(
        f"🎴 مینی‌اپ غفون:\n{web_url}\n\nاز دکمه‌ی منو چت (بالا چپ چت) هم می‌توانید باز کنید.",
        parse_mode=ParseMode.HTML)


async def cleanup_room(context, room: Room):
    cancel_jobs(room.chat_id)
    for uid in room.players:
        UID_ROOM.pop(uid, None)
    ROOMS.pop(room.chat_id, None)
    RT.pop(room.chat_id, None)
    save_rooms()


# ---------------- کالبک‌ها ----------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    uid = q.from_user.id

    if data == "join":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        err = room.add_player(uid, q.from_user.full_name)
        if err:
            await q.answer(err, show_alert=True)
            return
        save_rooms()
        await refresh_lobby(context, room)
        return

    if data == "start":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        if uid != room.host_id:
            await q.answer("فقط میزبان می‌تواند شروع کند.", show_alert=True)
            return
        await start_match(context, room.chat_id)
        return

    if data == "startai":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        if uid != room.host_id:
            await q.answer("فقط میزبان می‌تواند شروع کند.", show_alert=True)
            return
        if room.state != "lobby":
            await q.answer("بازی از قبل در جریان است.", show_alert=True)
            return
        for i in range(4 - len(room.players)):
            room.add_bot(f"ربات {G.fa(i + 1)}")
        save_rooms()
        await start_match(context, room.chat_id)
        return

    if data == "end":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        if uid != room.host_id:
            await q.answer("فقط میزبان می‌تواند پایان دهد.", show_alert=True)
            return
        await cleanup_room(context, room)
        await q.edit_message_text("❌ بازی پاک شد.")
        return

    if data == "seatmenu":
        room = ROOMS.get(q.message.chat_id)
        if not room or room.state != "lobby":
            await q.answer("فقط قبل از شروع بازی.", show_alert=True)
            return
        if uid != room.host_id:
            await q.answer("فقط میزبان می‌تواند صندلی جابه‌جا کند.", show_alert=True)
            return
        await show_seats(context, room)
        return

    if data == "seatback":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        rt(room.chat_id)["swap_seat"] = None
        await refresh_lobby(context, room)
        return

    if data.startswith("seat:"):
        room = ROOMS.get(q.message.chat_id)
        if not room or room.state != "lobby":
            await q.answer("فقط قبل از شروع بازی.", show_alert=True)
            return
        if uid != room.host_id:
            await q.answer("فقط میزبان می‌تواند صندلی جابه‌جا کند.", show_alert=True)
            return
        s = int(data.split(":")[1])
        pend = rt(room.chat_id).get("swap_seat")
        if pend is None:
            rt(room.chat_id)["swap_seat"] = s
            await q.answer(f"صندلی {G.fa(s + 1)} انتخاب شد؛ حالا صندلی دیگر را بزن.")
            await show_seats(context, room)
            return
        if pend == s:
            rt(room.chat_id)["swap_seat"] = None
            await q.answer("انصراف از جابه‌جایی.")
            await show_seats(context, room)
            return
        try:
            room.swap_seats(pend, s)
        except GameError as e:
            await q.answer(str(e), show_alert=True)
            return
        rt(room.chat_id)["swap_seat"] = None
        save_rooms()
        await q.answer("✅ جابه‌جایی انجام شد.")
        await show_seats(context, room)
        return

    if data == "again":
        room = ROOMS.get(q.message.chat_id)
        if not room:
            return
        room.scores = [0, 0]
        room.round_log = []
        room.round_no = 0
        await q.edit_message_text("🔄 بازی جدید آماده است!")
        await start_match(context, room.chat_id)
        return

    if data.startswith("tgt:"):
        room = ROOMS.get(q.message.chat_id)
        if not room or uid != room.host_id:
            return
        room.target = int(data.split(":")[1])
        save_rooms()
        await refresh_lobby(context, room)
        return

    if data.startswith("bid:"):
        room = find_room_for_user(uid)
        if not room or room.state != "bid":
            return
        seat = room.seat_of(uid)
        if seat != room.current_bidder():
            await q.answer("نوبت شما نیست.", show_alert=True)
            return
        await do_bid(context, room.chat_id, seat, int(data.split(":")[1]))
        return

    if data.startswith("trump:"):
        room = find_room_for_user(uid)
        if not room or room.state != "trump":
            return
        seat = room.seat_of(uid)
        suit = int(data.split(":")[1])
        try:
            room.set_trump(seat, suit)
        except GameError as e:
            await q.answer(str(e), show_alert=True)
            return
        await q.edit_message_text(f"✅ حکم «{SUITS[suit]}» ثبت شد.",
                                  reply_markup=InlineKeyboardMarkup([]))
        await context.bot.send_message(chat_id=room.chat_id,
                                       text=f"👑 حاکم: {esc(seat_name(room, seat))} | "
                                            f"اعلام: {G.fa(room.bid_value)} دست | "
                                            f"حکم: {SUIT_SYMBOLS[suit]} {SUITS[suit]}")
        await begin_turn(context, room.chat_id)
        return

    if data.startswith("play:"):
        room = find_room_for_user(uid)
        if not room or room.state != "play":
            return
        seat = room.seat_of(uid)
        card = int(data.split(":")[1])
        cancel_jobs(room.chat_id)
        try:
            res = room.play_card(seat, card)
        except GameError as e:
            await q.answer(str(e), show_alert=True)
            await begin_turn(context, room.chat_id)
            return
        await update_table(context, room.chat_id)
        if res and res[0] == "trick":
            await context.bot.send_message(chat_id=room.chat_id,
                                           text=f"🎯 دست را {esc(seat_name(room, res[1]))} برد!")
        await begin_turn(context, room.chat_id)
        return


# ---------------- اجرا ----------------
async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("startgame", "ساخت بازی (گروهی یا تک‌فره)"),
        ("join", "عضو شدن در بازی"),
        ("play", "شروع سریع (میزبان)"),
        ("cancel", "پایان بازی (میزبان)"),
        ("help", "راهنمای بازی"),
        ("webapp", "بازکردن مینی‌اپ تلگرام"),
    ])
    # دکمه‌ی منو چت برای بازکردن مینی‌اپ
    web_url = os.environ.get("WEB_URL", "")
    if web_url:
        try:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButton("بازی غفون", WebAppInfo(url=web_url))
            )
        except Exception as e:
            log.debug("set_chat_menu_button: %s", e)
    # سرور وب برای مینی‌اپ
    await start_web_server()


async def log_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.message
    if m and m.text:
        log.info("MSG کاربر %s در چت %s: %s", update.effective_user.id if update.effective_user else "؟",
                 update.effective_chat.id if update.effective_chat else "؟", m.text[:80])


async def log_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q:
        log.info("CB کاربر %s: %s", q.from_user.id, q.data)


def main():
    token = get_token()
    if not token:
        print("=" * 60)
        print("توکن ربات پیدا نشد!")
        print("توکن را از @BotFather بگیرید و یکی از این دو کار را بکنید:")
        print("  ۱) export BOT_TOKEN=توکن  و سپس python bot.py")
        print("  ۲) توکن را در config.json بگذارید")
        print("=" * 60)
        return
    load_rooms()
    app = Application.builder().token(token).build()
    app.post_init = post_init
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("startgame", cmd_startgame))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("webapp", cmd_webapp))
    app.add_handler(CallbackQueryHandler(on_callback))
    # لاگ ورودی‌ها برای دیباگ (گروه منفی = قبل از هاندلرهای اصلی)
    app.add_handler(MessageHandler(filters.ALL, log_msg), group=-1)
    app.add_handler(CallbackQueryHandler(log_cb), group=-1)
    app.post_shutdown = stop_web_server
    log.info("غفون بات شروع به کار کرد …")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
