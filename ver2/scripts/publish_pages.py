#!/usr/bin/env python3
import json,shutil,sys
from pathlib import Path
def choose_destination(src,dest_dir):
    base=dest_dir/src.name; src_bytes=src.read_bytes()
    if not base.exists():return base,'new'
    if src_bytes==base.read_bytes():return base,'reuse'
    n=2
    while True:
        c=dest_dir/f'{src.stem}-r{n}{src.suffix}'
        if not c.exists():return c,'revision'
        if src_bytes==c.read_bytes():return c,'reuse_revision'
        n+=1
def main():
    if len(sys.argv) not in (6,7):raise SystemExit('usage: publish_pages.py enriched_json src_dir pages_checkout pages_base manifest_path [notion_route_json]')
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); src_dir=Path(sys.argv[2]); pages_checkout=Path(sys.argv[3]); pages_base=sys.argv[4].rstrip('/'); manifest_path=Path(sys.argv[5]); route_path=Path(sys.argv[6]) if len(sys.argv)==7 else None; seq=data['sequence']; default_ch=int(data['passage']['chapter']); fallback_only=None
    if route_path:
        route=json.loads(route_path.read_text(encoding='utf-8')); fallback_only=set(str(v) for v in route.get('fallback_needed',[]))
    dest_dir=pages_checkout/seq
    if fallback_only:dest_dir.mkdir(parents=True,exist_ok=True)
    entries=[]
    for obj in data['verses']:
        ch=int(obj.get('chapter',default_ch)); verse=int(obj['verse']); ref=f'{ch}:{verse}'
        if fallback_only is not None and ref not in fallback_only:continue
        expected=src_dir/f'genesis-{ch}-{verse}.html'
        if not expected.exists():raise SystemExit(f'missing generated HTML: {expected}')
        dest,action=choose_destination(expected,dest_dir)
        if action in {'new','revision'}:shutil.copy2(expected,dest)
        entries.append({'chapter':ch,'verse':verse,'ref':ref,'source':str(expected),'filename':dest.name,'url':f'{pages_base}/{seq}/{dest.name}','action':action})
    manifest={'sequence':seq,'pages_base_url':pages_base,'fallback_only':sorted(fallback_only) if fallback_only is not None else None,'entries':entries}; manifest_path.parent.mkdir(parents=True,exist_ok=True); manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':main()
