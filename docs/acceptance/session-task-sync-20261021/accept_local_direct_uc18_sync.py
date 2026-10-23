"""Explicitly authorized Mac MCP management verification, no SUT execution.

The released stock stdio/daemon uses its default strict public HTTPS transport.
Only hypertest_get_task and the original-key hypertest_sync_task are called.
"""
from __future__ import annotations
import argparse,asyncio,hashlib,json,os,shlex,sqlite3,subprocess,sys,tomllib,traceback,ssl
from collections import Counter
from datetime import datetime,timezone
from importlib.metadata import distribution,version
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from hypertest.interactive_client.service import validate_sync_receipt,validate_task_page
from hypertest.api.task_schemas import SessionTaskSync

ROOT=Path('/Users/zhangliangchen/PycharmProjects/hypertest-one/docs/acceptance/session-task-sync-20261021')
OUT=ROOT/'local-direct'
PROJECT='01a15de2-205e-76e6-bfad-7468a724f886'
TASK='01a15de5-9aca-76b4-bd57-c673112f2e92'
KEY='uc18-real-session-current-20261021-v1'
OWNER='interactive:01a15de2-20b7-702b-9bdd-32f27d89fb57'
WHEEL='d7e7bfdbb5a5a25bab343bf695185cc9587c745605c667ba28a9d23d336a6dd3'
BUNDLE='278f5003a287746b5abba528eed1f04f2d1f31122f0b8fea5e39c37601662f3c'

def now():return datetime.now(timezone.utc).isoformat()
def save(name,data):
 p=OUT/name;temp=p.with_name('.'+p.name+'.tmp')
 fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
 os.replace(temp,p)
def journal(config):
 p=Path(config['state_dir'])/'client.sqlite3'
 if not p.exists():return {'file_exists':False,'intent':None}
 db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
 try:
  row=db.execute('SELECT state,digest,payload,result FROM intents WHERE kind=? AND key=?',('session-task:'+PROJECT,KEY)).fetchone()
  return {'file_exists':True,'intent':None if row is None else {'state':row[0],'digest':row[1],'payload':json.loads(row[2]),'result':json.loads(row[3]) if row[3] else None}}
 finally:db.close()
def processes(config_path):
 rows=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True)
 found=[]
 for row in rows.splitlines():
  try:pid,ppid,command=row.strip().split(None,2);args=shlex.split(command)
  except ValueError:continue
  if 'hypertest.interactive_client' not in args or '--config' not in args:continue
  if Path(args[args.index('--config')+1])!=config_path:continue
  item={'pid':int(pid),'ppid':int(ppid),'argv':args}
  if 'daemon' in args:
   result=subprocess.run(['/usr/sbin/lsof','-nP','-a','-p',pid,'-iTCP'],capture_output=True,text=True)
   item['tcp_connections']=result.stdout.strip().splitlines()
  found.append(item)
 return found

def ancestors():
 result=[];pid=os.getpid()
 for _ in range(12):
  row=subprocess.run(['ps','-p',str(pid),'-o','pid=,ppid=,comm='],capture_output=True,text=True).stdout.strip()
  if not row:break
  actual,parent,comm=row.split(None,2);result.append({'pid':int(actual),'ppid':int(parent),'comm':comm})
  if int(parent)<=1:break
  pid=int(parent)
 return result

async def run(phase):
 OUT.mkdir(mode=0o700,exist_ok=True);OUT.chmod(0o700)
 assert sys.flags.isolated==1 and version('hypertest-one')=='0.2.0'
 direct=json.loads(distribution('hypertest-one').read_text('direct_url.json'))
 assert direct['archive_info']['hashes']['sha256']==WHEEL
 assert not direct.get('dir_info',{}).get('editable',False)
 profile=tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['hypertest_management']
 assert profile['enabled_tools']==['hypertest_sync_task','hypertest_get_task']
 args=profile['args'];config_path=Path(args[args.index('--config')+1]);config=json.loads(config_path.read_text())
 assert config['api_url']=='https://155.138.206.106:8080/api/v1'
 assert config['allow_insecure_loopback'] is False and config['ca_file']
 assert config['host_adapter']=={'kind':'unsupported'}
 assert sys.platform=='darwin'
 original_ca=Path.home()/'.local/share/hypertest/session-sync-dev-20261021/server-trust/ingress-ca.crt'
 configured_ca=Path(config['ca_file']).resolve(strict=True)
 ca_fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(configured_ca.read_text())).hexdigest()
 assert ca_fingerprint==hashlib.sha256(ssl.PEM_cert_to_DER_cert(original_ca.read_text())).hexdigest()=='9b3cf1b792fc14bec884034757cb7dda95ab8cba0e946cd236cb9a531a1d67e6'
 assert '--autostart' in args and args[:3]==['-I','-m','hypertest.interactive_client']
 raw=(ROOT/'UC18_REMOTE_SOURCE_BUNDLE_V2.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==BUNDLE
 bundle=json.loads(raw);identity={'project_id':PROJECT,'provider':bundle['task']['provider'],'session_id':bundle['task']['session_id']}
 frozen_payload={**bundle['task'],**identity,'cases':bundle['cases'],'reports':bundle['reports'],'idempotency_key':KEY,'expected_version':0}
 before_path=Path.home()/'.local/share/hypertest/session-sync-dev-20261021/local-direct-mcp-20261021/before.json'
 server_before=json.loads(before_path.read_text())
 receipt_row=next(row for row in server_before['receipts'] if row['idempotency_key']==KEY)
 payload=receipt_row['request_payload']
 assert payload==SessionTaskSync.model_validate(frozen_payload).model_dump(mode='json'), 'Original body differs from frozen source; no sync allowed'
 digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
 assert digest==receipt_row['input_digest']=='a3be2c5222fb7ac223297bc25f9907da60d1f06de2194d9a1453dd508395d10f'
 observation={'original_body_source':str(before_path)+' ->receipts[].request_payload','phase':phase,'started_at':now(),'invocation':'Local Codex tool launches official MCP SDK, not native tool hotload','official_version':version('hypertest-one'),'sdk_version':version('mcp'),'wheel_sha256':WHEEL,'sdk_pid':os.getpid(),'sdk_executable':sys.executable,'stock_profile_command':profile['command'],'stock_profile_args':args,'stock_profile_cwd':profile['cwd'],'api_url':config['api_url'],'ca_file':config['ca_file'],'default_transport':True,'TLS_verification':True,'HTTP_fallback':False,'api_transport_public_https_tcp':True,'remote_TLS_UDS':False,'SSH_or_forwarding':False,'local_stock_stdio_daemon_UDS':True,'sys_platform':sys.platform,'uid':os.getuid(),'sdk_ppid':os.getppid(),'sdk_ancestors':ancestors(),'ca_original_file':str(original_ca),'ca_resolved_file':str(configured_ca),'ca_der_sha256':ca_fingerprint,'source_bundle_sha256':BUNDLE,'source_session_id':identity['session_id'],'request_digest':digest,'journal_before':journal(config),'management_tools_called':[],'sut_tests_executed':0,'native_tools_hotload_verified':False}
 save(phase+'-progress.json',observation)
 err_path=OUT/(phase+'-stdio-stderr.log')
 if err_path.exists():raise RuntimeError('Preserve existing attempt log; use original GET reconciliation')
 fd=os.open(err_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as errlog:
  params=StdioServerParameters(command=profile['command'],args=args,cwd=profile['cwd'],env=profile.get('env'))
  async with stdio_client(params,errlog=errlog) as (reader,writer):
   async with ClientSession(reader,writer) as session:
    init=await session.initialize();observation['server_info']=init.serverInfo.model_dump(mode='json')
    tools=await session.list_tools();observation['advertised_tools']=sorted(t.name for t in tools.tools)
    async def call(name,arguments,label):
     assert name in {'hypertest_get_task','hypertest_sync_task'}
     observation['management_tools_called'].append({'tool':name,'label':label})
     save(phase+'-progress.json',observation)
     result=await session.call_tool(name,arguments)
     if result.isError or not isinstance(result.structuredContent,dict):
      save(label+'-error.json',{'isError':result.isError,'content':[x.model_dump(mode='json') for x in result.content]})
      raise RuntimeError('Management call failed; preserve original key and query only')
     save(label+'.json',result.structuredContent)
     return result.structuredContent
    async def read(label):
     receipt=await call('hypertest_get_task',{'project_id':PROJECT,'idempotency_key':KEY},label+'-receipt')
     validate_sync_receipt(receipt,KEY,0,TASK,identity);assert receipt['version']==1
     pieces=[];offset=0;total=None
     while True:
      request={**identity,'version':1,'offset':offset,'limit':24000}
      page=await call('hypertest_get_task',request,label+'-page-'+str(offset))
      validate_task_page(page,request);assert page['task_id']==TASK and page['version']==1
      if total is None:total=page['total_chars']
      assert page['total_chars']==total
      pieces.append(page['content'])
      if page['complete']:break
      offset=page['next_offset']
     text=''.join(pieces);assert len(text)==total
     doc=json.loads(text);save(label+'-full-task.json',doc)
     task=doc['task'];assert task['id']==TASK and task['version']==1 and task['owner_actor_ref']==OWNER
     assert all(task[k]==v for k,v in {**bundle['task'],**identity}.items())
     assert task['source']=='AGENT_REPORTED' and len(doc['cases'])==15 and len(doc['reports'])==2
     for kind in ('cases','reports'):
      for expected in bundle[kind]:
       actual=next(x for x in doc[kind] if x['key']==expected['key'])
       assert all(actual[k]==v for k,v in expected.items())
       assert actual['source']=='AGENT_REPORTED'
       if kind=='reports':assert actual['markdown'].encode()==expected['markdown'].encode()
     return receipt,{'pages':len(pieces),'chars':total,'task_fields_exact':True,'all_case_fields_exact':True,'all_report_fields_exact':True,'report_markdown_bytes_exact':True,'case_results':dict(Counter(x['reported_result'] for x in doc['cases'])),'task_created_at':task['created_at'],'task_last_synced_at':task['last_synced_at']}
    original,readback=await read(phase+'-before')
    observation['original_receipt']=original;observation['before_readback']=readback
    observation['process_chain_before_sync']=processes(config_path)
    observation['journal_after_read']=journal(config)
    save(phase+'-progress.json',observation)
    if phase=='sync':
     # Explicit reviewed idempotent replay of an already ACKED server operation.
     # Never automatically retry this call after process death/uncertain response.
     guard=OUT/'original-key-idempotent-intent.json'
     if guard.exists():
      observation['sync_call_sent']=False
      observation['query_only_reason']='Prior external intent exists; never replay after uncertainty'
     else:
      save(guard.name,{'state':'SENT_OR_UNKNOWN','project_id':PROJECT,'task_id':TASK,'key':KEY,'expected_version':0,'request_digest':digest,'sent_at':now()})
      observation['sync_call_sent']=True
      result=await call('hypertest_sync_task',payload,'sync-original-key-result')
      validate_sync_receipt(result,KEY,0,TASK,identity);assert result==original
      save(guard.name,{'state':'ACKED','project_id':PROJECT,'task_id':TASK,'key':KEY,'request_digest':digest,'receipt':result,'checked_at':now()})
      observation['sync_result']=result
     receipt,after=await read('sync-after')
     assert receipt==original and after==readback
     assert json.loads((OUT/'sync-before-full-task.json').read_text())==json.loads((OUT/'sync-after-full-task.json').read_text())
     observation['after_readback']=after;observation['task_and_revision_state_unchanged']=True
    observation['process_chain']=processes(config_path)
    observation['journal_after']=journal(config)
 observation['completed_at']=now();observation['status']='PASS'
 save(phase+'-observations.json',observation)
 print(json.dumps({k:observation[k] for k in ('phase','status','original_receipt','before_readback','sut_tests_executed','native_tools_hotload_verified')},ensure_ascii=False))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['read','sync'],required=True);options=parser.parse_args()
 try:asyncio.run(run(options.phase))
 except BaseException as exc:
  failure={'phase':options.phase,'exception':type(exc).__name__,'message':str(exc),'at':now(),'automatic_retry':False,'next_action':'Original key GET only; do not alter transport, token, key or reports'}
  save(options.phase+'-failure.json',failure)
  print(json.dumps(failure,ensure_ascii=False));sys.exit(1)
