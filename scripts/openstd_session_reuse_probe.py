import base64, json, os, re, time
from pathlib import Path
import requests

BASE='https://c.gb688.cn/bzgk/gb'
STD1=('GB15082-2008','8676EBC34F75CFFDF7EA4BC12517A007')
STD2=('GB4599-2024','D88797E512723F8CBF170A20E81F27AD')
BRANCH=os.environ['GITHUB_REF_NAME']; REPO=os.environ['GITHUB_REPOSITORY']; RUN_ID=os.environ['GITHUB_RUN_ID']; TOKEN=os.environ['GITHUB_TOKEN']
ANSWER='ops/openstd_captcha_answer.txt'
CAPTCHA_PATH=f'state/openstd-session-reuse/captcha-{RUN_ID}.png'
RESULT_PATH=f'state/openstd-session-reuse/result-{RUN_ID}.json'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133 Safari/537.36'
GH=f'https://api.github.com/repos/{REPO}/contents'
GH_HEADERS={'Authorization':f'Bearer {TOKEN}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}

def gh_get(path):
    return requests.get(f'{GH}/{path}',headers=GH_HEADERS,params={'ref':BRANCH},timeout=20)

def gh_put(path,data:bytes,message):
    current=gh_get(path); payload={'message':message,'content':base64.b64encode(data).decode(),'branch':BRANCH}
    if current.status_code==200: payload['sha']=current.json()['sha']
    r=requests.put(f'{GH}/{path}',headers=GH_HEADERS,json=payload,timeout=30); r.raise_for_status(); return r.json()

def wait_answer(timeout=420):
    end=time.time()+timeout
    while time.time()<end:
        r=gh_get(ANSWER)
        if r.status_code==200:
            code=base64.b64decode(r.json()['content']).decode().strip()
            if code and code.upper() not in {'PENDING','USED'} and re.fullmatch(r'[A-Za-z0-9]{3,8}',code): return code
        time.sleep(4)
    raise TimeoutError('captcha answer timeout')

def probe(sess,name,hcno):
    ref=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={hcno}'
    with sess.get(f'{BASE}/viewGb',params={'hcno':hcno},headers={'Referer':ref},stream=True,timeout=45) as r:
        first=next((c for c in r.iter_content(8192) if c),b''); cd=r.headers.get('Content-Disposition',''); ct=r.headers.get('Content-Type','')
        return {'name':name,'hcno':hcno,'status':r.status_code,'content_type':ct,'content_disposition':cd[:160],'content_length':r.headers.get('Content-Length'),'first_hex':first[:8].hex(),'is_pdf':first.startswith(b'%PDF-') or '.pdf' in cd.lower() or 'application/pdf' in ct.lower()}

def persist(obj):
    gh_put(RESULT_PATH,json.dumps(obj,ensure_ascii=False,indent=2).encode(),'test: persist OpenSTD session reuse result')

s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
try:
    ref=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={STD1[1]}'
    cap=s.get(f'{BASE}/gc',params={'_':int(time.time()*1000)},headers={'Referer':ref},timeout=30); cap.raise_for_status()
    gh_put(CAPTCHA_PATH,cap.content,'test: publish OpenSTD captcha challenge')
    print(f'CAPTCHA_PATH={CAPTCHA_PATH}',flush=True)
    code=wait_answer()
    v=s.post(f'{BASE}/verifyCode',data={'verifyCode':code,'agreeIECTips':'true'},headers={'Referer':ref},timeout=30)
    ok=v.status_code==200 and v.text.strip()=='success'
    out={'run_id':RUN_ID,'captcha_bytes':len(cap.content),'verify_status':v.status_code,'verify_response':v.text.strip()[:80],'verified':ok}
    if not ok:
        out['verdict']='CAPTCHA_REJECTED'; persist(out); raise SystemExit(2)
    first=probe(s,*STD1); second=probe(s,*STD2)
    out.update({'first':first,'second':second,'verdict':'SESSION_REUSABLE' if first['is_pdf'] and second['is_pdf'] else ('SECOND_REQUIRES_NEW_CHALLENGE' if first['is_pdf'] and not second['is_pdf'] else 'DOWNLOAD_NOT_CONFIRMED')})
    persist(out); print(json.dumps(out,ensure_ascii=False,indent=2))
finally:
    s.close()
