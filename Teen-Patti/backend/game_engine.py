from dataclasses import dataclass
from collections import Counter
import secrets
from typing import Iterable

SUITS = ('S', 'H', 'D', 'C')
RANKS = ('2','3','4','5','6','7','8','9','T','J','Q','K','A')
RANK_VALUE = {r:i+2 for i,r in enumerate(RANKS)}
CATEGORY = {'HIGH_CARD':1,'PAIR':2,'COLOR':3,'SEQUENCE':4,'PURE_SEQUENCE':5,'TRAIL':6}

@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    def code(self): return f'{self.rank}{self.suit}'

def new_deck(): return [Card(r,s) for s in SUITS for r in RANKS]

def secure_shuffle(deck):
    deck = list(deck)
    for i in range(len(deck)-1, 0, -1):
        j = secrets.randbelow(i+1)
        deck[i], deck[j] = deck[j], deck[i]
    return deck

def _straight_high(values):
    u = sorted(set(values))
    if len(u) != 3: return None
    if u == [2,3,14]: return 3
    if u[2] - u[0] == 2: return u[2]
    return None

def evaluate_hand(cards: Iterable[Card]):
    cards = list(cards)
    if len(cards) != 3 or len({c.code() for c in cards}) != 3:
        raise ValueError('A hand must contain three distinct cards')
    values = sorted((RANK_VALUE[c.rank] for c in cards), reverse=True)
    counts = Counter(values)
    flush = len({c.suit for c in cards}) == 1
    straight_high = _straight_high(values)
    if len(counts) == 1:
        return (CATEGORY['TRAIL'], values[0], 0, 0)
    if straight_high and flush:
        return (CATEGORY['PURE_SEQUENCE'], straight_high, 0, 0)
    if straight_high:
        return (CATEGORY['SEQUENCE'], straight_high, 0, 0)
    if flush:
        return (CATEGORY['COLOR'], *values)
    if 2 in counts.values():
        pair = max(v for v,c in counts.items() if c == 2)
        kicker = max(v for v,c in counts.items() if c == 1)
        return (CATEGORY['PAIR'], pair, kicker, 0)
    return (CATEGORY['HIGH_CARD'], *values)

def compare_hands(hand_a, hand_b):
    ea, eb = evaluate_hand(hand_a), evaluate_hand(hand_b)
    return 1 if ea > eb else -1 if ea < eb else 0
