import json,os,socket,subprocess,tempfile,time,signal,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone
root=Path('/tmp/tradecase-p7-web-access')
output=Path('docs/evidence/P7/web-access-independent.json')
start=time.monotonic(); result={'upstream_sha':'d173a75978ceb2c63fa0b27f7408cd2bf7fe4310','source_checkout':'independent temporary upstream checkout, not product source copy','captured_at':datetime.now(timezone.utc).isoformat(),'site':'https://quotes.toscrape.com/js/','calls':[],'login_used':False,'user_profile_used':False,'license':'README/frontmatter declares MIT; complete LICENSE missing; redistribution not approved'}
def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=body.encode() if body is not None else None,method='POST' if body is not None else 'GET')
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=22) as r:
  value=json.loads(r.read().decode())
 result['calls'].append({'path':path.split('?')[0],'status':r.status,'response':value});return value
chrome=proxy=None
with tempfile.TemporaryDirectory(prefix='tradecase-p7-browser-') as tmp:
 profile=Path(tmp)/'profile';profile.mkdir()
 s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
 env=os.environ.copy();env['CDP_PROXY_PORT']=str(port)
 try:
  chrome=subprocess.Popen(['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome','--headless=new','--remote-debugging-port=0','--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--disable-component-update','about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  for _ in range(100):
   if (profile/'DevToolsActivePort').exists() and (profile/'Local State').exists(): break
   if chrome.poll() is not None: raise RuntimeError('isolated Chrome exited before DevTools port appeared')
   time.sleep(.1)
  else: raise TimeoutError('isolated Chrome startup timeout')
  sandbox = '(version 1)(allow default)(deny file-read* (subpath ' + json.dumps(str(Path.home() / '.web-access')) + '))'
  proxy=subprocess.Popen(['/usr/bin/sandbox-exec','-p',sandbox,'node',str(root/'scripts/cdp-proxy.mjs'),'--browser',str(profile)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  for _ in range(100):
   try:
    api('/health');break
   except (OSError,urllib.error.URLError):
    if proxy.poll() is not None: raise RuntimeError('upstream proxy exited during startup')
    time.sleep(.1)
  else: raise TimeoutError('upstream proxy startup timeout')
  target=api('/new','https://quotes.toscrape.com/js/')['targetId']
  data=api('/eval?target='+target,'JSON.stringify({url:location.href,title:document.title,quotes:document.querySelectorAll(".quote").length,authors:document.querySelectorAll(".quote .author").length})')
  api('/close?target='+target)
  api('/health')
  result['status']='tested_live';result['interpretation']='Upstream proxy and isolated Chrome were exercised; evaluate returned response to confirm dynamic content.'
 except Exception as e:
  result['status']='blocked';result['error_type']=type(e).__name__;result['error']=str(e)
 finally:
  for p in (proxy,chrome):
   if p is not None and p.poll() is None:
    try: os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=5)
    except Exception:
     try: os.killpg(p.pid,signal.SIGKILL)
     except ProcessLookupError: pass
  result['processes_stopped']=all(p is None or p.poll() is not None for p in (proxy,chrome))
result['elapsed_seconds']=round(time.monotonic()-start,3)
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':result['status'],'calls':result['calls'],'error':result.get('error'),'processes_stopped':result['processes_stopped'],'elapsed_seconds':result['elapsed_seconds']},ensure_ascii=False))
