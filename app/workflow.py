"""LangGraph checkpoints approval pause/resume; SQLite owns atomic side effects."""
import os
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

class State(TypedDict,total=False):
    approval_id:str
    decision:str
    result:dict


def review(state):
    decision=interrupt({'approval_id':state['approval_id'],'message':'Authenticated reviewer required before resuming.'})
    return {'decision':decision}


def execute(state):
    from app import governance as g
    with g.db() as c:
        import json
        row=c.execute('SELECT body,state FROM approvals WHERE id=?',(state['approval_id'],)).fetchone()
    if row and row[1]!='pending':
        saved=json.loads(row[0]).get('resolution_trace')
        if saved:return {'result':saved}
        raise ValueError('This legacy approval is already resolved.')
    return {'result':g.resolve(state['approval_id'],state['decision'])}


def graph(checkpointer):
    builder=StateGraph(State);builder.add_node('review',review);builder.add_node('execute',execute)
    builder.add_edge(START,'review');builder.add_edge('review','execute');builder.add_edge('execute',END)
    return builder.compile(checkpointer=checkpointer)


def invoke(approval_id,decision=None):
    path=Path(os.getenv('DATA_DIR','/data'))/'workflow.sqlite'
    config={'configurable':{'thread_id':approval_id}}
    with SqliteSaver.from_conn_string(str(path)) as saver:
        compiled=graph(saver)
        snapshot=compiled.get_state(config)
        if not snapshot.values:
            compiled.invoke({'approval_id':approval_id},config)
        if decision is None:return {'thread_id':approval_id,'state':'paused'}
        if snapshot.values.get('result'):raise ValueError('Workflow has already completed.')
        result=compiled.invoke(Command(resume=decision),config)
        return result['result']
