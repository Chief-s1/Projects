import asyncio, json, uuid, secrets
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from database.database import SessionLocal
from database.models import Table, Player, Match, GameState, PlayerCard, Action, Contribution, SideShowRequest
from backend.game_engine import Card, secure_shuffle, new_deck, compare_hands
from backend.events import event
from backend.state_manager import state_manager
from config import settings

UTC=timezone.utc

def now(): return datetime.now(UTC)

def as_utc(dt):
    if not dt: return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
def iso(dt):
    d=as_utc(dt)
    return d.isoformat().replace('+00:00','Z') if d else None

def _cards_for(session, match_id, player_id):
    rows=session.execute(select(PlayerCard).where(PlayerCard.match_id==match_id, PlayerCard.player_id==player_id)).scalars().all()
    return [Card(r.rank,r.suit) for r in rows]

def _players(session, table_id): return session.execute(select(Player).where(Player.table_id==table_id).order_by(Player.id)).scalars().all()

def _public_state(session, table_id):
    table=session.get(Table,table_id); gs=session.get(GameState,table_id)
    players=[]
    for p in _players(session,table_id):
        players.append({'id':p.id,'name':p.name,'balance':p.balance,'active':p.active,'connected':p.connected,'seen_cards':p.seen_cards,'blind_plays':p.blind_plays})
    payload={}
    if gs and gs.payload:
        try: payload=json.loads(gs.payload)
        except (TypeError, ValueError): payload={}
    return {'table_id':table_id,'table_code':table.join_code,'host_player_id':table.host_player_id,'status':table.status,'boot':table.boot,'starting_chips':table.starting_chips,'pot':gs.pot if gs else 0,
            'current_bid':gs.current_bid if gs else 0,'current_player_id':gs.current_player_id if gs else None,
            'turn_started_at':iso(gs.turn_started_at) if gs else None,'turn_deadline':iso(gs.turn_deadline) if gs else None,
            'state_version':gs.state_version if gs else 0,'match_id':gs.match_id if gs else None,'players':players,
            'show_reveal':payload.get('show_reveal'), 'show_winner_id':payload.get('show_winner_id'),
            'show_winner_name':payload.get('show_winner_name'), 'show_loser_id':payload.get('show_loser_id'),
            'show_loser_name':payload.get('show_loser_name'), 'show_tie':payload.get('show_tie',False),
            'last_award':payload.get('last_award'), 'replay_yes':payload.get('replay_yes',[]), 'replay_no':payload.get('replay_no',[]),
            'scores_saved':payload.get('scores_saved',False), 'score_file_name':payload.get('score_file_name'), 'replay_ended':payload.get('replay_ended',False),
            'replay_started_at':payload.get('replay_started_at'), 'replay_deadline':payload.get('replay_deadline')}

def _private_state(session, table_id, player_id):
    s=_public_state(session,table_id)
    p=session.get(Player,player_id)
    if p and p.seen_cards and s['match_id']:
        s['my_cards']=[c.code() for c in _cards_for(session,s['match_id'],player_id)]
    else: s['my_cards']=[]
    return s

async def push_state(table_id, event_name='STATE_SYNC', actor_id=None, extra=None, private_player_ids=None):
    with SessionLocal() as session:
        gs=session.get(GameState,table_id); version=gs.state_version if gs else 0
        public=_public_state(session,table_id)
    msg=event(event_name,version,server_timestamp=now().timestamp(),state=public,actor_id=actor_id,**(extra or {}))
    await state_manager.broadcast(table_id,msg)
    targets = list(state_manager.runtime(table_id).connections.keys())
    for pid in targets:
        with SessionLocal() as session:
            priv=_private_state(session,table_id,pid)
        await state_manager.send(table_id,pid,event('STATE_SYNC',priv['state_version'],server_timestamp=now().timestamp(),state=priv))

class MatchService:
    def __init__(self): pass

    def create_table(self, host_name, starting_chips, boot):
        if starting_chips <= 0 or boot <= 0 or boot > starting_chips: raise ValueError('Starting chips must be positive and at least the boot amount.')
        for _ in range(100):
            code=f'{__import__("secrets").randbelow(10000):04d}'
            with SessionLocal() as s:
                if s.execute(select(Table).where(Table.join_code==code, Table.status!='FINISHED')).scalar_one_or_none(): continue
                tid=str(uuid.uuid4()); pid=str(uuid.uuid4())
                from backend.auth import issue_token, hash_token
                token=issue_token()
                t=Table(id=tid,join_code=code,host_player_id=pid,boot=boot,starting_chips=starting_chips,max_players=settings.max_players,status='LOBBY')
                p=Player(id=pid,table_id=tid,name=host_name.strip(),balance=starting_chips,starting_balance=starting_chips,session_token_hash=hash_token(token))
                s.add(t); s.flush(); s.add(p); s.flush(); s.add(GameState(table_id=tid)); s.commit()
                return {'table_id':tid,'player_id':pid,'token':token,'join_code':code}
        raise RuntimeError('Unable to allocate a unique table code.')

    def join_table(self, join_code, player_name):
        name=player_name.strip()
        if not name or len(name)>80: raise ValueError('Invalid player name.')
        with SessionLocal() as s:
            t=s.execute(select(Table).where(Table.join_code==join_code)).scalar_one_or_none()
            if not t: raise ValueError('Table not found.')
            if t.status!='LOBBY': raise ValueError('Table is no longer accepting players.')
            players=_players(s,t.id)
            if len(players)>=t.max_players: raise ValueError('Table is full.')
            if any(p.name.casefold()==name.casefold() for p in players): raise ValueError('Duplicate player name.')
            starting_chips=t.starting_chips
            pid=str(uuid.uuid4()); from backend.auth import issue_token,hash_token
            token=issue_token()
            s.add(Player(id=pid,table_id=t.id,name=name,balance=starting_chips,starting_balance=starting_chips,session_token_hash=hash_token(token)))
            s.commit()
            return {'table_id':t.id,'player_id':pid,'token':token,'join_code':t.join_code}

    async def start_match(self, table_id, player_id):
        rt=state_manager.runtime(table_id)
        async with rt.lock:
            with SessionLocal() as s:
                t=s.get(Table,table_id); host=s.get(Player,player_id)
                if not t or not host or t.host_player_id!=player_id: raise ValueError('Only the host can start the match.')
                if t.status!='LOBBY': raise ValueError('Table is not in lobby.')
                ps=[p for p in _players(s,table_id) if p.active]
                if len(ps)<2: raise ValueError('At least 2 players are required.')
                if any(p.balance<t.boot for p in ps): raise ValueError('Every player must have enough chips for boot.')
                deck=secure_shuffle(new_deck()); mid=str(uuid.uuid4()); ts=now(); deadline=ts+timedelta(seconds=settings.turn_seconds)
                m=Match(id=mid,table_id=table_id,boot=t.boot,pot=t.boot*len(ps),status='PLAYING',started_at=ts)
                s.add(m); s.flush()
                for p in ps:
                    p.balance-=t.boot; p.seen_cards=False; p.blind_plays=0; p.active=True
                    s.add(Contribution(match_id=mid,player_id=p.id,amount=t.boot,kind='BOOT'))
                for p in ps:
                    for _ in range(3):
                        c=deck.pop(); s.add(PlayerCard(match_id=mid,player_id=p.id,rank=c.rank,suit=c.suit))
                gs=s.get(GameState,table_id); gs.payload='{}'; gs.match_id=mid; gs.current_bid=t.boot; gs.pot=t.boot*len(ps); gs.current_player_id=ps[0].id; gs.turn_started_at=ts; gs.turn_deadline=deadline; gs.state_version+=1
                t.status='PLAYING'; s.commit()
        await push_state(table_id,'MATCH_STARTED',actor_id=player_id)
        await self._schedule_timeout(table_id, mid, ps[0].id, deadline)

    async def _schedule_timeout(self, table_id, match_id, player_id, deadline):
        rt=state_manager.runtime(table_id)
        if rt.timeout_task and not rt.timeout_task.done(): rt.timeout_task.cancel()
        async def waiter():
            try:
                delay=max(0,(as_utc(deadline)-now()).total_seconds())
                await asyncio.sleep(delay)
                await self.timeout_turn(table_id,match_id,player_id)
            except asyncio.CancelledError: pass
        rt.timeout_task=asyncio.create_task(waiter())

    def _advance_player(self,s,table_id,current_id):
        # Find the next active player using the full table order. The current
        # player may already have been marked inactive (manual PACK/timeout),
        # so searching only the active list would make the current player
        # disappear and raise StopIteration.
        all_players=_players(s,table_id)
        if not all_players:
            return None
        try:
            current_index=next(i for i,p in enumerate(all_players) if p.id==current_id)
        except StopIteration:
            return next((p.id for p in all_players if p.active),None)
        for offset in range(1,len(all_players)+1):
            candidate=all_players[(current_index+offset)%len(all_players)]
            if candidate.active:
                return candidate.id
        return None

    async def _start_replay(self, table_id, match_id, eligible_ids):
        rt=state_manager.runtime(table_id)
        async with rt.lock:
            with SessionLocal() as s:
                gs=s.get(GameState,table_id); t=s.get(Table,table_id)
                if not gs or gs.match_id!=match_id or t.status!='REPLAY': return
                ids=[]
                for pid in eligible_ids:
                    p=s.get(Player,pid)
                    if p and p.balance>=t.boot: ids.append(pid)
                if len(ids)<2: return
                deck=secure_shuffle(new_deck()); mid=str(uuid.uuid4()); ts=now(); deadline=ts+timedelta(seconds=settings.turn_seconds)
                m=Match(id=mid,table_id=table_id,boot=t.boot,pot=t.boot*len(ids),status='PLAYING',started_at=ts)
                s.add(m); s.flush()
                allp=_players(s,table_id)
                for p in allp:
                    p.active=p.id in ids; p.seen_cards=False; p.blind_plays=0
                for pid in ids:
                    p=s.get(Player,pid); p.balance-=t.boot; s.add(Contribution(match_id=mid,player_id=pid,amount=t.boot,kind='BOOT'))
                    for _ in range(3):
                        c=deck.pop(); s.add(PlayerCard(match_id=mid,player_id=pid,rank=c.rank,suit=c.suit))
                gs.payload='{}'; gs.match_id=mid; gs.current_bid=t.boot; gs.pot=t.boot*len(ids); gs.current_player_id=ids[0]; gs.turn_started_at=ts; gs.turn_deadline=deadline; gs.state_version+=1
                t.status='PLAYING'; s.commit()
        await push_state(table_id,'MATCH_STARTED',actor_id=ids[0])
        await self._schedule_timeout(table_id,mid,ids[0],deadline)

    async def _schedule_replay_start(self, table_id, match_id, deadline):
        rt=state_manager.runtime(table_id)
        if rt.timeout_task and not rt.timeout_task.done(): rt.timeout_task.cancel()
        async def waiter():
            try:
                delay=max(0,(as_utc(deadline)-now()).total_seconds())
                await asyncio.sleep(delay)
                with SessionLocal() as s:
                    gs=s.get(GameState,table_id)
                    if not gs or gs.match_id!=match_id: return
                    payload=json.loads(gs.payload or '{}')
                    ids=payload.get('replay_yes',[])
                    if len(ids)<2:
                        from services.excel_service import save_table_score_file
                        _, filename=save_table_score_file(table_id)
                        payload['scores_saved']=True; payload['score_file_name']=filename; payload['replay_ended']=True
                        t=s.get(Table,table_id); t.status='FINISHED'; gs.payload=json.dumps(payload); gs.state_version+=1; s.commit()
                        end_now=True
                    else:
                        end_now=False
                if end_now:
                    await push_state(table_id,'REPLAY_ENDED')
                    return
                await self._start_replay(table_id,match_id,ids)
            except asyncio.CancelledError: pass
        rt.timeout_task=asyncio.create_task(waiter())

    async def action(self, table_id, player_id, token_player_id, action_type, request_id):
        if player_id!=token_player_id: raise ValueError('Session/player mismatch.')
        rt=state_manager.runtime(table_id)
        async with rt.lock:
            with SessionLocal() as s:
                p=s.get(Player,player_id); gs=s.get(GameState,table_id)
                if not p or p.table_id!=table_id or not gs or not gs.match_id: raise ValueError('No active match.')
                action_type=action_type.upper()
                if action_type in ('REPLAY_YES','REPLAY_NO'):
                    if s.get(Table,table_id).status!='REPLAY': raise ValueError('Replay voting is not open.')
                    payload=json.loads(gs.payload or '{}'); yes=list(dict.fromkeys(payload.get('replay_yes',[]))); no=list(dict.fromkeys(payload.get('replay_no',[])))
                    all_players=_players(s,table_id)
                    all_ids=[x.id for x in all_players]
                    if action_type=='REPLAY_YES':
                        if p.balance < s.get(Table,table_id).boot: raise ValueError('Not enough chips to join the next match.')
                        if player_id not in yes: yes.append(player_id)
                        no=[x for x in no if x!=player_id]
                    else:
                        yes=[x for x in yes if x!=player_id]
                        if player_id not in no: no.append(player_id)
                    payload['replay_yes']=yes; payload['replay_no']=no
                    # If everyone explicitly declines, close the table immediately and save scores.
                    if all_ids and set(no)>=set(all_ids):
                        from services.excel_service import save_table_score_file
                        _, filename=save_table_score_file(table_id)
                        payload['scores_saved']=True; payload['score_file_name']=filename; payload['replay_ended']=True
                        s.get(Table,table_id).status='FINISHED'; gs.payload=json.dumps(payload); gs.state_version+=1; s.commit()
                        await push_state(table_id,'REPLAY_ENDED',actor_id=player_id)
                        return
                    if len(yes)>=2 and not payload.get('replay_deadline'):
                        d=now()+timedelta(seconds=10); payload['replay_started_at']=iso(now()); payload['replay_deadline']=iso(d)
                        schedule_deadline=d
                    else: schedule_deadline=None
                    gs.payload=json.dumps(payload); gs.state_version+=1; s.commit()
                    await push_state(table_id,'MATCH_RESET',actor_id=player_id)
                    if schedule_deadline: await self._schedule_replay_start(table_id,gs.match_id,schedule_deadline)
                    return
                if not p.active: raise ValueError('Player is no longer active.')
                if gs.current_player_id!=player_id: raise ValueError('Not your turn.')
                if not request_id: raise ValueError('request_id is required.')
                duplicate=s.execute(select(Action).where(Action.request_id==request_id,Action.match_id==gs.match_id)).scalar_one_or_none()
                if duplicate: return
                if gs.turn_deadline and now()>as_utc(gs.turn_deadline): raise ValueError('Turn has expired.')
                action_type=action_type.upper()
                if action_type=='SEE_CARDS':
                    if not p.seen_cards: p.seen_cards=True
                    gs.state_version+=1; s.add(Action(match_id=gs.match_id,player_id=player_id,action='SEE_CARDS',request_id=request_id)); s.commit()
                    await push_state(table_id,'CARDS_REVEALED',actor_id=player_id,private_player_ids=[player_id]); return
                if action_type=='PACK':
                    p.active=False
                    s.add(Action(match_id=gs.match_id,player_id=player_id,action='PACK',request_id=request_id))
                    next_id=self._advance_player(s,table_id,player_id)
                    gs.current_player_id=next_id
                    finished=self._finish_if_needed(s,table_id,gs)
                    if not finished and next_id:
                        ts=now()
                        gs.turn_started_at=ts
                        gs.turn_deadline=ts+timedelta(seconds=settings.turn_seconds)
                    gs.state_version+=1
                    s.commit()
                    await push_state(table_id,'MATCH_FINISHED' if finished else 'PLAYER_PACKED',actor_id=player_id)
                    if not finished and next_id and gs.match_id:
                        await self._schedule_timeout(table_id,gs.match_id,next_id,gs.turn_deadline)
                    elif finished:
                        with SessionLocal() as ss:
                            gg=ss.get(GameState,table_id); pp=json.loads(gg.payload or '{}'); rd=pp.get('replay_deadline')
                        if rd: await self._schedule_replay_start(table_id,gs.match_id,as_utc(datetime.fromisoformat(rd.replace('Z','+00:00'))))
                    return
                if action_type in ('BID','BID_DOUBLE'):
                    base=gs.current_bid
                    required=base*2 if p.seen_cards else base
                    amount=required if action_type=='BID' else required*2
                    if amount<=0 or p.balance<amount: raise ValueError('Insufficient balance for this play.')
                    if not p.seen_cards:
                        p.blind_plays += 1
                        if p.blind_plays > 3: raise ValueError('Maximum 3 blind plays reached; see your cards.')
                    p.balance-=amount; gs.pot+=amount
                    if amount>gs.current_bid: gs.current_bid=amount
                    s.add(Contribution(match_id=gs.match_id,player_id=player_id,amount=amount,kind=action_type))
                    if not p.seen_cards and p.blind_plays >= 3:
                        p.seen_cards = True
                    s.add(Action(match_id=gs.match_id,player_id=player_id,action=action_type,amount=amount,request_id=request_id))
                    next_id=self._advance_player(s,table_id,player_id); gs.current_player_id=next_id; ts=now(); gs.turn_started_at=ts; gs.turn_deadline=ts+timedelta(seconds=settings.turn_seconds); gs.state_version+=1
                    s.commit()
                    await push_state(table_id,'BID_PLACED',actor_id=player_id,extra={'amount':amount})
                    await self._schedule_timeout(table_id,gs.match_id,next_id,gs.turn_deadline); return
                if action_type=='SHOW':
                    active=[x for x in _players(s,table_id) if x.active]
                    if len(active)!=2:
                        raise ValueError('Show is available only when exactly 2 active players remain.')
                    a,b=active[0],active[1]
                    ca=_cards_for(s,gs.match_id,a.id); cb=_cards_for(s,gs.match_id,b.id)
                    cmp=compare_hands(ca,cb)
                    tie=False
                    if cmp>0:
                        winner,loser=a,b
                    elif cmp<0:
                        winner,loser=b,a
                    else:
                        # Exact Teen Patti hand ties can occur. Resolve them server-side so
                        # SHOW always has a single winner who receives the entire pot.
                        winner,loser=secrets.choice([(a,b),(b,a)])
                        tie=True
                    revealed={
                        a.id:[c.code() for c in ca],
                        b.id:[c.code() for c in cb],
                    }
                    awarded=gs.pot
                    gs.payload=json.dumps({
                        'show_reveal':revealed,
                        'show_winner_id':winner.id,
                        'show_winner_name':winner.name,
                        'show_loser_id':loser.id,
                        'show_loser_name':loser.name,
                        'show_pot':awarded,
                        'show_tie':tie,
                        'last_award':{'winner_id':winner.id,'winner_name':winner.name,'amount':awarded},
                        'replay_yes':[p.id for p in _players(s,table_id) if p.balance>=s.get(Table,table_id).boot], 'replay_no':[], 'replay_started_at':iso(now()), 'replay_deadline':iso(now()+timedelta(seconds=10)),
                    })
                    s.add(Action(match_id=gs.match_id,player_id=player_id,action='SHOW',request_id=request_id,details=json.dumps({
                        'players':[a.id,b.id], 'winner_id':winner.id, 'tie':tie
                    })))
                    loser.active=False
                    gs.current_player_id=winner.id
                    winner.balance+=gs.pot
                    m=s.get(Match,gs.match_id); m.winner_player_id=winner.id; m.ended_at=now(); m.status='FINISHED'; m.pot=gs.pot
                    t=s.get(Table,table_id); t.status='REPLAY'
                    gs.current_player_id=None; gs.turn_started_at=None; gs.turn_deadline=None; gs.state_version+=1
                    for pp in _players(s,table_id): pp.seen_cards=False; pp.blind_plays=0; pp.active=True
                    s.commit()
                    await push_state(table_id,'SHOW_RESOLVED',actor_id=player_id,extra={'winner_id':winner.id,'winner_name':winner.name,'loser_id':loser.id,'show_tie':tie,'revealed_cards':revealed})
                    with SessionLocal() as ss:
                        gg=ss.get(GameState,table_id); pp=json.loads(gg.payload or '{}'); rd=pp.get('replay_deadline'); ids=pp.get('replay_yes',[])
                    if rd: await self._schedule_replay_start(table_id,gs.match_id,as_utc(datetime.fromisoformat(rd.replace('Z','+00:00'))))
                    return
                if action_type=='SIDE_SHOW':
                    if not p.seen_cards: raise ValueError('You must see your cards before requesting a side show.')
                    active=[x for x in _players(s,table_id) if x.active]
                    prev=self._previous_active(active,player_id)
                    if not prev or not prev.seen_cards: raise ValueError('Previous active player must have seen cards.')
                    existing=s.execute(select(SideShowRequest).where(SideShowRequest.match_id==gs.match_id,SideShowRequest.status=='PENDING')).scalar_one_or_none()
                    if existing: raise ValueError('A side show request is already pending.')
                    # Side Show has a chip cost. The REQUESTER pays it; the responding
                    # player never pays for merely accepting/declining the request.
                    side_show_cost=gs.current_bid
                    if side_show_cost<=0 or p.balance<side_show_cost:
                        raise ValueError('Insufficient balance for Side Show.')
                    p.balance-=side_show_cost
                    gs.pot+=side_show_cost
                    s.add(Contribution(match_id=gs.match_id,player_id=player_id,amount=side_show_cost,kind='SIDE_SHOW'))
                    req=SideShowRequest(id=str(uuid.uuid4()),match_id=gs.match_id,requester_id=player_id,opponent_id=prev.id,status='PENDING')
                    s.add(req)
                    s.add(Action(match_id=gs.match_id,player_id=player_id,action='SIDE_SHOW_REQUEST',amount=side_show_cost,request_id=request_id,details=json.dumps({'cost':side_show_cost,'opponent_id':prev.id})))
                    gs.state_version+=1
                    s.commit()
                    # Only the immediately previous active player receives the actual request/modal.
                    await state_manager.send(table_id,prev.id,event('SIDE_SHOW_REQUEST',gs.state_version,request_id=req.id,from_player_id=player_id,from_player_name=p.name,cost=side_show_cost))
                    # Synchronize balances/pot to everyone without broadcasting a Side Show modal.
                    await push_state(table_id,'STATE_SYNC',actor_id=player_id,extra={'side_show_cost':side_show_cost,'side_show_requester_id':player_id,'side_show_opponent_id':prev.id})
                    return
                raise ValueError('Unknown action.')

    def _previous_active(self, active, current_id):
        if len(active)<2:return None
        idx=next(i for i,p in enumerate(active) if p.id==current_id)
        return active[(idx-1)%len(active)]

    async def side_show_response(self, table_id, player_id, request_id, accept):
        rt=state_manager.runtime(table_id)
        async with rt.lock:
            with SessionLocal() as s:
                req=s.get(SideShowRequest,request_id); gs=s.get(GameState,table_id)
                if not req or req.match_id!=gs.match_id or req.opponent_id!=player_id or req.status!='PENDING': raise ValueError('Invalid side show request.')
                req.status='ACCEPTED' if accept else 'DECLINED'; gs.state_version+=1
                if not accept:
                    s.add(Action(match_id=gs.match_id,player_id=player_id,action='SIDE_SHOW_DECLINED'))
                    s.commit(); await push_state(table_id,'SIDE_SHOW_DECLINED',actor_id=player_id); return
                a=s.get(Player,req.requester_id); b=s.get(Player,req.opponent_id)
                ca=_cards_for(s,gs.match_id,a.id); cb=_cards_for(s,gs.match_id,b.id); cmp=compare_hands(ca,cb)
                loser=b if cmp>0 else a if cmp<0 else None
                if loser is None:
                    req.status='RESOLVED'; s.add(Action(match_id=gs.match_id,player_id=player_id,action='SIDE_SHOW_RESOLVED',details=json.dumps({'result':'tie'})))
                else:
                    loser.active=False; req.status='RESOLVED'; s.add(Action(match_id=gs.match_id,player_id=player_id,action='SIDE_SHOW_RESOLVED',details=json.dumps({'loser':loser.id})))
                    if gs.current_player_id==loser.id: gs.current_player_id=self._advance_player(s,table_id,loser.id)
                gs.state_version+=1; finished=self._finish_if_needed(s,table_id,gs); s.commit()
                await push_state(table_id,'SIDE_SHOW_ACCEPTED',actor_id=player_id)
                await push_state(table_id,'SIDE_SHOW_RESOLVED',actor_id=player_id)
                if gs.current_player_id and gs.match_id and s.get(Match,gs.match_id).status=='PLAYING':
                    ts=now(); gs.turn_started_at=ts; gs.turn_deadline=ts+timedelta(seconds=settings.turn_seconds); gs.state_version+=1; s.commit(); await push_state(table_id,'TURN_CHANGED'); await self._schedule_timeout(table_id,gs.match_id,gs.current_player_id,gs.turn_deadline)
                elif finished:
                    with SessionLocal() as ss:
                        gg=ss.get(GameState,table_id); pp=json.loads(gg.payload or '{}'); rd=pp.get('replay_deadline')
                    if rd: await self._schedule_replay_start(table_id,gs.match_id,as_utc(datetime.fromisoformat(rd.replace('Z','+00:00'))))

    def _finish_if_needed(self,s,table_id,gs):
        m=s.get(Match,gs.match_id); active=[p for p in _players(s,table_id) if p.active]
        if len(active)!=1:return False
        awarded=gs.pot; winner=active[0]; winner.balance+=awarded; m.winner_player_id=winner.id; m.ended_at=now(); m.status='FINISHED'; m.pot=awarded
        t=s.get(Table,table_id); t.status='REPLAY'; gs.current_player_id=None; gs.turn_started_at=None; gs.turn_deadline=None
        payload=json.loads(gs.payload or '{}'); payload.update({'last_award':{'winner_id':winner.id,'winner_name':winner.name,'amount':awarded},'replay_yes':[p.id for p in _players(s,table_id) if p.balance>=t.boot], 'replay_no':[], 'replay_started_at':iso(now()), 'replay_deadline':iso(now()+timedelta(seconds=10))}) ; gs.payload=json.dumps(payload); gs.state_version+=1
        # Reset per-match visibility but retain balances.
        for p in _players(s,table_id): p.seen_cards=False; p.blind_plays=0; p.active=True
        return True

    async def timeout_turn(self,table_id,match_id,player_id):
        rt=state_manager.runtime(table_id)
        async with rt.lock:
            with SessionLocal() as s:
                gs=s.get(GameState,table_id)
                if not gs or gs.match_id!=match_id or gs.current_player_id!=player_id or not gs.turn_deadline or now()<as_utc(gs.turn_deadline):return
                p=s.get(Player,player_id)
                if not p or not p.active:return
                p.active=False; s.add(Action(match_id=match_id,player_id=player_id,action='TIMEOUT'))
                next_id=self._advance_player(s,table_id,player_id); gs.current_player_id=next_id; gs.state_version+=1
                finished=self._finish_if_needed(s,table_id,gs)
                if not finished and next_id:
                    ts=now(); gs.turn_started_at=ts; gs.turn_deadline=ts+timedelta(seconds=settings.turn_seconds)
                s.commit()
                await push_state(table_id,'MATCH_FINISHED' if finished else 'TIMEOUT',actor_id=player_id)
                if not finished and next_id: await self._schedule_timeout(table_id,match_id,next_id,gs.turn_deadline)
                elif finished:
                    with SessionLocal() as ss:
                        gg=ss.get(GameState,table_id); pp=json.loads(gg.payload or '{}'); rd=pp.get('replay_deadline')
                    if rd: await self._schedule_replay_start(table_id,match_id,as_utc(datetime.fromisoformat(rd.replace('Z','+00:00'))))

    async def disconnect(self,table_id,player_id):
        with SessionLocal() as s:
            p=s.get(Player,player_id)
            if p and p.table_id==table_id: p.connected=False; p.last_seen=now(); s.commit()
        await state_manager.remove_connection(table_id,player_id); await push_state(table_id,'PLAYER_LEFT',actor_id=player_id)

    async def reconnect(self,table_id,player_id):
        with SessionLocal() as s:
            p=s.get(Player,player_id)
            if not p or p.table_id!=table_id: raise ValueError('Invalid session.')
            p.connected=True; p.last_seen=now(); s.commit(); st=_private_state(s,table_id,player_id)
        return st

match_service=MatchService()
