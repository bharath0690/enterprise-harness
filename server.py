"""Local product interface for the shared Deep Agents harness. Run: python server.py."""
import ast
from contextlib import contextmanager
import json
import mimetypes
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from stages import build_stage, STAGES
from langgraph.checkpoint.memory import InMemorySaver
from company import Company, ROOT, ACCESS
from runtime import make_model, PreviewModel
from workspace import recover_old_files, working_files
import shutil

STAGE = os.getenv('NSWORK_STAGE', 'persistence')
STAGE = {'ongoing': 'persistence'}.get(STAGE, STAGE)
if STAGE not in STAGES:
    raise ValueError('Unknown NSWORK_STAGE')
MEMORY = InMemorySaver()
WEB = ROOT / 'web'
RUNTIME = ROOT / '.runtime'
RUNTIME.mkdir(exist_ok=True)
META = RUNTIME / 'product.sqlite' if STAGE == 'persistence' else f'file:nswork-{STAGE}?mode=memory&cache=shared'
_MEMORY_DB = sqlite3.connect(META, uri=True, check_same_thread=False) if STAGE != 'persistence' else None
CHECKPOINTS = RUNTIME / 'product-checkpoints.sqlite'
PORT = int(os.getenv('NSWORK_PORT', '8502'))
ACTIVE = set()
LOCK = threading.Lock()
load_dotenv(ROOT / '.env', override=True)
if not os.getenv('HARNESS_MODEL'):
    os.environ['HARNESS_MODEL'] = 'anthropic:claude-sonnet-4-6' if os.getenv('ANTHROPIC_API_KEY') else 'openai:gpt-5.4'

STARTERS = {
    'sales': [
        {'title': 'Prepare an Acme proposal', 'detail': 'Company facts, our proposal procedure and a saved draft', 'prompt': 'Use our proposal skill to prepare a concise Acme proposal using the customer record. Save the draft to /work/proposal.md. Mark pricing and timeline as awaiting confirmation. Do not send it or request a specialist review.'},
        {'title': 'Get a customer briefing', 'detail': 'Find the facts before a customer conversation', 'prompt': 'Give me a concise briefing on Beacon using our company records. Cite the record and separate what we know from questions to ask.'},
        {'title': 'Check a proposed commitment', 'detail': 'Ask a specialist to review the evidence', 'prompt': 'Ask the proposal reviewer to check this promise for Acme: We guarantee a full migration in 48 hours for $500. Tell me which claims our records support.'},
    ],
    'engineering': [
        {'title': 'Investigate the Beacon sync issue', 'detail': 'A shared triage procedure and engineering records', 'prompt': 'Use our triage skill to investigate Beacon’s sync issue. Look up the issue record and customer facts. Save a brief investigation to /work/triage.md and cite the evidence.'},
    ],
    'finance': [
        {'title': 'Summarize quarterly revenue', 'detail': 'Query the finance records with source citations', 'prompt': 'What is the revenue total for 2026-Q3? Cite the record and give me a concise summary.'},
    ],
}
SOURCE_MAP = {
    '1A': ('Company instructions','agent.py','company_context'),
    '1B': ('Shared skills','skills/company/write-proposal/SKILL.md',None),
    '2A': ('Company tools','tools/customer.py','customer_brief'),
    '2B': ('Planning','agent.py','execution_middleware'),
    '2C': ('Subagents','agent.py','specialist'),
    '3A': ('Permissions','company.py','require'),
    '3B': ('Approval','agent.py','build_harness'),
    '4A': ('Working files','agent.py','build_harness'),
    '4B': ('Checkpoints','server.py','saved_harness'),
    '4C': ('Context management','agent.py','build_harness'),
}


def stage_starters():
    """Offer tasks that use only capabilities configured in the active chapter."""
    if STAGE == 'base':
        choices = [{'title': 'Start a conversation', 'detail': 'Ask the model a question',
                    'prompt': 'What makes a useful customer discovery question? Give three examples.'}]
    elif STAGE == 'context':
        choices = [{'title': 'Prepare a proposal from a brief', 'detail': 'Use our shared proposal skill',
                    'prompt': 'Use our proposal skill to prepare a draft for Acme. Employee brief: Acme wants to unify weekly sales reporting across three teams. Pricing, timeline and exact deliverables are not confirmed. Print the draft in chat for review. Do not send it.'}]
    else:
        choices_by_role = {role: [dict(item) for item in items] for role, items in STARTERS.items()}
        if STAGE != "persistence":
            choices_by_role["sales"][0]["prompt"] = "Use our proposal skill to draft a concise Acme proposal. Look up Acme in our company records, cite the record, and print the draft in chat. Do not send it."
            choices_by_role["sales"][0]["detail"] = "Company facts and our proposal procedure"
            choices_by_role["engineering"][0]["prompt"] = "Use our triage skill to investigate Beacon's sync issue. Look up the issue record and print the findings in chat. Cite the evidence."
        return choices_by_role
    return {role: choices for role in ACCESS}


# SQLite shared-memory tables reject overlapping readers and writers immediately.
# Serialize short metadata transactions, without locking model execution.
DB_LOCK = threading.RLock()


@contextmanager
def db():
    """Serialize task metadata access from agent runs and UI polling threads."""
    with DB_LOCK:
        connection = sqlite3.connect(META, timeout=30, uri=STAGE != "persistence")
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def init_db():
    """Create task storage and mark interrupted runs after a server restart."""
    with db() as conn:
        conn.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, role TEXT, title TEXT, status TEXT, created REAL, updated REAL, error TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT, payload TEXT);
        ''')
        conn.execute("UPDATE tasks SET status='interrupted', error='The server restarted. Resume this task to continue.' WHERE status='running'")


def append_event(task, **payload):
    """Store an actual execution event for the conversation’s inline activity feed."""
    payload['time'] = time.time()
    with db() as conn:
        conn.execute('INSERT INTO events(task,payload) VALUES (?,?)', (task,json.dumps(payload,ensure_ascii=False)))


def get_task(task):
    """Retrieve a saved task or raise an error if it no longer exists."""
    with db() as conn:
        row=conn.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
    if row is None:
        raise ValueError('Task not found')
    return dict(row)


def text_content(content):
    """Extract public text blocks without exposing provider reasoning blocks."""
    if isinstance(content,str): return content
    return '\n'.join(p.get('text','') for p in content if isinstance(p,dict) and p.get('type') in {'text','output_text'})


def task_workspace(task):
    """Keep each task in a separate local directory beside the task database."""
    if not task or not all(ch.isalnum() or ch in "-_" for ch in task):
        raise ValueError("Invalid task ID")
    return Path(CHECKPOINTS).parent / "workspace" / task


def open_harness(role, saver, live=True, task=None):
    """Build the active chapter’s configuration for the selected employee role."""
    model = make_model(True) if live else PreviewModel()
    reviewer = make_model(True, specialist=True) if live else model
    return build_stage(STAGE, model, Company((RUNTIME/'company.sqlite').resolve()), role, saver, reviewer, task_workspace(task) if task else None)


@contextmanager
def saved_harness(role, live=True, task=None):
    """Reopen the same checkpoint store for each request or inspection."""
    if STAGE != 'persistence':
        yield open_harness(role, MEMORY, live, task)
    else:
        with SqliteSaver.from_conn_string(str(CHECKPOINTS)) as saver:
            yield open_harness(role, saver, live, task)


def configuration(task):
    """Keep graph execution associated with this task’s checkpoint thread."""
    return {'configurable':{'thread_id':task},'recursion_limit':200}


def tool_label(name,args):
    """Map a real tool call to its readable label and notebook component number."""
    if name=='read_file':
        path=args.get('file_path','')
        if '/skills/' in path: return 'Read shared skill','1B'
        if '/company/' in path: return 'Read company instructions','1A'
        return 'Read working file','4A'
    return {
        'customer_brief':('Look up customer facts','2A'),
        'issue_lookup':('Look up engineering issue','2A'),
        'revenue_summary':('Query revenue records','2A'),
        'write_todos':('Update the plan','2B'),
        'task':('Delegate to proposal reviewer','2C'),
        'send_proposal':('Send proposal for review','3B'),
        'write_file':('Save working file','4A'),
        'edit_file':('Update working file','4A'),
    }.get(name,(name.replace('_',' ').capitalize(),'2A'))


def safe_error(error):
    # Do not return SDK request objects, headers or credentials to the browser.
    """Return a short failure message without request headers or credentials."""
    code=getattr(error,'status_code',None)
    if code in {401,403}: return 'The model provider rejected the credential. Check the local environment.'
    if getattr(error,'code',None) in {'credit_balance_exhausted','insufficient_quota'}: return 'The provider key has no available credits. Add a funded key or replenish its balance, then resume.'
    if code==429: return 'The provider rate limit or quota was reached. Try again after checking your account.'
    if code: return f'The model provider returned HTTP {code}. This task is saved; you can retry.'
    if isinstance(error,ValueError): return str(error)[:240]
    return f'This run stopped ({type(error).__name__}). Its completed work is saved.'


def run_task(task, prompt=None, decision=None):
    """Execute or resume the graph and record its real messages, tool events, and approval state."""
    row=get_task(task)
    try:
        with saved_harness(row['role'], task=task) as graph:
            config=configuration(task)
            snapshot=graph.get_state(config)
            recover_old_files(task_workspace(task), snapshot.values.get('files', {}))
            if decision:
                interrupts=[i for t in snapshot.tasks for i in t.interrupts]
                if not interrupts: raise ValueError('There is no pending approval.')
                value=Command(resume={i.id:{'decisions':[{'type':decision} for _ in i.value['action_requests']]} for i in interrupts})
                append_event(task,kind='review',label='Approved by you' if decision=='approve' else 'Rejected by you',section='3B')
            elif prompt:
                if snapshot.next: raise ValueError('Resolve or resume the pending run before sending another request.')
                value={'messages':[{'role':'user','content':prompt}]}
            else:
                value=None
            if prompt:
                append_event(task,kind='message',role='user',text=prompt)
            append_event(task,kind='run',label='Run started',section=None)
            seen=set()
            # Complete each checkpoint before advancing to the next agent step.
            for namespace,update in graph.stream(value,config,stream_mode='updates',subgraphs=True,durability='sync'):
                for node,payload in update.items():
                    if not isinstance(payload,dict):continue
                    messages=payload.get('messages',[])
                    if not isinstance(messages,list): messages=[messages]
                    for message in messages:
                        scope='Specialist' if namespace else 'Main agent'
                        if getattr(message,'type',None)=='ai':
                            if not namespace and not message.tool_calls and text_content(message.content):
                                key=('message',message.id)
                                if key not in seen:
                                    seen.add(key)
                                    append_event(task,kind='message',role='assistant',text=text_content(message.content))
                            for call in message.tool_calls:
                                key=(str(namespace),call['id'],'call')
                                if key in seen:continue
                                seen.add(key)
                                label,section=tool_label(call['name'],call['args'])
                                append_event(task,kind='tool_call',call_id=call['id'],tool=call['name'],label=label,section=section,scope=scope,args=call['args'])
                        elif getattr(message,'type',None)=='tool':
                            key=(str(namespace),message.tool_call_id,'result')
                            if key in seen:continue
                            seen.add(key)
                            append_event(task,kind='tool_result',call_id=message.tool_call_id,tool=message.name,scope=scope,result=text_content(message.content)[:16000],failed=getattr(message,'status',None)=='error')
            snapshot=graph.get_state(config)
            interrupted=any(t.interrupts for t in snapshot.tasks)
            status='needs_review' if interrupted else 'interrupted' if snapshot.next else 'complete'
            append_event(task,kind='run_end',label='Waiting for your review' if interrupted else 'Run complete' if status=='complete' else 'Run paused',section='3B' if interrupted else None)
            with db() as conn:conn.execute('UPDATE tasks SET status=?,updated=?,error=NULL WHERE id=?',(status,time.time(),task))
    except Exception as error:
        message=safe_error(error)
        append_event(task,kind='error',label=message,section=None)
        with db() as conn:conn.execute('UPDATE tasks SET status=?,updated=?,error=? WHERE id=?',('error',time.time(),message,task))
    finally:
        with LOCK:ACTIVE.discard(task)


def delete_task(task, role):
    """Delete a stopped task, its activity, checkpoints and local workspace."""
    with LOCK:
        row = get_task(task)
        if row['role'] != role:
            raise ValueError('Use the task’s original profile.')
        if task in ACTIVE or row['status'] in {'running', 'queued'}:
            raise ValueError('Wait for this task to finish before deleting it.')
        if STAGE != 'persistence':
            MEMORY.delete_thread(task)
        else:
            with SqliteSaver.from_conn_string(str(CHECKPOINTS)) as saver:
                saver.delete_thread(task)
        folder = task_workspace(task)
        if folder.exists(): shutil.rmtree(folder)
        with db() as conn:
            conn.execute('DELETE FROM events WHERE task=?', (task,))
            conn.execute('DELETE FROM tasks WHERE id=?', (task,))


def start(task, prompt=None, decision=None):
    """Launch one background run per task and prevent concurrent runs on the same conversation."""
    with LOCK:
        get_task(task)
        if task in ACTIVE:raise ValueError('This task is already running.')
        ACTIVE.add(task)
    with db() as conn:conn.execute("UPDATE tasks SET status='running',error=NULL,updated=? WHERE id=?",(time.time(),task))
    threading.Thread(target=run_task,args=(task,prompt,decision),daemon=True).start()


def task_state(task):
    """Read messages, working files, planning state, activity, and pending approvals for the UI."""
    row=get_task(task)
    with saved_harness(row['role'],False,task) as graph:
        snapshot=graph.get_state(configuration(task))
    values=snapshot.values
    messages=[]
    for m in values.get('messages',[]):
        if m.type in {'human','ai'} and not getattr(m,'tool_calls',[]):
            content=text_content(m.content)
            if content:messages.append({'id':m.id,'role':'user' if m.type=='human' else 'assistant','text':content})
    recover_old_files(task_workspace(task), values.get('files', {}))
    files=working_files(task_workspace(task))
    with db() as conn:
        events=[{'seq':r['seq'],**json.loads(r['payload'])} for r in conn.execute('SELECT seq,payload FROM events WHERE task=? ORDER BY seq',(task,))]
    interrupts=[i.value for t in snapshot.tasks for i in t.interrupts]
    return {**row,'messages':messages,'files':files,'todos':values.get('todos',[]),'events':events,'interrupts':interrupts,'pending':bool(snapshot.next)}


def source(section):
    """Extract the actual configuration function or document for the code explorer."""
    title,file,symbol=SOURCE_MAP[section]
    content=(ROOT/file).read_text()
    if symbol:
        node=next(n for n in ast.walk(ast.parse(content)) if isinstance(n,ast.FunctionDef) and n.name==symbol)
        first=min([node.lineno]+[d.lineno for d in node.decorator_list])
        content='\n'.join(content.splitlines()[first-1:node.end_lineno])
    return {'title':title,'file':file,'symbol':symbol,'content':content}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        """Suppress request logging so conversation contents stay out of console output."""
        pass

    def respond(self,value,status=200):
        """Send a JSON response that the browser must not cache."""
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)

    def do_GET(self):
        """Serve product assets, task state, or source excerpts from the local workspace."""
        route=urlparse(self.path);path=route.path
        try:
            if path=='/api/config':
                model=os.environ['HARNESS_MODEL'];provider=model.split(':')[0]
                self.respond({'model':model,'ready':bool(os.getenv('ANTHROPIC_API_KEY' if provider=='anthropic' else 'OPENAI_API_KEY')),'roles':list(ACCESS),'stage':STAGE,'starters':stage_starters(),'sections':[{'id':k,'title':v[0]} for k,v in SOURCE_MAP.items()]});return
            if path=='/api/tasks':
                role=parse_qs(route.query).get('role',['sales'])[0]
                if role not in ACCESS:raise ValueError('Unknown profile')
                with db() as conn:rows=[dict(r) for r in conn.execute('SELECT * FROM tasks WHERE role=? ORDER BY updated DESC',(role,))]
                self.respond(rows);return
            if path.startswith('/api/tasks/'):
                self.respond(task_state(path.rsplit('/',1)[-1]));return
            if path.startswith('/api/source/'):
                self.respond(source(path.rsplit('/',1)[-1]));return
            if path=='/logo.svg':file=WEB/'assets/ns-work-logo.svg'
            else:
                file=(WEB/('index.html' if path=='/' else path.lstrip('/'))).resolve()
                if not file.is_relative_to(WEB.resolve()):raise ValueError('Not found')
            if not file.is_file():self.respond({'error':'Not found'},404);return
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream');self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(file.read_bytes())
        except (ValueError,KeyError):self.respond({'error':'Not found'},404)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.respond({'error':'Unable to load this task.'},500)

    def do_POST(self):
        """Validate local requests before creating, resuming, approving, or deleting tasks."""
        origin=self.headers.get('Origin')
        if self.headers.get('Host') not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}'} or origin and origin not in {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}:
            self.respond({'error':'Request origin not allowed'},403);return
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>24000:raise ValueError('Request is too large')
            data=json.loads(self.rfile.read(size))
            path=urlparse(self.path).path
            if path=='/api/tasks':
                role=data.get('role','sales');prompt=data.get('prompt','').strip()
                if role not in ACCESS or not prompt or len(prompt)>12000:raise ValueError('Choose a profile and enter a task.')
                task=uuid4().hex;now=time.time();title=(data.get('title') or prompt.split('\n')[0])[:64]
                with db() as conn:conn.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,NULL)',(task,role,title,'queued',now,now))
                start(task,prompt);self.respond({'id':task},202);return
            parts=path.strip('/').split('/')
            if len(parts)==4 and parts[:2]==['api','tasks']:
                task,action=parts[2:];row=get_task(task)
                if row['role']!=data.get('role'):raise ValueError('Use the task’s original profile.')
                if action=='delete':
                    delete_task(task,data.get('role'))
                    self.respond({'deleted':task});return
                elif action=='message':
                    prompt=data.get('prompt','').strip()
                    if not prompt or len(prompt)>12000:raise ValueError('Enter a message.')
                    if row['status'] in {'running','needs_review','interrupted'}:raise ValueError('Finish the pending run first.')
                    start(task,prompt)
                elif action=='review':
                    decision=data.get('decision')
                    if decision not in {'approve','reject'} or row['status']!='needs_review':raise ValueError('No matching review is pending.')
                    start(task,decision=decision)
                elif action=='resume':
                    if row['status'] not in {'error','interrupted'}:raise ValueError('This task cannot be resumed.')
                    start(task)
                else:raise ValueError('Unknown action')
                self.respond({'id':task},202);return
            self.respond({'error':'Not found'},404)
        except (ValueError,KeyError,json.JSONDecodeError) as error:self.respond({'error':str(error)},400)
        except Exception:self.respond({'error':'Unable to start this task.'},500)


if __name__=='__main__':
    init_db()
    print(f'NS Work ready at http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
