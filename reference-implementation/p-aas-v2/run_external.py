#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
V1=ROOT.parent/'p-aas-v1'
for p in (ROOT,V1):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
from paas_v2.basyx import BasyxAdapter
from paas_v2.runner import run_external


def main():
    ap=argparse.ArgumentParser(description='Run P-AAS V2 against an external AAS implementation')
    ap.add_argument('--adapter',choices=['basyx'],default='basyx')
    ap.add_argument('--base-url',required=True)
    ap.add_argument('--fixture',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--target-version',default='unknown')
    ap.add_argument('--authorization-enabled',action='store_true')
    args=ap.parse_args()
    fixture=json.loads(Path(args.fixture).read_text(encoding='utf-8'))
    adapter=BasyxAdapter(args.base_url,{'implementation':'Eclipse BaSyx','version':args.target_version,'authorization_enabled':args.authorization_enabled})
    result=run_external(adapter,fixture,Path(args.out))
    print('P_AAS_V2_REQUIRED_FAILURES='+str(result['required_failures']))
    return 1 if result['required_failures'] else 0

if __name__=='__main__': raise SystemExit(main())
