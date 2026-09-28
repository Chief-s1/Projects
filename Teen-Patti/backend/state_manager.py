import asyncio
from collections import defaultdict

class TableRuntime:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.connections = {}
        self.last_action_ids = set()
        self.timeout_task = None

class StateManager:
    def __init__(self): self.tables = defaultdict(TableRuntime)
    def runtime(self, table_id): return self.tables[table_id]
    async def add_connection(self, table_id, player_id, ws):
        rt=self.runtime(table_id); rt.connections[player_id]=ws
    async def remove_connection(self, table_id, player_id):
        rt=self.runtime(table_id); rt.connections.pop(player_id, None)
    async def broadcast(self, table_id, message):
        rt=self.runtime(table_id)
        dead=[]
        for pid, ws in list(rt.connections.items()):
            try: await ws.send_json(message)
            except Exception: dead.append(pid)
        for pid in dead: rt.connections.pop(pid, None)
    async def send(self, table_id, player_id, message):
        ws=self.runtime(table_id).connections.get(player_id)
        if ws:
            try: await ws.send_json(message)
            except Exception: self.runtime(table_id).connections.pop(player_id,None)

state_manager = StateManager()
