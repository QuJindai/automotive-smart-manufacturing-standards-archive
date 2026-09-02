import json, os, re, subprocess, time
from pathlib import Path
import requests
BASE='https://c.gb688.cn/bzgk/gb'
STD1=('GB15082-2008','8676EBC34F75CFFDF7EA4BC12517A007')
STD2=('GB4599-2024','D88797E512723F8CBF170A20E81F27AD')
BRANCH=os.environ.get('GITHUB_REF_NAME','test/openstd-session-reuse-clean-20260902')
CAPTCHA=Path('state/openstd-session-reuse/captcha.png')
RESULT=Path('state/openstd-session-reuse/result.json')
ANSWER='ops/openstd_captcha_answer.txt'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133 Safari/537.36'
def sh(*args,check=True): return subprocess.run(args,text=True,capture_output=True,check=check)
def sync_push(path,msg):
 sh('git','config','user.name','github-actions[bot]'); sh('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
 sh('git','pull','--rebase','origin',BRANCH,check=False); sh('git','add',str(path)); c=sh('git','commit','-m',msg,check=False)
 if c.returncode==0: sh('git','push','origin',f'HEAD:{BRANCH}')
def wait_answer(timeout=420):
 end=time.time()+timeout
 while time.time()<end:
  sh('git','fetch','origin',BRANCH,check=False); r=sh('git','show',f'origin/{BRANCH}:{ANSWER}',check=False)
  if r.returncode==0:
   code=r.stdout.strip()
   if code and code.upper() not in {'PENDING','USED'} and re.fullmatch(r'[A-Za-z0-9]{3,8}',code): return code
  time.sleep(5)
 raise TimeoutError('captcha answer timeout')
def probe(sess,name,hcno):
 ref=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={hcno}'
 with sess.get(f'{BASE}/viewGb',params={'hcno':hcno},headers={'Referer':ref},stream=True,timeout=40) as r:
  first=next((c for c in r.iter_content(8192) if c),b''); cd=r.headers.get('Content-Disposition',''); ct=r.headers.get('Content-Type','')
  return {'name':name,'status':r.status_code,'content_type':ct,'content_disposition':cd[:160],'content_length':r.headers.get('Content-Length'),'first_hex':first[:8].hex(),'is_pdf':first.startswith(b'%PDF-') or '.pdf' in cd.lower() or 'application/pdf' in ct.lower()}
def save(obj):
 RESULT.parent.mkdir(parents=True,exist_ok=True); RESULT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8'); sync_push(RESULT,'test: persist OpenSTD session reuse result')
s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
try:
 ref=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={STD1[1]}'
 r=s.get(f'{BASE}/gc',params={'_':int(time.time()*1000)},headers={'Referer':ref},timeout=30); r.raise_for_status(); CAPTCHA.parent.mkdir(parents=True,exist_ok=True); CAPTCHA.write_bytes(r.content); sync_push(CAPTCHA,'test: publish OpenSTD captcha challenge')
 code=wait_answer(); v=s.post(f'{BASE}/verifyCode',data={'verifyCode':code,'agreeIECTips':'true'},headers={'Referer':ref},timeout=30); ok=v.status_code==200 and v.text.strip()=='success'
 out={'captcha_bytes':len(r.content),'verify_status':v.status_code,'verify_response':v.text.strip()[:80],'verified':ok}
 if not ok: out['verdict']='CAPTCHA_REJECTED'; save(out); raise SystemExit(2)
 a=probe(s,*STD1); b=probe(s,*STD2); out.update({'first':a,'second':b,'verdict':'SESSION_REUSABLE' if a['is_pdf'] and b['is_pdf'] else ('SECOND_REQUIRES_NEW_CHALLENGE' if a['is_pdf'] and not b['is_pdf'] else 'DOWNLOAD_NOT_CONFIRMED')}); save(out); print(json.dumps(out,ensure_ascii=False,indent=2))
finally: s.close()
