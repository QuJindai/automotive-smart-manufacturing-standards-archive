from __future__ import annotations

import argparse
from pathlib import Path

from .runner import run_reference


def build_parser() -> argparse.ArgumentParser:
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser(description='Run P-AAS reference executor V1')
    p.add_argument('--out',required=True,help='Output directory for evidence and generated AASX')
    p.add_argument('--example',default=str(root/'examples'/'automotive-eol-station'),help='Synthetic or user-provided AAS fixture directory')
    p.add_argument('--profile-dir',default=str(root/'profile'),help='Directory containing P-AAS profile/test JSON')
    p.add_argument('--base-url',default=None,help='Optional external AAS service base URL; default uses embedded reference service')
    return p


def main(argv=None) -> int:
    args=build_parser().parse_args(argv)
    bundle=run_reference(args.example,args.out,profile_dir=args.profile_dir,external_base_url=args.base_url)
    counts={k:sum(1 for x in bundle['test_results'] if x['result']==k) for k in ['PASS','FAIL','BLOCKED','NOT_APPLICABLE']}
    print(f"AAS_PASS={counts['PASS']} AAS_FAIL={counts['FAIL']} AAS_BLOCKED={counts['BLOCKED']}")
    print(f"EVIDENCE_BUNDLE={Path(args.out)/'evidence-bundle.json'}")
    return 0 if counts['FAIL']==0 and counts['BLOCKED']==0 else 1

if __name__=='__main__':
    raise SystemExit(main())
