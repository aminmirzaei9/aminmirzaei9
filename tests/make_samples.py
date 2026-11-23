"""ساخت تصاویر نمونه برای پیش‌نمایش گرافیک بازی."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import graphics as G
from engine import Room, cid

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(OUT, exist_ok=True)


def build_room():
    r = Room(-1, 1, target=100)
    for i, n in enumerate(["علی", "رضا", "مریم", "سارا"], start=1):
        r.add_player(i, n)
    r.start()
    r.new_round()
    # اعلام دست نیمه‌کاره برای نمایش
    r.place_bid(r.current_bidder(), 5)
    r.place_bid(r.current_bidder(), 7)
    r.place_bid(r.current_bidder(), 0)
    # حاکم را مشخص کن و حکم بگذار
    r.state = "trump"
    r.ruler = r.highest_bidder
    r.bid_value = r.bid_max
    r.set_trump(r.ruler, 1)  # دل
    # چند کارت بازی شود
    for _ in range(3):
        seat = r.turn
        card = r.legal_cards(seat)[0]
        r.play_card(seat, card)
    return r


room = build_room()
names = {s: room.players[room.seats[s]] for s in range(4)}

G.make_lobby_banner().save(os.path.join(OUT, "sample_lobby.png"))
G.make_table_image(room, names).save(os.path.join(OUT, "sample_table.png"))
G.make_hand_image(room.hands[0], room.legal_cards(0), True, "🟢 نوبت شماست! کارت بازی کنید").save(
    os.path.join(OUT, "sample_hand.png"))
G.make_card(cid(0, 14), 300, 420).save(os.path.join(OUT, "sample_card.png"))
# نتیجه‌ی نمونه
room2 = Room(-1, 1, target=100)
room2.round_no = 3
room2.scores = [25, 18]
G.make_result_image(room2, names, (0, 8, 7, True)).save(os.path.join(OUT, "sample_result.png"))
G.make_winner(0, [100, 62]).save(os.path.join(OUT, "sample_winner.png"))
print("نمونه‌ها ذخیره شدند در:", OUT)
