from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

def now_utc(): return datetime.now(timezone.utc)

class Table(Base):
    __tablename__ = 'tables'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    join_code: Mapped[str] = mapped_column(String(4), unique=True, index=True)
    host_player_id: Mapped[str] = mapped_column(String(36))
    boot: Mapped[int] = mapped_column(Integer)
    starting_chips: Mapped[int] = mapped_column(Integer, default=1000)
    max_players: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default='LOBBY')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class Player(Base):
    __tablename__ = 'players'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey('tables.id'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    balance: Mapped[int] = mapped_column(Integer)
    starting_balance: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=True)
    seen_cards: Mapped[bool] = mapped_column(Boolean, default=False)
    blind_plays: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    session_token_hash: Mapped[str] = mapped_column(String(64), index=True)
    __table_args__ = (Index('ix_player_table_name', 'table_id', 'name', unique=True),)

class Match(Base):
    __tablename__ = 'matches'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    table_id: Mapped[str] = mapped_column(ForeignKey('tables.id'), index=True)
    boot: Mapped[int] = mapped_column(Integer)
    pot: Mapped[int] = mapped_column(Integer, default=0)
    winner_player_id: Mapped[str | None] = mapped_column(ForeignKey('players.id'), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='PLAYING')

class GameState(Base):
    __tablename__ = 'game_state'
    table_id: Mapped[str] = mapped_column(ForeignKey('tables.id'), primary_key=True)
    match_id: Mapped[str | None] = mapped_column(ForeignKey('matches.id'), nullable=True)
    current_player_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_bid: Mapped[int] = mapped_column(Integer, default=0)
    pot: Mapped[int] = mapped_column(Integer, default=0)
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    turn_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text, default='{}')

class PlayerCard(Base):
    __tablename__ = 'player_cards'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id'), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), index=True)
    rank: Mapped[str] = mapped_column(String(2))
    suit: Mapped[str] = mapped_column(String(1))
    __table_args__ = (Index('ix_cards_match_player', 'match_id', 'player_id'),)

class Action(Base):
    __tablename__ = 'actions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id'), index=True)
    player_id: Mapped[str | None] = mapped_column(ForeignKey('players.id'), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(40))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    details: Mapped[str] = mapped_column(Text, default='{}')

class Contribution(Base):
    __tablename__ = 'match_contributions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id'), index=True)
    player_id: Mapped[str] = mapped_column(ForeignKey('players.id'), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))

class SideShowRequest(Base):
    __tablename__ = 'side_show_requests'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    match_id: Mapped[str] = mapped_column(ForeignKey('matches.id'), index=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey('players.id'))
    opponent_id: Mapped[str] = mapped_column(ForeignKey('players.id'))
    status: Mapped[str] = mapped_column(String(20), default='PENDING')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
