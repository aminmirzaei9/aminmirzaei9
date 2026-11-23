"""موتور بازی «غفون» (حکم با اعلام دست) — بدون وابستگی به تلگرام.

قوانین پیاده‌سازی‌شده:
- ۴ بازیکن، ۲ تیم دونفره (صندلی‌های 0 و 2 در برابر 1 و 3)
- ۵۲ کارت، هر نفر ۱۳ کارت
- اعلام دست (بیدینگ): هر نفر یک‌نوبت بید می‌زند (بالاتر از بیشترین بید) یا پاس؛
  بالاترین بیدکننده «حاکم» می‌شود و خال حکم را انتخاب می‌کند.
- بازی: برنده‌ی هر دست، دست بعد را شروع می‌کند؛ باید خال زمینه را دنبال کرد؛
  کارت حکم بر همه می‌برد.
- امتیاز: اگر تیم حاکم به بید X برسد (Y≥X) → امتیاز Y؛ اگر نفُکند (Y<X) → تیم حریف ۲×X.
- بازی تا رسیدن به امتیاز هدف (پیش‌فرض ۱۰۰).
"""
from __future__ import annotations

import random

SUITS = ["پیک", "دل", "خشت", "گشنیز"]
SUIT_SYMBOLS = ["♠", "♥", "♦", "♣"]
SUIT_COLORS = ["#1f2937", "#dc2626", "#dc2626", "#1f2937"]  # پیک/گشنیز سیاه، دل/خشت قرمز
RANK_LABEL = {14: "A", 13: "K", 12: "Q", 11: "J", 10: "10", 9: "9", 8: "8",
              7: "7", 6: "6", 5: "5", 4: "4", 3: "3", 2: "2"}
RANK_NAMES = {14: "آس", 13: "شاه", 12: "بی‌بی", 11: "سرباز"}

TEAM_NAMES = ["تیم آبی", "تیم قرمز"]
TEAM_COLORS = ["#3B82F6", "#EF4444"]
TEAM_EMOJI = ["🔵", "🔴"]


def cid(suit: int, rank: int) -> int:
    return suit * 13 + (rank - 2)


def card_suit(c: int) -> int:
    return c // 13


def card_rank(c: int) -> int:
    return c % 13 + 2


def card_name(c: int) -> str:
    r = card_rank(c)
    return f"{RANK_NAMES.get(r, RANK_LABEL[r])} {SUITS[card_suit(c)]}"


def card_label(c: int) -> str:
    return RANK_LABEL[card_rank(c)]


class GameError(Exception):
    pass


import secrets


class Room:
    def __init__(self, chat_id: int, host_id: int, target: int = 100, single: bool = False, room_id: str | None = None):
        self.chat_id = chat_id
        self.host_id = host_id
        self.room_id = room_id or secrets.token_urlsafe(6)  # کد کوتاه اتاق برای لینک دعوت
        self.target = target
        self.single = single  # حالت تک‌فره: بازی در چت خصوصی، ۳ ربات
        self.players: dict[int, str] = {}          # uid -> name
        self.seats: list[int | None] = [None] * 4  # seat -> uid
        self.state = "lobby"  # lobby | bid | trump | play | round_end | finished
        self.scores = [0, 0]
        self.round_no = 0
        self.hands: list[list[int]] = [[] for _ in range(4)]
        self.bids: dict[int, int] = {}
        self.bid_order: list[int] = []
        self.bid_idx = 0
        self.bid_max = 0
        self.highest_bidder: int | None = None
        self.ruler: int | None = None
        self.trump: int | None = None
        self.bid_value = 0
        self.lead: int | None = None
        self.played: list[tuple[int, int]] = []     # (seat, card)
        self.turn: int | None = None
        self.tricks = [0, 0]                        # team -> tricks this round
        self.round_log: list[tuple] = []            # (team, tricks, bid, success)

    # ---------------- lobby ----------------
    def add_player(self, uid: int, name: str) -> str | None:
        if self.state != "lobby":
            return "بازی در جریان است؛ منتظر پایان آن بمانید."
        if uid in self.players:
            return None
        if len(self.players) >= 4:
            return "ظرفیت بازی کامل است (۴ نفر)."
        self.players[uid] = name
        self._seat(uid)
        return None

    def remove_player(self, uid: int):
        self.players.pop(uid, None)
        for i in range(4):
            if self.seats[i] == uid:
                self.seats[i] = None

    def _seat(self, uid: int):
        """گذاشتن بازیکن در اولین صندلی خالی."""
        if uid in self.seats:
            return
        for i in range(4):
            if self.seats[i] is None:
                self.seats[i] = uid
                return

    def add_bot(self, name: str) -> int:
        """افزودن ربات با شناسه‌ی منفی؛ شناسه‌ها با جابه‌جایی صندلی هم سازگارند."""
        uid = -1
        while uid in self.players:
            uid -= 1
        self.players[uid] = name
        self._seat(uid)
        return uid

    def swap_seats(self, a: int, b: int):
        """جابه‌جایی دو صندلی (برای چیدن ربات‌ها و بازیکنان)."""
        if not (0 <= a < 4 and 0 <= b < 4):
            raise GameError("صندلی نامعتبر است.")
        self.seats[a], self.seats[b] = self.seats[b], self.seats[a]

    def start(self) -> str | None:
        if len(self.players) != 4:
            return "برای شروع باید دقیقاً ۴ بازیکن باشد."
        # چینش میزبان رعایت می‌شود؛ فقط صندلی‌های خالی پر می‌شود
        free = [i for i in range(4) if self.seats[i] is None]
        missing = [u for u in self.players if u not in self.seats]
        if len(free) != len(missing):
            self.seats = list(self.players)[:4]
        else:
            for i, u in zip(free, missing):
                self.seats[i] = u
        self.scores = [0, 0]
        self.round_no = 0
        self.round_log = []
        self.state = "lobby"
        return None

    def team_of(self, seat: int) -> int:
        return seat % 2  # 0,2 -> تیم 0 | 1,3 -> تیم 1

    def seat_of(self, uid: int) -> int | None:
        try:
            return self.seats.index(uid)
        except (ValueError, TypeError):
            return None

    # ---------------- round ----------------
    def new_round(self):
        deck = [cid(s, r) for s in range(4) for r in range(2, 15)]
        random.shuffle(deck)
        self.hands = [sorted(deck[i * 13:(i + 1) * 13],
                             key=lambda c: (card_suit(c), -card_rank(c)))
                     for i in range(4)]
        self.trump = None
        self.ruler = None
        self.bid_value = 0
        self.bids = {}
        self.played = []
        self.tricks = [0, 0]
        self.round_no += 1
        self.state = "bid"
        start = (self.round_no - 1) % 4
        self.bid_order = [(start + i) % 4 for i in range(4)]
        self.bid_idx = 0
        self.bid_max = 0
        self.highest_bidder = None
        return self.hands

    def current_bidder(self) -> int | None:
        if self.state != "bid":
            return None
        return self.bid_order[self.bid_idx]

    def place_bid(self, seat: int, value: int) -> str | None:
        """value=0 یعنی پاس. خروجی: None | 'trump' | 'redeal'."""
        if self.state != "bid" or seat != self.current_bidder():
            raise GameError("نوبت اعلام شما نیست.")
        if value != 0 and (value <= self.bid_max or value > 13):
            raise GameError("بید باید بالاتر از بیشترین بید باشد.")
        self.bids[seat] = value
        if value > self.bid_max:
            self.bid_max = value
            self.highest_bidder = seat
        self.bid_idx += 1
        if self.bid_idx >= 4:
            if self.highest_bidder is None:
                return "redeal"
            self.ruler = self.highest_bidder
            self.bid_value = self.bid_max
            self.state = "trump"
            return "trump"
        return None

    def set_trump(self, seat: int, suit: int):
        if self.state != "trump" or seat != self.ruler:
            raise GameError("نوبت انتخاب حکم با شما نیست.")
        self.trump = suit
        self.state = "play"
        self.lead = self.ruler
        self.turn = self.ruler
        self.played = []

    def legal_cards(self, seat: int) -> list[int]:
        hand = self.hands[seat]
        if not self.played:
            return list(hand)
        lead_suit = card_suit(self.played[0][1])
        follow = [c for c in hand if card_suit(c) == lead_suit]
        return follow if follow else list(hand)

    def play_card(self, seat: int, card: int):
        """خروجی: None | ('trick', winner_seat)"""
        if self.state != "play" or seat != self.turn:
            raise GameError("نوبت شما نیست.")
        if card not in self.hands[seat]:
            raise GameError("این کارت در دست شما نیست.")
        if card not in self.legal_cards(seat):
            raise GameError("باید خال زمینه را دنبال کنید.")
        self.hands[seat].remove(card)
        self.played.append((seat, card))
        if len(self.played) == 4:
            winner = self.trick_winner()
            self.tricks[self.team_of(winner)] += 1
            self.played = []
            self.lead = winner
            self.turn = winner
            return ("trick", winner)
        self.turn = (seat + 1) % 4
        return None

    def trick_winner(self) -> int:
        lead_suit = card_suit(self.played[0][1])
        best_seat, best_card = self.played[0]
        for seat, card in self.played[1:]:
            if self._beats(card, best_card, lead_suit):
                best_seat, best_card = seat, card
        return best_seat

    def _beats(self, card: int, best: int, lead_suit: int) -> bool:
        cs, bs = card_suit(card), card_suit(best)
        if cs == self.trump and bs != self.trump:
            return True
        if cs == self.trump and bs == self.trump:
            return card_rank(card) > card_rank(best)
        if cs == lead_suit and bs == lead_suit:
            return card_rank(card) > card_rank(best)
        return False

    def round_over(self) -> bool:
        return all(len(h) == 0 for h in self.hands)

    def score_round(self) -> tuple:
        team = self.team_of(self.ruler)
        y = self.tricks[team]
        x = self.bid_value
        if y >= x:
            self.scores[team] += y
            res = (team, y, x, True)
        else:
            other = 1 - team
            self.scores[other] += 2 * x
            res = (other, y, x, False)
        self.round_log.append(res)
        self.state = "round_end"
        if self.scores[0] >= self.target or self.scores[1] >= self.target:
            self.state = "finished"
        return res

    # ---------------- persistence ----------------
    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id, "host_id": self.host_id, "target": self.target,
            "single": self.single,
            "players": self.players, "seats": self.seats,
            "scores": self.scores, "round_no": self.round_no,
            "round_log": self.round_log,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Room":
        r = cls(d["chat_id"], d["host_id"], d.get("target", 100), d.get("single", False))
        r.players = {int(k): v for k, v in d.get("players", {}).items()}
        r.seats = d.get("seats", [None] * 4)
        r.scores = d.get("scores", [0, 0])
        r.round_no = d.get("round_no", 0)
        r.round_log = d.get("round_log", [])
        r.state = "lobby"  # پس از ری‌استارت، از لابی ادامه می‌دهیم
        return r
