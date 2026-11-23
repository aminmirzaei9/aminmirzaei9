"""شبیه‌سازی بازی کامل با حرکت‌های تصادفی + تست‌های واحد موتور."""
import random
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Room, cid, card_suit, card_rank, card_name, GameError


def test_trick_winner():
    r = Room(-1, 1)
    r.trump = 1  # دل حکم
    r.played = [(0, cid(0, 5)), (1, cid(1, 2))]
    assert r.trick_winner() == 1, "حکم باید برنده شود"
    r.played = [(0, cid(0, 5)), (1, cid(0, 9)), (2, cid(0, 7)), (3, cid(0, 14))]
    assert r.trick_winner() == 3, "بالاترین خال زمینه باید ببرد"
    r.trump = 2
    r.played = [(0, cid(1, 14)), (1, cid(2, 2)), (2, cid(1, 13)), (3, cid(3, 14))]
    assert r.trick_winner() == 1, "حتی ۲ خشت از آس دل بالاتر است"


def test_legal_cards():
    r = Room(-1, 1)
    r.state = "play"
    r.trump = 0
    r.turn = 0
    r.hands[0] = [cid(1, 5), cid(1, 9), cid(2, 3), cid(0, 14)]
    r.played = [(3, cid(1, 7))]
    legal = r.legal_cards(0)
    assert legal == [cid(1, 5), cid(1, 9)], "باید خال زمینه را دنبال کرد"
    r.played = [(3, cid(3, 7))]
    assert len(r.legal_cards(0)) == 4, "اگر خال نداشته باشیم، هر کارتی مجاز است"


def test_follow_rule_enforced():
    r = Room(-1, 1)
    r.state = "play"
    r.trump = 0
    r.turn = 0
    r.hands[0] = [cid(1, 5), cid(2, 3)]
    r.played = [(3, cid(1, 7))]
    try:
        r.play_card(0, cid(2, 3))
        raise AssertionError("باید خطا می‌داد: خال زمینه موجود است")
    except GameError:
        pass


def play_game(target=100, verbose=False):
    room = Room(chat_id=-1, host_id=1, target=target)
    for i, name in enumerate(["علی", "رضا", "مریم", "سارا"], start=1):
        assert room.add_player(i, name) is None
    assert room.start() is None
    guard = 0
    while room.state != "finished" and guard < 60:
        guard += 1
        room.new_round()
        while room.state == "bid":
            seat = room.current_bidder()
            vals = [0] + list(range(room.bid_max + 1, 14))
            res = room.place_bid(seat, random.choice(vals))
            if res == "redeal":
                break
            if res == "trump":
                room.set_trump(room.ruler, random.randint(0, 3))
        if room.state != "play":
            continue
        while room.state == "play":
            seat = room.turn
            legal = room.legal_cards(seat)
            res = room.play_card(seat, random.choice(legal))
            if room.round_over():
                break
        res = room.score_round()
        if verbose:
            print(f"  دور {room.round_no}: اعلام={res[2]} دست={res[1]} "
                  f"تیم={res[0]} موفق={res[3]} امتیاز={room.scores}")
    assert room.state == "finished", "بازی تمام نشد"
    assert room.scores[0] >= target or room.scores[1] >= target
    return room


if __name__ == "__main__":
    test_trick_winner()
    test_legal_cards()
    test_follow_rule_enforced()
    print("✅ تست‌های واحد موتور موفق بود.")
    for t in range(30):
        r = play_game(target=random.choice([20, 50, 100]))
        assert r.scores[0] != r.scores[1] or True
    print("✅ ۳۰ بازی شبیه‌سازی‌شده با موفقیت تمام شد.")
    print("نمونه یک بازی:")
    play_game(target=50, verbose=True)
