from __future__ import annotations

import base64
import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from .aasx import build_aasx, validate_aasx
from .api import TransportError, request_json
from .evidence import artifact_entry, assertion, now_iso, test_result
from .jws import verify_compact
from .mock_server import ReferenceServer
from .rules import check_asset_kind, check_asset_identifier, check_capabilities, check_required_semantics
from .sample import load_sample
from .semantic import check_iec61360, check_languages, check_units, check_unit_resolvability


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _result_from_check(test_id: str, check, linked: list[str], artifact: dict, level='C1') -> dict:
    return test_result(test_id,level,check.passed,linked,[assertion(check.check_id,check.passed,True,check.observed,check.message)],[artifact])


def _api_assert(test_id: str, passed: bool, linked: list[str], expected, observed, artifact: dict, message: str, level='C1') -> dict:
    return test_result(test_id,level,passed,linked,[assertion(test_id+'-assertion',passed,expected,observed,message)],[artifact])


def _tamper_jws(token: str) -> str:
    head,payload,sig=token.split('.')
    raw=base64.urlsafe_b64decode(payload + '='*(-len(payload)%4))
    if raw:
        raw=raw[:-1]+bytes([raw[-1]^1])
    changed=base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    return '.'.join([head,changed,sig])


def run_reference(example_dir: str | Path, output_dir: str | Path, profile_dir: str | Path | None=None, external_base_url: str | None=None) -> dict:
    example_dir=Path(example_dir)
    output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    artifacts_dir=output_dir/'artifacts'; artifacts_dir.mkdir(exist_ok=True)
    profile_dir=Path(profile_dir) if profile_dir else Path(__file__).resolve().parents[1]/'profile'
    profile=_load(profile_dir/'p-aas-profile.v1.json')
    tests=_load(profile_dir/'p-aas-test-cases.v1.json')
    test_map={x['id']:x for x in tests['cases']}
    rules=profile['rules']
    sample=load_sample(example_dir)
    started=now_iso()

    known=set(test_map)
    t001_ok=all(r.get('source') and r.get('machine_checks') and r.get('test_ids') and set(r['test_ids']).issubset(known) for r in rules)
    structural={
        'AAS-T001': {'passed':t001_ok,'message':'all P-AAS rules have source, machine checks and known TestIDs','observed':{'rules':len(rules),'tests':len(known)}},
        'AAS-T002': asdict(check_asset_kind(sample)),
        'AAS-T003': asdict(check_asset_identifier(sample)),
        'AAS-T004': asdict(check_required_semantics(sample)),
        'AAS-T005': asdict(check_iec61360(sample)),
        'AAS-T006': asdict(check_languages(sample,set(profile['parameters']['required_languages']))),
        'AAS-T007': asdict(check_units(sample)),
        'AAS-T008': asdict(check_unit_resolvability(sample)),
        'AAS-T009': asdict(check_capabilities(sample,set(profile['parameters']['required_capabilities']))),
    }
    structural_path=artifacts_dir/'structural-checks.json'
    structural_path.write_text(json.dumps(structural,ensure_ascii=False,indent=2),encoding='utf-8')
    structural_art=artifact_entry(output_dir,structural_path,'ART-STRUCTURAL','application/json')
    results=[]
    for i in range(1,10):
        tid=f'AAS-T{i:03d}'; row=structural[tid]
        if tid=='AAS-T001':
            results.append(_api_assert(tid,row['passed'],test_map[tid]['linked_rule_ids'],'traceable P-AAS rules',row['observed'],structural_art,row['message']))
        else:
            class Obj: pass
            obj=Obj(); obj.check_id=row['check_id']; obj.passed=row['passed']; obj.message=row['message']; obj.observed=row['observed']
            results.append(_result_from_check(tid,obj,test_map[tid]['linked_rule_ids'],structural_art))

    secret=b'synthetic-reference-secret'
    running=None
    base_url=external_base_url
    api_trace=[]
    try:
        if not base_url:
            running=ReferenceServer(sample,secret).start(); base_url=running.base_url
        def trace(name,res):
            api_trace.append({'operation':name,'status':res.status,'json':res.json}); return res
        good=trace('query-valid',request_json('POST',base_url+'/query',{'idShort':'Status'}))
        bad=trace('query-invalid',request_json('POST',base_url+'/query',{'unsupported':'x'}))
        t010=good.status==200 and good.json and good.json.get('results') and good.json['results'][0].get('idShort')=='Status' and bad.status==400

        aas=trace('get-aas',request_json('GET',base_url+'/shells/'+quote(sample.aas_id,safe='')))
        t011=aas.status==200 and aas.json and aas.json.get('id')==sample.aas_id
        smid=sample.submodel_ids['Status']
        sm=trace('get-submodel',request_json('GET',base_url+'/submodels/'+quote(smid,safe='')))
        t012=sm.status==200 and sm.json and sm.json.get('id')==smid
        unauth=trace('protected-no-auth',request_json('GET',base_url+'/protected'))
        t013=unauth.status==401
        denied=trace('protected-denied',request_json('GET',base_url+'/protected',token='no-privilege-token'))
        t014=denied.status==403 and isinstance(denied.json,dict) and 'protected' not in denied.json
        resource_url=base_url+'/resources/run-resource'
        p1=trace('put-no-privilege',request_json('PUT',resource_url,{'value':0},token='no-privilege-token'))
        p2=trace('put-create',request_json('PUT',resource_url,{'value':1},token='create-token'))
        p3=trace('put-create-existing',request_json('PUT',resource_url,{'value':2},token='create-token'))
        p4=trace('put-update',request_json('PUT',resource_url,{'value':3},token='update-token'))
        t015=(p1.status,p2.status,p3.status,p4.status)==(403,201,403,200)
        allow=trace('abac-allow',request_json('POST',base_url+'/authorize',{'subject':{'factory':'F1','role':'engineer'},'resource':{'factory':'F1'},'context':{'hour':10,'equipment_state':'READY'}}))
        deny=trace('abac-deny',request_json('POST',base_url+'/authorize',{'subject':{'factory':'F2','role':'engineer'},'resource':{'factory':'F1'},'context':{'hour':10,'equipment_state':'READY'}}))
        t016=allow.status==200 and allow.json.get('allowed') is True and deny.status==200 and deny.json.get('allowed') is False
        signed=trace('signed',request_json('GET',base_url+'/signed/'+quote(sample.aas_id,safe='')))
        if external_base_url:
            t017=False; t017_blocked=True; t017_message='external mode requires target-specific signature verifier/key configuration'
        else:
            token=signed.json.get('jws') if signed.status==200 and isinstance(signed.json,dict) else ''
            ok,payload=verify_compact(token,secret)
            tamper_ok=verify_compact(_tamper_jws(token),secret)[0] if token else True
            t017=bool(ok and payload and sample.aas_id.encode() in payload and not tamper_ok); t017_blocked=False; t017_message='original JWS verifies and tampered payload fails'
    except TransportError as exc:
        api_trace.append({'operation':'transport','error':str(exc)})
        t010=t011=t012=t013=t014=t015=t016=t017=False; t017_blocked=False
        api_blocked=str(exc)
    else:
        api_blocked=None
    finally:
        if running is not None: running.stop()

    api_path=artifacts_dir/'api-trace.json'; api_path.write_text(json.dumps(api_trace,ensure_ascii=False,indent=2),encoding='utf-8')
    api_art=artifact_entry(output_dir,api_path,'ART-API-TRACE','application/json')
    api_values={10:t010,11:t011,12:t012,13:t013,14:t014,15:t015,16:t016,17:t017}
    api_expected={10:'valid query 200 + invalid query 400',11:'AAS read 200',12:'Submodel read 200',13:401,14:403,15:[403,201,403,200],16:'allow and deny decisions',17:'valid signature + tamper rejection'}
    for i in range(10,18):
        tid=f'AAS-T{i:03d}'; blocked=bool(api_blocked) or (i==17 and external_base_url)
        msg=api_blocked if api_blocked else (t017_message if i==17 else test_map[tid]['title'])
        results.append(test_result(tid,'C1',api_values[i],test_map[tid]['linked_rule_ids'],[assertion(tid+'-assertion',api_values[i],api_expected[i],api_values[i],msg)],[api_art],observations=msg,blocked=blocked))

    aasx_path=build_aasx(sample,output_dir/'sample.aasx')
    aasx_checks=validate_aasx(aasx_path,set(profile['parameters']['required_supplementary_files']))
    aasx_art=artifact_entry(output_dir,aasx_path,'ART-AASX','application/asset-administration-shell-package')
    structure=[x for x in aasx_checks if x.check_id!='aasx-supplementary']
    supplementary=next((x for x in aasx_checks if x.check_id=='aasx-supplementary'),None)
    t018=bool(structure) and all(x.passed for x in structure)
    t019=bool(supplementary and supplementary.passed)
    results.append(test_result('AAS-T018','C2',t018,test_map['AAS-T018']['linked_rule_ids'],[assertion(x.check_id,x.passed,True,x.observed,x.message) for x in structure],[aasx_art]))
    results.append(test_result('AAS-T019','C2',t019,test_map['AAS-T019']['linked_rule_ids'],[assertion(supplementary.check_id,supplementary.passed,True,supplementary.observed,supplementary.message)] if supplementary else [assertion('aasx-supplementary',False,True,None,'supplementary check missing')],[aasx_art]))

    results.sort(key=lambda x:x['test_id'])
    counts={k:sum(1 for x in results if x['result']==k) for k in ['PASS','FAIL','BLOCKED','NOT_APPLICABLE']}
    summary={'profile_id':'P-AAS','profile_version':profile['profile_version'],'counts':counts,'overall':'PASS' if counts['FAIL']==0 and counts['BLOCKED']==0 else 'FAIL'}
    summary_path=output_dir/'test-summary.json'; summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    bundle={
        'schema_version':'1.0','evidence_bundle_id':'P-AAS-REFERENCE-'+started.replace(':','').replace('-','').replace('+','_'),
        'profile_version':profile['profile_version'],'system_under_test':{'name':'Synthetic Automotive EOL AAS Reference','version':'1.0','site':'synthetic-reference-site','asset_ids':[sample.aas['assetInformation']['globalAssetId']],'model_ids':[]},
        'run_started_at':started,'run_completed_at':now_iso(),'environment':{'mode':'external' if external_base_url else 'embedded-reference','base_url':base_url},
        'test_results':results,'bundle_sha256':None,'signatures':[]
    }
    (output_dir/'evidence-bundle.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
    return bundle
