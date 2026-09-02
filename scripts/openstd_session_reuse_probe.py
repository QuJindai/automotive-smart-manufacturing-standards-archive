import json, os, re, subprocess, time
from pathlib import Path
import requests

BASE='https://c.gb688.cn/bzgk/gb'
STD1=('GB15082-2008','8676EBC34F75CFFDF7EA4BC12517A007')
STD2=('GB4599-2024','D88797E512723F8CBF170A20E81F27AD')
BRANCH=os.environ.get('GITHUB_REF_NAME','test/openstd-min-loop-20260902')
CAPTCHA=Path('state/openstd-session-reuse/captcha.png')
RESULT=Path('state/openstd-session-reuse/result.json')
ANSWER='ops/openstd_captcha_answer.txt'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133 Safari/537.36'

def sh(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check)

def git_commit(path, msg):
    sh('git','config','user.name','github-actions[bot]')
    sh('git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    sh('git','add',str(path))
    c=sh('git','commit','-m',msg,check=False)
    if c.returncode==0:
        sh('git','push','origin',f'HEAD:{BRANCH}')

def fetch_answer(timeout=420):
    deadline=time.time()+timeout
    while time.time()<deadline:
        sh('git','fetch','origin',BRANCH,check=False)
        r=sh('git','show',f'origin/{BRANCH}:{ANSWER}',check=False)
        if r.returncode==0:
            code=r.stdout.strip()
            if code and code.upper() not in {'PENDING','USED'} and re.fullmatch(r'[A-Za-z0-9]{3,8}',code):
                return code
        time.sleep(5)
    raise TimeoutError('captcha answer timeout')

def probe_pdf(sess, name, hcno):
    ref=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={hcno}'
    with sess.get(f'{BASE}/viewGb',params={'hcno':hcno},headers={'Referer':ref},stream=True,timeout=40) as r:
        first=b''
        for chunk in r.iter_content(8192):
            if chunk:
                first=chunk
                break
        cd=r.headers.get('Content-Disposition','')
        ct=r.headers.get('Content-Type','')
        is_pdf=(first.startswith(b'%PDF-') or '.pdf' in cd.lower() or 'application/pdf' in ct.lower())
        return {'name':name,'hcno':hcno,'status_code':r.status_code,'content_type':ct,'content_disposition':cd[:200],'content_length':r.headers.get('Content-Length'),'first_bytes_hex':first[:8].hex(),'is_pdf':is_pdf}

def write_result(obj):
    RESULT.parent.mkdir(parents=True,exist_ok=True)
    sh('git','pull','--rebase','origin',BRANCH,check=False)
    RESULT.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    git_commit(RESULT,'test: persist OpenSTD session reuse result')

sess=requests.Session()
sess.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
try:
    ref1=f'https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={STD1[1]}'
    r=sess.get(f'{BASE}/gc',params={'_':int(time.time()*1000)},headers={'Referer':ref1},timeout=30)
    r.raise_for_status()
    CAPTCHA.parent.mkdir(parents=True,exist_ok=True)
    CAPTCHA.write_bytes(r.content)
    git_commit(CAPTCHA,'test: publish OpenSTD captcha for same-session probe')
    code=fetch_answer()
    vr=sess.post(f'{BASE}/verifyCode',data={'verifyCode':code,'agreeIECTips':'true'},headers={'Referer':ref1},timeout=30)
    verified=(vr.status_code==200 and vr.text.strip()=='success')
    result={'captcha_http_status':r.status_code,'captcha_bytes':len(r.content),'verify_http_status':vr.status_code,'verify_response':vr.text.strip()[:80],'verified':verified}
    if not verified:
        result['verdict']='CAPTCHA_REJECTED'
        write_result(result)
        raise SystemExit(2)
    first=probe_pdf(sess,*STD1)
    second=probe_pdf(sess,*STD2)
    result.update({'first':first,'second':second,'verdict':'SESSION_REUSABLE' if first['is_pdf'] and second['is_pdf'] else ('SECOND_REQUIRES_NEW_CHALLENGE' if first['is_pdf'] and not second['is_pdf'] else 'DOWNLOAD_NOT_CONFIRMED')})
    write_result(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
finally:
    sess.close()
