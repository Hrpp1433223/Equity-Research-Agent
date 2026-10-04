import argparse, json, hashlib, subprocess, os, sys, shutil
from pathlib import Path
from datetime import datetime, timezone
from .finance import scenarios, sensitivity

ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,obj):Path(p).write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')
def binary(name):
    env=os.environ.get('EQUITY_'+name.upper())
    if env:return env
    found=shutil.which(name)
    if found:return found
    # Local Windows runtime discovery is optional and never part of model configuration.
    runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler'
    matches=list(runtime.rglob(name+'.exe'))
    if matches:return str(matches[0])
    raise RuntimeError('RENDERER_UNAVAILABLE: '+name+'; set EQUITY_'+name.upper())

def render(run):
    cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/convert_word.ps1'),'-InputDocx',str(run/'report.docx'),'-OutputPdf',str(run/'report.pdf')]
    result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    (run/'renderer.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode or not (run/'report.pdf').is_file():raise RuntimeError('RENDERER_UNAVAILABLE: Word COM export failed. See renderer.log')
    qa=run/'qa/pages';qa.mkdir(parents=True,exist_ok=True)
    r=subprocess.run([binary('pdftoppm'),'-r','110','-png',str(run/'report.pdf'),str(qa/'page')],capture_output=True,text=True,timeout=120)
    (run/'qa/render.log').write_text(r.stdout+r.stderr,encoding='utf-8')
    if r.returncode:raise RuntimeError('PNG_RENDER_FAILED')
    manifest_path=run/'run_manifest.json'
    if manifest_path.exists():
        manifest=read(manifest_path)
        manifest.update(renderer='Microsoft Word COM ExportAsFixedFormat; Poppler PNG',renderer_result=result.stdout.strip(),pdf_sha256=hashlib.sha256((run/'report.pdf').read_bytes()).hexdigest(),export_finished_utc=datetime.now(timezone.utc).isoformat())
        write(manifest_path,manifest)

def main():
    parser=argparse.ArgumentParser(description='Public multi-market equity research workspace')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('serve');p.add_argument('--port',type=int,default=8766)
    p=sub.add_parser('company');p.add_argument('--market',choices=['US','SH','HK'],required=True);p.add_argument('--symbol',required=True);p.add_argument('--snapshot');p.add_argument('--assumptions');p.add_argument('--sector',default='non_financial');p.add_argument('--live',action='store_true');p.add_argument('--skip-pdf',action='store_true');p.add_argument('--output',default='outputs/companies')
    p=sub.add_parser('validate');p.add_argument('--run-dir',required=True)
    a=parser.parse_args()
    if a.command=='serve':
        from .app import serve
        serve(a.port)
    elif a.command=='validate':
        from .company_reports import validate
        result=validate(a.run_dir);print(json.dumps(result));return 0 if result['passed'] else 1
    else:
        from .company_reports import generate_company
        run,result=generate_company(a.market,a.symbol,a.output,snapshot_file=a.snapshot,overrides=read(a.assumptions) if a.assumptions else None,sector=a.sector,live=a.live,skip_pdf=a.skip_pdf)
        print(json.dumps({'report':str(run),'status':result['valuation_status']}))
    return 0
if __name__=='__main__':raise SystemExit(main())
