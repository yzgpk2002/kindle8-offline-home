"""Offline publication checks. Reports filenames/rules, never matched secrets."""
import re,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
allowed={'.md','.txt','.py','.cjs','.js','.html','.sh','.lua','.c','.java','.json','.png'}
fail=[];count=0
patterns={
 'private-key':r'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----',
 'github-token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
 'api-key':r'\bsk-[A-Za-z0-9]{24,}',
 'personal-path':r'[A-Za-z]:[/\\]Users[/\\]',
}
for p in root.rglob('*'):
    rel=p.relative_to(root)
    if any(x in ('.git','__pycache__','.pytest_cache') for x in rel.parts) or not p.is_file():continue
    count+=1
    if p.name not in ('.gitignore','.gitattributes') and p.suffix not in allowed:fail.append((str(rel),'unexpected file type'))
    if p.suffix=='.png':continue
    s=p.read_text(encoding='utf-8-sig')
    if p!=Path(__file__).resolve():
        for name,pattern in patterns.items():
            if re.search(pattern,s):fail.append((str(rel),name))
    if p.suffix=='.md':
        for link in re.findall(r'\]\(([^\s)]+)\)',s):
            if '://' in link or link.startswith('#'):continue
            target=(p.parent/link.split('#')[0]).resolve()
            if not target.is_relative_to(root) or not target.exists():fail.append((str(rel),'broken local link: '+link))
for name,rule in fail:print(name+': '+rule)
print('PUBLICATION_CHECK '+('FAIL' if fail else 'PASS')+' files='+str(count))
sys.exit(bool(fail))
