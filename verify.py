"""Verify the shipped harness with scripted graphs and temporary storage, without provider calls."""
import sys, json, tempfile, shutil, contextlib, io, sqlite3, os
from pathlib import Path
APP=Path(__file__).resolve().parent
ROOT=APP
os.environ['OPENAI_API_KEY']='offline-configuration-check'
os.environ['LANGSMITH_TRACING']='false'
os.environ['LANGCHAIN_TRACING_V2']='false'
sys.path.insert(0,str(APP))
from runtime import PreviewModel, make_model
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr
from company import Company
from stages import build_stage, STAGES
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

class Scripted(PreviewModel):
    responses:list
    _index:int=PrivateAttr(default=0)
    def _generate(self,messages,**kwargs):
        if self._index>=len(self.responses):raise AssertionError('Unexpected model call')
        msg=self.responses[self._index];self._index+=1
        return ChatResult(generations=[ChatGeneration(message=msg)])

def call(name,**args):
    return AIMessage(content='',tool_calls=[{'name':name,'args':args,'id':name+'-test','type':'tool_call'}])
def inp(text='Check the configuration'):return {'messages':[{'role':'user','content':text}]}
def done():return AIMessage(content='Complete.')
report={}
with tempfile.TemporaryDirectory(prefix='nswork-verify-') as tmp:
    tmp=Path(tmp)
    for name in ('company','skills'):shutil.copytree(APP/name,tmp/name)
    (tmp/'.runtime').mkdir()
    namespace={}
    cells=json.loads((APP/'00_NS_Work.ipynb').read_text())['cells']
    ran=0;ui_stages=[]
    for i,c in enumerate(cells):
        if c['cell_type']!='code':continue
        src=''.join(c['source'])
        assert 'input(' not in src
        if 'update_ui(' in src:
            import re
            ui_stages.extend(re.findall(r'update_ui\("(\w+)"\)',src));continue
        with contextlib.redirect_stdout(io.StringIO()):exec(compile(src,f'notebook-cell-{i}','exec'),namespace)
        if i==2:namespace['ROOT']=tmp
        ran+=1
    namespace['connection'].close()
    report['notebook']={'configuration_cells_executed':ran,'ui_sequence':ui_stages,'interactive_input':False}
    assert ui_stages==list(STAGES)
    company=Company((tmp/'records.sqlite').resolve())
    for stage in STAGES:
        for role in ('sales','engineering','finance'):
            build_stage(stage,PreviewModel(),company,role,InMemorySaver(),workspace=tmp/f'{stage}-{role}')
    report['stage_role_compilation']=15
    assert 'Access denied' in str(company.all_tools_for('engineering')['revenue_summary'].invoke({'quarter':'2026-Q3'}))
    assert 'revenue_summary' not in [t.name for t in company.tools_for('engineering')]
    assert '480000' in str(company.all_tools_for('finance')['revenue_summary'].invoke({'quarter':'2026-Q3'}))
    report['role_permissions']='passed'
    model=Scripted(responses=[call('read_file',file_path='/skills/company/write-proposal/SKILL.md'),call('customer_brief',customer='Acme'),call('write_file',file_path='/work/proposal.md',content='Customer goal: Acme reporting\nPricing pending.'),done()])
    db=tmp/'saved.sqlite';workspace=tmp/'saved-work';cfg={'configurable':{'thread_id':'recording-check'},'recursion_limit':100}
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph=build_stage('persistence',model,company,'sales',saver,workspace=workspace)
        result=graph.invoke(inp('Prepare proposal; Priya confirms Friday.'),cfg)
        assert (workspace/'work/proposal.md').exists()
        assert any(m.name=='customer_brief' for m in result['messages'] if isinstance(m,ToolMessage))
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph=build_stage('persistence',Scripted(responses=[done()]),company,'sales',saver,workspace=workspace)
        result=graph.invoke(inp('Continue.'),cfg)
        assert any('Priya' in str(m.content) for m in result['messages'])
    report['skills_tools_files_checkpoint_followup']='passed'
    before=(workspace/'company/AGENTS.md').read_text()
    model=Scripted(responses=[call('edit_file',file_path='/company/AGENTS.md',old_string=before.splitlines()[0],new_string='Changed'),done()])
    graph=build_stage('persistence',model,company,'sales',InMemorySaver(),workspace=workspace)
    result=graph.invoke(inp(),{'configurable':{'thread_id':'protected'}})
    assert (workspace/'company/AGENTS.md').read_text()==before
    assert any('denied' in str(m.content).lower() for m in result['messages'] if isinstance(m,ToolMessage))
    report['protected_company_file']='passed'
    parent=Scripted(responses=[call('task',subagent_type='proposal-reviewer',description='Look up Acme and review commitments.'),done()])
    reviewer=Scripted(responses=[call('customer_brief',customer='Acme'),AIMessage(content='C-101: pricing and timing need confirmation.')])
    graph=build_stage('actions',parent,company,'sales',InMemorySaver(),reviewer,workspace=tmp/'reviewer')
    result=graph.invoke(inp(),{'configurable':{'thread_id':'reviewer'}})
    assert any(m.name=='task' and 'C-101' in str(m.content) for m in result['messages'] if isinstance(m,ToolMessage))
    report['subagent_delegation']='passed'
    model=Scripted(responses=[call('send_proposal',customer='Acme',body='Customer goal\nReporting\nProposed scope\nConfirm\nAssumptions\nPricing pending\nNext steps\nReview'),done()])
    graph=build_stage('boundaries',model,company,'sales',InMemorySaver(),workspace=tmp/'approval')
    cfg={'configurable':{'thread_id':'approval'}}
    result=graph.invoke(inp(),cfg);assert result.get('__interrupt__')
    graph.invoke(Command(resume={'decisions':[{'type':'reject'}]}),cfg)
    assert company.query('SELECT * FROM outbox')==[]
    report['approval_pause_and_rejection']='passed'
print(json.dumps(report,indent=2))
