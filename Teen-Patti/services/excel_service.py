from io import BytesIO
import pandas as pd
from sqlalchemy import select
from database.database import SessionLocal
from database.models import Match, Player, Action, Contribution

def build_match_workbook(table_id=None):
    with SessionLocal() as s:
        matches=s.execute(select(Match).where(Match.table_id==table_id) if table_id else select(Match)).scalars().all()
        players=s.execute(select(Player)).scalars().all()
        actions=s.execute(select(Action)).scalars().all()
        contrib=s.execute(select(Contribution)).scalars().all()
        pmap={p.id:p for p in players}
        scores=[]
        for m in matches:
            for p in players:
                if p.table_id != m.table_id: continue
                cs=sum(c.amount for c in contrib if c.match_id==m.id and c.player_id==p.id)
                scores.append({'Match ID':m.id,'Player':p.name,'Starting Chips':p.starting_balance,'Boot':m.boot,'Total Contribution':cs,'Final Chips':p.balance,'Winner':p.id==m.winner_player_id})
        histories=[{'Match ID':m.id,'Start Time':m.started_at,'End Time':m.ended_at,'Boot':m.boot,'Pot':m.pot,'Winner':pmap[m.winner_player_id].name if m.winner_player_id in pmap else ''} for m in matches]
        ledger=[]
        for m in matches:
            if not m.winner_player_id: continue
            winner=pmap.get(m.winner_player_id)
            for c in contrib:
                if c.match_id==m.id and c.player_id!=m.winner_player_id:
                    ledger.append({'Match ID':m.id,'Player':pmap[c.player_id].name,'Winner':winner.name if winner else '', 'Amount':c.amount})
        logs=[{'Match ID':a.match_id,'Timestamp':a.timestamp,'Player':pmap[a.player_id].name if a.player_id in pmap else '', 'Action':a.action,'Amount':a.amount} for a in actions]
    bio=BytesIO()
    with pd.ExcelWriter(bio,engine='openpyxl') as writer:
        pd.DataFrame(scores).to_excel(writer,index=False,sheet_name='Player Scores')
        pd.DataFrame(histories).to_excel(writer,index=False,sheet_name='Match History')
        pd.DataFrame(ledger).to_excel(writer,index=False,sheet_name='Ownership Ledger')
        pd.DataFrame(logs).to_excel(writer,index=False,sheet_name='Action Log')
    bio.seek(0); return bio.getvalue()

def save_table_score_file(table_id):
    from pathlib import Path
    from datetime import datetime
    out_dir=Path('scores')
    out_dir.mkdir(parents=True, exist_ok=True)
    # ':' is not a valid Windows filename character, so HH-MM is used on the
    # admin host while retaining the requested timestamp ordering.
    filename=datetime.now().strftime('%H-%M-%d-%b-%y_score_list.xlsx')
    path=out_dir/filename
    path.write_bytes(build_match_workbook(table_id))
    return str(path), filename
