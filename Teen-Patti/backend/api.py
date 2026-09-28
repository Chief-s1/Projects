import logging
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from database.database import init_db, SessionLocal
from database.models import Player, Table
from backend.auth import verify_token
from backend.state_manager import state_manager
from services.match_service import match_service, _private_state
from services.excel_service import build_match_workbook
from config import settings

logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format='%(asctime)s %(levelname)s %(message)s')
app=FastAPI(title='Teen Patti Realtime Backend',version='1.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

class CreateRequest(BaseModel): host_name:str=Field(min_length=1,max_length=80); starting_chips:int=Field(gt=0); boot:int=Field(gt=0)
class JoinRequest(BaseModel): join_code:str=Field(min_length=4,max_length=4,pattern=r'^\d{4}$'); player_name:str=Field(min_length=1,max_length=80)
class ActionRequest(BaseModel): player_id:str; token:str; action:str; request_id:str
class SideShowRequestModel(BaseModel): player_id:str; token:str; request_id:str; accept:bool

@app.on_event('startup')
def startup(): init_db()

@app.get('/health')
def health(): return {'ok':True,'service':'teen-patti','websocket_port':settings.websocket_port}

@app.post('/api/tables')
def create(req:CreateRequest):
    try:return match_service.create_table(req.host_name,req.starting_chips,req.boot)
    except ValueError as e: raise HTTPException(400,str(e))

@app.post('/api/tables/join')
async def join(req:JoinRequest):
    try:
        data=match_service.join_table(req.join_code,req.player_name)
        from services.match_service import push_state
        await push_state(data['table_id'],'PLAYER_JOINED',actor_id=data['player_id'])
        return data
    except ValueError as e: raise HTTPException(400,str(e))

@app.get('/api/tables/{table_id}/state')
def state(table_id:str,player_id:str=Query(...),token:str=Query(...)):
    with SessionLocal() as s:
        p=s.get(Player,player_id)
        if not p or p.table_id!=table_id or not verify_token(token,p.session_token_hash): raise HTTPException(401,'Invalid session')
        return _private_state(s,table_id,player_id)

@app.post('/api/tables/{table_id}/start')
async def start(table_id:str, req:ActionRequest):
    with SessionLocal() as s:
        p=s.get(Player,req.player_id)
        if not p or p.table_id!=table_id or not verify_token(req.token,p.session_token_hash): raise HTTPException(401,'Invalid session')
    try: await match_service.start_match(table_id,req.player_id)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}

@app.post('/api/tables/{table_id}/action')
async def action(table_id:str,req:ActionRequest):
    with SessionLocal() as s:
        p=s.get(Player,req.player_id)
        if not p or p.table_id!=table_id or not verify_token(req.token,p.session_token_hash): raise HTTPException(401,'Invalid session')
    try: await match_service.action(table_id,req.player_id,req.player_id,req.action,req.request_id)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}

@app.post('/api/tables/{table_id}/side-show')
async def side_show(table_id:str,req:SideShowRequestModel):
    with SessionLocal() as s:
        p=s.get(Player,req.player_id)
        if not p or p.table_id!=table_id or not verify_token(req.token,p.session_token_hash): raise HTTPException(401,'Invalid session')
    try: await match_service.side_show_response(table_id,req.player_id,req.request_id,req.accept)
    except ValueError as e: raise HTTPException(400,str(e))
    return {'ok':True}

@app.get('/api/reports.xlsx')
def report():
    from fastapi.responses import Response
    return Response(build_match_workbook(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename=teen_patti_report.xlsx'})

@app.get('/api/tables/{table_id}/scores.xlsx')
def table_report(table_id:str, player_id:str=Query(...), token:str=Query(...)):
    from fastapi.responses import Response
    from services.excel_service import build_match_workbook
    from datetime import datetime
    with SessionLocal() as s:
        p=s.get(Player,player_id)
        if not p or p.table_id!=table_id or not verify_token(token,p.session_token_hash):
            raise HTTPException(401,'Invalid session')
    filename=datetime.now().strftime('%H-%M-%d-%b-%y_score_list.xlsx')
    return Response(
        content=build_match_workbook(table_id),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':f'attachment; filename="{filename}"'},
    )

@app.websocket('/ws/{table_id}/{player_id}')
async def websocket(ws:WebSocket,table_id:str,player_id:str,token:str):
    await ws.accept()
    with SessionLocal() as s:
        p=s.get(Player,player_id)
        if not p or p.table_id!=table_id or not verify_token(token,p.session_token_hash):
            await ws.close(code=1008); return
    await state_manager.add_connection(table_id,player_id,ws)
    try:
        state=await match_service.reconnect(table_id,player_id)
        await ws.send_json({'type':'STATE_SYNC','version':state['state_version'],'server_timestamp':__import__('time').time(),'state':state})
        while True:
            msg=await ws.receive_json()
            typ=msg.get('type','').upper(); reqid=msg.get('request_id')
            if typ=='PING': await ws.send_json({'type':'PONG','server_timestamp':__import__('time').time(),'client_timestamp':msg.get('client_timestamp')}); continue
            if typ=='ACTION':
                action_name=msg.get('action','').upper()
                try:
                    if action_name=='START_MATCH':
                        await match_service.start_match(table_id,player_id)
                    else:
                        await match_service.action(table_id,player_id,player_id,action_name,reqid)
                except ValueError as e: await ws.send_json({'type':'ERROR','error':str(e),'request_id':reqid})
            elif typ=='SIDE_SHOW_RESPONSE':
                try: await match_service.side_show_response(table_id,player_id,msg.get('request_id'),bool(msg.get('accept')))
                except ValueError as e: await ws.send_json({'type':'ERROR','error':str(e),'request_id':reqid})
    except WebSocketDisconnect:
        await match_service.disconnect(table_id,player_id)
    except Exception:
        await match_service.disconnect(table_id,player_id)
        raise
