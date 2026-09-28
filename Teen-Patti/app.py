import json, os
import requests
import streamlit as st
from config import settings

st.set_page_config(page_title='Teen Patti', page_icon='🃏', layout='wide', initial_sidebar_state='collapsed')
BACKEND=f'http://127.0.0.1:{settings.websocket_port}'

if 'session' not in st.session_state:
    st.session_state.session=None

st.markdown('''<style>
[data-testid="stAppViewContainer"]{background:#f5f7fb;color:#172033}
[data-testid="stHeader"]{background:#f5f7fb}
[data-testid="stToolbar"]{visibility:hidden}
.block-container{max-width:1280px;padding-top:1.25rem;padding-bottom:1rem}
.hero{padding:22px 28px;border-radius:18px;background:#fff;border:1px solid #e2e8f0;margin-bottom:16px;box-shadow:0 8px 28px rgba(15,23,42,.06)}
.hero h1{margin:0;font-size:36px;color:#172033}.hero p{color:#64748b;margin:5px 0 0}
</style>''',unsafe_allow_html=True)


def api_post(path,payload):
    r=requests.post(BACKEND+path,json=payload,timeout=5)
    if not r.ok:
        try: detail=r.json().get('detail','Request failed')
        except Exception: detail=r.text
        raise RuntimeError(detail)
    return r.json()


def game_component(session):
    cfg={'table_id':session['table_id'],'player_id':session['player_id'],'token':session['token'],'ws_port':settings.websocket_port,'host':os.getenv('PUBLIC_HOST','')}
    payload=json.dumps(cfg).replace('</','<\\/')
    component=r'''<!doctype html>
<html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
body{margin:0;background:#f5f7fb;color:#172033;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}
.wrap{padding:4px 8px 20px}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:16px 20px;box-shadow:0 5px 18px rgba(15,23,42,.05)}
.brand{display:flex;align-items:center;gap:12px}.brandIcon{width:44px;height:44px;border-radius:13px;background:#ecfdf5;color:#087443;display:flex;align-items:center;justify-content:center;font-size:25px}.title{font-size:24px;font-weight:850;line-height:1.1}.subtitle{font-size:12px;color:#64748b;margin-top:4px}
.stats{display:flex;gap:8px;flex-wrap:wrap}.pill{background:#f8fafc;border:1px solid #e2e8f0;padding:8px 12px;border-radius:11px;font-size:13px}.pill b{font-size:15px}
.connection{font-size:12px;color:#64748b;margin:9px 2px}.online{color:#087443!important}.offline{color:#b42318!important}
.table{position:relative;margin:14px auto;max-width:1100px;min-height:610px;border-radius:42px;background:linear-gradient(145deg,#dcefe4,#cfe8d9);border:1px solid #b8d8c5;box-shadow:0 18px 50px rgba(15,23,42,.10);padding:22px;overflow:hidden}
.felt{position:absolute;inset:12px;border-radius:34px;background:radial-gradient(circle at 50% 42%,#ffffff 0%,#f8fffb 35%,#edf9f1 100%);border:1px solid #cce4d5}
.seats{position:relative;z-index:2;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:start}
.player{position:relative;background:#fff;border:1px solid #e2e8f0;border-radius:15px;padding:12px;min-height:78px;box-shadow:0 5px 15px rgba(15,23,42,.07);display:flex;gap:10px;align-items:center;overflow:hidden}.player.turn{border-color:transparent}.player.turn::before{content:"";position:absolute;inset:-2px;border-radius:17px;padding:2px;background:conic-gradient(#16a34a var(--timer-progress,0%),#fff 0);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}.player.turn::after{content:"";position:absolute;inset:2px;border-radius:13px;box-shadow:inset 0 0 0 1px rgba(22,163,74,.08);pointer-events:none}.player > *{position:relative;z-index:1}
.player.me{border-color:#79cfa2;box-shadow:0 0 0 2px rgba(16,185,129,.10),0 5px 15px rgba(15,23,42,.07)}
.player.turn{border-color:transparent;box-shadow:0 0 0 2px rgba(22,163,74,.10),0 5px 18px rgba(15,23,42,.09)}
.player.packed{opacity:.58}.avatar{width:42px;height:42px;min-width:42px;border-radius:50%;background:#edf2f7;border:1px solid #dbe3ec;display:flex;align-items:center;justify-content:center;font-size:20px}.me .avatar{background:#e8f8ef;border-color:#b8e4c9}.playerInfo{min-width:0}.name{font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.meta{font-size:11px;color:#64748b;margin-top:4px}.turnLabel{font-size:10px;font-weight:800;color:#a86b00;margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
.empty{visibility:hidden}
.center{position:absolute;z-index:3;left:50%;top:47%;transform:translate(-50%,-50%);text-align:center}.potLabel{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#64748b;font-weight:800}.pot{font-size:38px;font-weight:900;color:#172033;margin-top:3px}.bid{display:inline-block;margin-top:6px;padding:6px 10px;border-radius:999px;background:#eef8f2;color:#087443;font-size:12px;font-weight:750}
.myArea{position:absolute;z-index:4;left:50%;bottom:16px;transform:translateX(-50%);width:min(700px,88%);background:#fff;border:1px solid #cfe2d7;border-radius:20px;padding:14px 16px;box-shadow:0 12px 30px rgba(15,23,42,.12)}.myArea.turnTimer{border-color:transparent}.myArea.turnTimer::before{content:"";position:absolute;inset:-2px;border-radius:22px;padding:2px;background:conic-gradient(#16a34a var(--timer-progress,0%),#fff 0);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}.myArea.turnTimer > *{position:relative;z-index:1}
.myHeader{display:flex;align-items:center;justify-content:space-between;gap:12px}.myIdentity{display:flex;align-items:center;gap:10px}.myName{font-size:16px;font-weight:850}.myBalance{font-size:12px;color:#64748b}.myCards{display:flex;justify-content:center;gap:10px;margin:12px 0 13px;min-height:94px}.card{width:66px;height:92px;border-radius:10px;background:#fff;border:1px solid #d5dde7;box-shadow:0 5px 12px rgba(15,23,42,.12);display:flex;align-items:center;justify-content:center;font-size:27px;font-weight:800}.card.red{color:#d32f2f}.card.black{color:#172033}.card.back{background:repeating-linear-gradient(45deg,#e8eef5,#e8eef5 6px,#dce5ef 6px,#dce5ef 12px);color:#6b7b8d;font-size:25px}
.timerRow{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:8px}.timer{font-size:27px;font-weight:900;font-variant-numeric:tabular-nums}.timer.warn{color:#b42318}.timerHint{font-size:11px;color:#64748b}.turnText{font-size:12px;color:#64748b;text-align:center}.actions{display:flex;justify-content:center;gap:8px;flex-wrap:wrap;margin-top:10px}button{border:1px solid #d2dae4;border-radius:10px;padding:10px 15px;font-weight:750;cursor:pointer;background:#f8fafc;color:#172033}button.primary{background:#087443;color:#fff;border-color:#087443}button.secondary{background:#eef7f2;color:#087443;border-color:#bfe2ce}button.danger{background:#b42318;color:#fff;border-color:#b42318}button.host{background:#1d4ed8;color:#fff;border-color:#1d4ed8;padding:12px 20px}button:disabled{opacity:.38;cursor:not-allowed}
.lobby{position:absolute;z-index:4;left:50%;top:50%;transform:translate(-50%,-50%);width:min(620px,88%);text-align:center;background:#fff;border:1px solid #dce5ed;border-radius:20px;padding:28px;box-shadow:0 15px 40px rgba(15,23,42,.10)}.lobby h2{margin:0 0 5px}.lobby p{color:#64748b;margin:0 0 18px}.hostStart{display:inline-flex;align-items:center;gap:8px}.requirement{margin-top:12px;font-size:12px;color:#64748b}
.msg{position:fixed;z-index:20;right:18px;top:18px;padding:11px 14px;border-radius:11px;background:#fff7e8;color:#8a5a00;border:1px solid #efd39a;box-shadow:0 10px 25px rgba(15,23,42,.12);display:none}.overlay{position:fixed;z-index:30;inset:0;background:rgba(15,23,42,.42);display:none;align-items:center;justify-content:center}.modal{background:#fff;color:#172033;border:1px solid #d9e2ec;border-radius:18px;padding:25px;max-width:420px;width:90%;box-shadow:0 20px 60px rgba(15,23,42,.25)}.showdownModal{max-width:720px}.showdownCards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin:18px 0}.showdownHand{background:#f8fafc;border:1px solid #e2e8f0;border-radius:15px;padding:14px;text-align:center}.showdownName{font-weight:850;margin-bottom:10px}.showdownWinner{border-color:#16a34a;background:#f0fdf4}.showdownCardsRow{display:flex;justify-content:center;gap:8px}.showdownCardsRow .card{width:58px;height:80px;font-size:23px}.showdownBadge{margin-top:9px;color:#087443;font-size:12px;font-weight:850;text-transform:uppercase}.replayOverlay{z-index:50}.award{margin:12px auto;padding:12px 16px;border-radius:12px;background:#ecfdf5;border:1px solid #86efac;color:#166534;font-weight:850;text-align:center}.replayCount{font-size:34px;font-weight:900;text-align:center;margin:12px 0;color:#166534}
@media(max-width:850px){.table{min-height:720px}.seats{grid-template-columns:repeat(2,minmax(0,1fr))}.center{top:38%}.myArea{bottom:14px}.stats{width:100%}}
</style></head><body>
<div class="wrap"><div id="connection" class="connection">Connecting…</div><div id="root"></div><div id="msg" class="msg"></div></div>
<div id="modal" class="overlay"><div class="modal"><h2>Side Show Request</h2><p id="modalText"></p><div class="actions"><button class="primary" onclick="side(true)">Accept</button><button onclick="side(false)">Decline</button></div></div></div><div id="showdown" class="overlay"><div class="modal showdownModal"><h2 id="winnerTitle">🏆 Winner</h2><p id="showdownText"></p><div id="showdownCards" class="showdownCards"></div><div id="replayBanner"></div></div></div>
<script>
const CFG=__CFG__;let ws=null,state=null,serverOffset=0,pendingSide=null,reconnectTimer=null,replayChoice=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function wsHost(){try{const ref=document.referrer;if(ref){const u=new URL(ref);if(u.hostname)return u.hostname}}catch(e){}try{if(window.parent&&window.parent.location.hostname)return window.parent.location.hostname}catch(e){}return location.hostname||location.host.split(':')[0]}
function wsUrl(){const h=CFG.host||wsHost();const scheme=(location.protocol==='https:'?'wss':'ws');return `${scheme}://${h}:${CFG.ws_port}/ws/${CFG.table_id}/${CFG.player_id}?token=${encodeURIComponent(CFG.token)}`}
function setConnection(text,ok=false){const el=document.getElementById('connection');if(el){el.textContent=text;el.className='connection '+(ok?'online':'offline')}}
function connect(){if(ws&&[WebSocket.OPEN,WebSocket.CONNECTING].includes(ws.readyState))return;const url=wsUrl();setConnection('Connecting to realtime server…');try{ws=new WebSocket(url)}catch(e){setConnection('WebSocket error');scheduleReconnect();return}ws.onopen=()=>{setConnection('● Realtime connected',true);send('PING',{client_timestamp:Date.now()/1000})};ws.onerror=()=>setConnection('Realtime connection failed — check backend/firewall');ws.onmessage=e=>{let m;try{m=JSON.parse(e.data)}catch{return}if(m.server_timestamp)serverOffset=m.server_timestamp-Date.now()/1000;if(m.type==='STATE_SYNC'){state=m.state;if(m.side_show_cost&&m.side_show_requester_id===CFG.player_id)showMsg(`Side Show cost: ${m.side_show_cost} chips`);render()}else if(m.type==='SIDE_SHOW_REQUEST'){pendingSide=m.request_id;document.getElementById('modalText').textContent=`${esc(m.from_player_name)} wants a Side Show.`;document.getElementById('modal').style.display='flex'}else if(m.type==='ERROR'){showMsg(m.error)}else if(m.type==='TIMEOUT'){showMsg(`${m.state?.players?.find?.(p=>p.id===m.actor_id)?.name||'Player'} timed out and was automatically packed.`)}else if(m.type==='MATCH_FINISHED'){showMsg('Match finished. Winner received the pot.')}else if(m.type==='PONG'&&m.client_timestamp){serverOffset=m.server_timestamp-(Date.now()/1000)}};ws.onclose=()=>{setConnection('Realtime disconnected — reconnecting…');scheduleReconnect()}}
function scheduleReconnect(){clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connect,1200)}
function send(type,p={}){if(ws&&ws.readyState===1)ws.send(JSON.stringify({type,...p}))}
function action(a){if(a==='START_MATCH'){send('ACTION',{action:a,request_id:crypto.randomUUID()});return}send('ACTION',{action:a,request_id:crypto.randomUUID()})}
function side(accept){if(pendingSide){send('SIDE_SHOW_RESPONSE',{request_id:pendingSide,accept});pendingSide=null}document.getElementById('modal').style.display='none'}
function scoreUrl(){const h=CFG.host||wsHost();return `http://${h}:${CFG.ws_port}/api/tables/${CFG.table_id}/scores.xlsx?player_id=${encodeURIComponent(CFG.player_id)}&token=${encodeURIComponent(CFG.token)}`}
function renderShowdown(){
 const box=document.getElementById('showdown'); if(!box||!state)return;
 const isReplay=state.status==='REPLAY'||state.replay_ended;
 const hasWinner=!!state.last_award?.winner_name;
 if(!isReplay||!hasWinner){box.style.display='none';return}
 const players=state.show_reveal?state.players.filter(p=>state.show_reveal[p.id]):[];
 const cardsHtml=players.map(p=>{const isWinner=p.id===state.show_winner_id;const cards=state.show_reveal[p.id].map(c=>{const x=card(c);return `<div class="card ${x.red?'red':'black'}">${x.text}</div>`}).join('');return `<div class="showdownHand ${isWinner?'showdownWinner':''}"><div class="showdownName">${esc(p.name)}</div><div class="showdownCardsRow">${cards}</div>${isWinner?'<div class="showdownBadge">Winner · Pot awarded</div>':''}</div>`}).join('');
 const award=state.last_award?.amount??0; document.getElementById('winnerTitle').textContent='🏆 Winner';
 document.getElementById('showdownText').innerHTML=`<b>${esc(state.last_award.winner_name)}</b> won <b>${award}</b> chips.`;
 document.getElementById('showdownCards').innerHTML=cardsHtml;
 const yes=new Set(state.replay_yes||[]), no=new Set(state.replay_no||[]); const deadline=state.replay_deadline?Math.max(0,Math.ceil(new Date(state.replay_deadline).getTime()/1000-(Date.now()/1000+serverOffset))):0;
 const choseNo=no.has(CFG.player_id), choseYes=yes.has(CFG.player_id);
 let banner='';
 if(choseNo || state.replay_ended){
   banner=`<div class="award">Thank you for playing! Your score file is ready.</div><div class="actions"><a href="${scoreUrl()}" target="_blank" download style="text-decoration:none"><button class="primary">⬇ Download Scores</button></a></div>`;
 } else if(deadline>0){
   banner=`<div class="award">New match starts in</div><div class="replayCount">${deadline}s</div><p style="text-align:center">Players are currently opted in by default. You can leave before the countdown ends.</p><div class="actions"><button onclick="replayVote('REPLAY_NO')">No, I'm done</button></div>`;
 } else {
   banner=`<div class="award">Starting new match…</div>`;
 }
 document.getElementById('replayBanner').innerHTML=banner;
 box.style.display='flex';
}

function replayVote(a){send('ACTION',{action:a,request_id:crypto.randomUUID()})}
function showMsg(x){const el=document.getElementById('msg');if(!el)return;el.textContent=x;el.style.display='block';clearTimeout(window.msgTimer);window.msgTimer=setTimeout(()=>el.style.display='none',3500)}
function remaining(){if(!state?.turn_deadline)return 0;return Math.max(0,new Date(state.turn_deadline).getTime()/1000-(Date.now()/1000+serverOffset))}
function card(c){let rank=c.slice(0,-1),s=c.slice(-1);if(rank==='T')rank='10';let sm={S:'♠',H:'♥',D:'♦',C:'♣'}[s];return {text:rank+sm,red:s==='H'||s==='D'}}
function avatar(name){return (String(name||'?').trim()[0]||'?').toUpperCase()}
function playerTile(p){let me=p.id===CFG.player_id,turn=p.id===state.current_player_id;let pct=0;if(turn){const total=Math.max(1,Number(state.turn_deadline&&state.turn_started_at?((new Date(state.turn_deadline).getTime()-new Date(state.turn_started_at).getTime())/1000):30));pct=Math.max(0,Math.min(100,(remaining()/total)*100));}return `<div class=\"player ${me?'me':''} ${turn?'turn':''} ${!p.active?'packed':''}\" data-player-id=\"${p.id}\" style=\"--timer-progress:${pct}\"><div class=\"avatar\">${avatar(p.name)}</div><div class=\"playerInfo\"><div class=\"name\">${esc(p.name)}${me?' (You)':''}</div><div class=\"meta\">${p.active?'Active':'Packed'} · ${p.connected?'Online':'Offline'} · ${p.balance} chips</div>${turn?'<div class=\"turnLabel\">'+Math.ceil(remaining())+'s · Current turn</div>':''}</div></div>`}

function render(){if(!state)return;renderShowdown();const me=state.players.find(p=>p.id===CFG.player_id);if(!me)return;const isHost=state.host_player_id===CFG.player_id;const opponents=state.players.filter(p=>p.id!==CFG.player_id);const tiles=opponents.map(playerTile).join('');const myTurn=state.current_player_id===CFG.player_id&&state.status==='PLAYING';const activeCount=state.players.filter(p=>p.active).length;const showAvailable=myTurn&&activeCount===2;const left=Math.ceil(remaining());const cards=state.my_cards?.length?state.my_cards.map(c=>{const x=card(c);return `<div class="card ${x.red?'red':'black'}">${x.text}</div>`}).join(''):`<div class="card back">🂠</div><div class="card back">🂠</div><div class="card back">🂠</div>`;const showLobby=state.status==='LOBBY';const start=showLobby&&isHost?`<button class="host" onclick="action('START_MATCH')">▶ Start Game</button>`:`<div class="requirement">${showLobby?'Waiting for the host to start the game…':''}</div>`;const mySeen=me.seen_cards;const req=mySeen?state.current_bid*2:state.current_bid;document.getElementById('root').innerHTML=`<div class="topbar"><div class="brand"><div class="brandIcon">🃏</div><div><div class="title">Teen Patti</div><div class="subtitle">Table ${esc(state.table_code)} · ${state.players.length}/15 players</div></div></div><div class="stats"><div class="pill">Boot <b>${state.boot}</b></div><div class="pill">Current Bid <b>${state.current_bid}</b></div><div class="pill">Pot <b>${state.pot}</b></div></div></div><div class="table"><div class="felt"></div><div class="seats">${tiles}</div><div class="center"><div class="potLabel">Pot</div><div class="pot">${state.pot}</div><div class="bid">Current bid · ${state.current_bid}</div></div>${showLobby?`<div class="lobby"><h2>Waiting to start</h2><p>${state.players.length} player${state.players.length===1?'':'s'} at the table. The host controls when the match begins.</p><div class="hostStart">${start}</div><div class="requirement">Minimum 2 players · Maximum 15 players</div></div>`:`<div class="myArea ${myTurn?'turnTimer':''}" style="--timer-progress:${Math.max(0,Math.min(100,(left/30)*100))}%"><div class="myHeader"><div class="myIdentity"><div class="avatar">${avatar(me.name)}</div><div><div class="myName">${esc(me.name)} (You)</div><div class="myBalance">${me.balance} chips · ${me.active?'Active':'Packed'}</div></div></div><div class="pill">${myTurn?'YOUR TURN':'WAITING'}</div></div><div class="myCards">${cards}</div><div class="timerRow"><div id="timer" class="timer">${left}s</div></div><div class="turnText">${myTurn?'Make your move. If the timer reaches 0, the server automatically packs you.':`Waiting for ${esc(state.players.find(p=>p.id===state.current_player_id)?.name||'next player')}.`}</div><div class="actions"><button class="secondary" onclick="action('SEE_CARDS')" ${!myTurn||me.seen_cards?'disabled':''}>See Cards</button><button class="primary" onclick="action('BID')" ${!myTurn?'disabled':''}>Bid ${req}</button><button onclick="action('BID_DOUBLE')" ${!myTurn?'disabled':''}>2× Bid</button><button class="danger" onclick="action('PACK')" ${!myTurn?'disabled':''}>Pack</button><button onclick="action('SIDE_SHOW')" ${!myTurn||!me.seen_cards?'disabled':''}>Side Show</button>${showAvailable?`<button class="primary" onclick="action('SHOW')">Show</button>`:''}</div></div>`}</div>`}
function animateTimer(){
 if(state){
  const left=remaining();
  const total=Math.max(1,Number(state.turn_deadline&&state.turn_started_at?((new Date(state.turn_deadline).getTime()-new Date(state.turn_started_at).getTime())/1000):30));
  const pct=Math.max(0,Math.min(100,(left/total)*100));
  document.querySelectorAll('.player.turn, .myArea.turnTimer').forEach(el=>el.style.setProperty('--timer-progress',pct+'%'));
  const t=document.getElementById('timer');if(t){const r=Math.ceil(left);t.textContent=r+'s';t.classList.toggle('warn',r<=5)}
  document.querySelectorAll('.player.turn .turnLabel').forEach(el=>el.textContent=Math.ceil(left)+'s · Current turn');
 }
 requestAnimationFrame(animateTimer);
}

setInterval(()=>{if(state){renderShowdown();render();}},1000);
requestAnimationFrame(animateTimer);connect();
</script></body></html>'''.replace('__CFG__',payload)
    import streamlit.components.v1 as components
    components.html(component,height=840,scrolling=False)

st.markdown('<div class="hero"><h1>🃏 Teen Patti</h1><p>Private player cards · realtime server-authoritative turns · automatic timeout packing.</p></div>',unsafe_allow_html=True)

if not st.session_state.session:
    tab1,tab2=st.tabs(['Create Table','Join Table'])
    with tab1:
        with st.form('create'):
            name=st.text_input('Player name'); chips=st.number_input('Starting chips',min_value=1,value=1000,step=100); boot=st.number_input('Boot',min_value=1,value=100,step=10)
            submitted=st.form_submit_button('Create Table',type='primary')
        if submitted:
            try:
                data=api_post('/api/tables',{'host_name':name,'starting_chips':chips,'boot':boot});st.session_state.session=data;st.rerun()
            except Exception as e: st.error(str(e))
    with tab2:
        with st.form('join'):
            code=st.text_input('4-digit joining code',max_chars=4); name=st.text_input('Player name',key='join_name')
            submitted=st.form_submit_button('Join Table',type='primary')
        if submitted:
            try:
                data=api_post('/api/tables/join',{'join_code':code,'player_name':name});st.session_state.session=data;st.rerun()
            except Exception as e: st.error(str(e))
else:
    game_component(st.session_state.session)
    if st.button('Leave table'):
        st.session_state.session=None;st.rerun()
