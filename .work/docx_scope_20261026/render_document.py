"""Use the packaged DOCX rasterizer with native Word PDF export on Windows."""
import importlib.util
import os
from pathlib import Path
import subprocess

RUNTIME=Path('C:/Users/ammo/.cache/codex-runtimes/codex-primary-runtime')
SKILL=Path('C:/Users/ammo/.codex/plugins/cache/openai-primary-runtime/documents/26.1025.11240/skills/documents')
os.environ['PATH']=str(RUNTIME/'dependencies/native/poppler/Library/bin')+os.pathsep+os.environ.get('PATH','')
spec=importlib.util.spec_from_file_location('packaged_docx_renderer',SKILL/'render_docx.py')
renderer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def native_pdf(doc_path,user_profile,convert_tmp_dir,stem,verbose):
    out=Path(convert_tmp_dir)/(stem+'.pdf')
    command=[str(RUNTIME/'dependencies/native/powershell/pwsh.exe'),'-NoProfile','-File',
             str(Path(__file__).with_name('export_word.ps1')),
             '-InputDoc',str(Path(doc_path).resolve()),'-OutputPdf',str(out.resolve())]
    result=subprocess.run(command,capture_output=True,text=True,timeout=170,encoding='utf-8',errors='replace')
    if result.returncode:
        raise RuntimeError(result.stdout+'\n'+result.stderr)
    if verbose:print(result.stdout)
    return str(out),'Native Word PDF export; packaged render_docx.py and bundled Poppler rasterization'


renderer.convert_to_pdf=native_pdf
renderer.main()
