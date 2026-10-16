#!/usr/bin/env python3
"""Auditable UI-only localization; Python 3 standard library, no dependencies."""
import argparse, difflib, hashlib, json, os, re, shutil, subprocess, sys, urllib.request
from pathlib import Path
from upstream_compat import apply_compat
ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT/'vendor/Compositor'
SOURCE = ROOT/'build/source'

def load(path, default=None):
    return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)
def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')
def run(*args):
    subprocess.run(list(map(str,args)),check=True)

def tokens(s):
    """Swift strings/comments opaque, including nested interpolation and comments."""
    out=[]; i=0
    def quoted(i):
        delim='"""' if s.startswith('"""',i) else '"'; j=i+len(delim)
        while j<len(s):
            if s.startswith(delim,j): return j+len(delim)
            if s.startswith('\\(',j):
                j=balanced(j+2); continue
            if s[j]=='\\': j+=2
            else: j+=1
        raise ValueError('Unterminated string')
    def balanced(j):
        depth=1
        while j<len(s):
            if s[j]=='"': j=quoted(j); continue
            if s[j]=='(': depth+=1
            if s[j]==')':
                depth-=1
                if not depth: return j+1
            j+=1
        raise ValueError('Unterminated interpolation')
    while i<len(s):
        if s.startswith('//',i):
            j=s.find('\n',i); j=len(s) if j<0 else j
            out.append((i,j,'comment')); i=j
        elif s.startswith('/*',i):
            j=i+2; depth=1
            while j<len(s) and depth:
                if s.startswith('/*',j): depth+=1; j+=2
                elif s.startswith('*/',j): depth-=1; j+=2
                else: j+=1
            out.append((i,j,'comment')); i=j
        elif s[i]=='"':
            j=quoted(i); out.append((i,j,'string')); i=j
        else: i+=1
    return out

def decode(lit):
    if lit.startswith('"""'): return None
    # Interpolated literals become stable numbered placeholders for translation.
    body=lit[1:-1]; result=''; i=0; n=0
    while i<len(body):
        if body.startswith('\\(',i):
            j=i+2; depth=1
            while j<len(body) and depth:
                if body[j]=='"':
                    # Use the same lexer to skip a nested quoted expression.
                    t=tokens(body[j:])[0]; j+=t[1]; continue
                if body[j]=='(': depth+=1
                elif body[j]==')': depth-=1
                j+=1
            result+='{'+str(n)+'}'; n+=1; i=j
        elif body[i]=='\\':
            if i+1>=len(body): return None
            c=body[i+1]
            if c=='u':
                m=re.match(r'\\u\{([0-9a-fA-F]+)\}',body[i:])
                if not m: return None
                result+=chr(int(m[1],16)); i+=len(m[0]); continue
            result+= {'n':'\n','t':'\t','r':'\r','0':'\0','"':'"','\\':'\\'}.get(c,c); i+=2
        else: result+=body[i]; i+=1
    return result

# UI boundary calls only. No replacing enum declarations, persistence keys or user content.
CALLS={'Text','Button','Toggle','Picker','Menu','Label','GroupBox','Section','TextField','SecureField','Window','WindowGroup',
       'confirmationDialog','alert','help','navigationTitle','accessibilityLabel','accessibilityHint','setAccessibilityLabel','addButton','slider','control','amount','colorSlider','pointSlider','wheel','geometrySlider','calibrationSlider','opticsSlider','sharpenSlider','hueRange','dimension','swatch','modifyControl'}
DYNAMIC=re.compile(r'^(?:\$0|[A-Za-z_][\w]*(?:\??\.[A-Za-z_][\w]*)*)\.(?:rawValue|title)$')
# .title could be a filename: only these known display-only variables are accepted.
TITLE_ALLOW={'definition.title','option.title','operation.title','kind.title'}

def rewrite(s, rel, catalog, sites, audit):
    ts=tokens(s); masked=list(s)
    for a,b,k in ts: masked[a:b]=' '*(b-a)
    mask=''.join(masked); edits={}
    def record(a,b,kind):
        lit=s[a:b]; key=decode(lit)
        if key and re.search('[A-Za-z]',key):
            catalog.setdefault(key,[]).append({'file':rel,'line':s.count('\n',0,a)+1,'kind':kind})
    for a,b,k in ts:
        if k=='string': record(a,b,'inventory')
    # Capture balanced first argument of UI calls; replace literals within only this argument.
    for m in re.finditer(r'\b('+ '|'.join(sorted(CALLS))+r')\s*\(',mask):
        a=m.end(); j=a; depth=0
        while j<len(mask):
            c=mask[j]
            if c in '([{': depth+=1
            elif c in ')]}':
                if depth==0: break
                depth-=1
            elif c==',' and depth==0: break
            j+=1
        expr=s[a:j].strip()
        # labeled Text(verbatim:) and button role don't accept a String in this position.
        if re.match(r'\w+\s*:',expr): continue
        for x,y,k in ts:
            if x>=a and y<=j and k=='string' and not (x>0 and s[x-1]=='#'):
                key=decode(s[x:y])
                if key and re.search('[A-Za-z]',key):
                    edits[(x,y)]='CN.text('+s[x:y]+')'; sites.append({'file':rel,'line':s.count('\n',0,x)+1,'key':key,'kind':'UI literal'})
        safe_dynamic = (rel.startswith('Compositor/UI/') and 'ProjectTabs' not in rel and expr in {'title','help','label','name','names[index]','anchorNames[index]','anchorNames[anchor]','CameraRawMixerSettings.names[index]','raw.calibration.process.summary','mode.help','help(mode)','request.title','request.confirmTitle','item.message'}) or expr in {'tool.label','session.mergeTitle'}
        if safe_dynamic or (DYNAMIC.fullmatch(expr) and (expr.endswith('.rawValue') or expr in TITLE_ALLOW)):
            x=a+len(s[a:j])-len(s[a:j].lstrip()); y=j-len(s[a:j])+len(s[a:j].rstrip())
            edits[(x,y)]='CN.text('+expr+')'; sites.append({'file':rel,'expression':expr,'kind':'dynamic display'})
        elif expr and not any(x>=a and y<=j for x,y in edits):
            audit.append({'file':rel,'line':s.count('\n',0,a)+1,'expression':expr,'reason':'dynamic/user data: manual classification required'})
    # Explicit AppKit presentation assignments and labeled menu/panel titles.
    for x,y,k in ts:
        if k!='string' or (x,y) in edits or (x>0 and s[x-1]=='#'): continue
        prefix=mask[max(0,x-160):x]
        if re.search(r'\.(?:title|messageText|informativeText|toolTip|placeholderString|prompt)\s*=\s*$',prefix) or re.search(r'\b(?:title|message|informativeText|withTitle)\s*:\s*$',prefix):
            # Do not localize declaration initialization, identity definitions or font names.
            if 'KeyboardShortcuts.swift' in rel or 'TypeControls.swift' in rel: continue
            key=decode(s[x:y])
            if key and re.search('[A-Za-z]',key):
                edits[(x,y)]='CN.text('+s[x:y]+')'; sites.append({'file':rel,'key':key,'kind':'AppKit literal'})
    # Nested UI calls must never create overlapping edits.
    end=-1
    for a,b in sorted(edits):
        if a<end: raise ValueError('Overlapping patches: '+rel)
        end=b
    for (a,b),value in sorted(edits.items(),reverse=True): s=s[:a]+value+s[b:]
    return s

def fetch(args):
    commit=args.ref
    target=ROOT/'build/fetch'
    if target.exists(): raise SystemExit('build/fetch 已存在；请保留或移动后再拉取。')
    run('git','clone','https://github.com/robbietilton/Compositor.git',target)
    run('git','-C',target,'checkout','--detach',commit)
    sha=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
    if VENDOR.exists(): VENDOR.rename(ROOT/'vendor'/('Compositor.backup.'+str(__import__('time').time_ns())))
    shutil.copytree(target,VENDOR,ignore=shutil.ignore_patterns('.git'))
    (ROOT/'UPSTREAM_COMMIT').write_text(sha+'\n')
    print('已拉取并保留旧源码备份：',sha)

def prepare(args):
    if SOURCE.exists(): shutil.rmtree(SOURCE)
    shutil.copytree(VENDOR,SOURCE)
    save(ROOT/'reports/upstream-compat.json', apply_compat(SOURCE, VENDOR))
    catalog={}; sites=[]; audit=[]; diffs=[]
    for f in sorted((SOURCE/'Compositor').rglob('*.swift')):
        rel=f.relative_to(SOURCE).as_posix(); before=f.read_text(); after=rewrite(before,rel,catalog,sites,audit)
        f.write_text(after)
    # Fail-closed patches target the pinned upstream. Upgrade requires review when anchors change.
    for patch in load(ROOT/'patches/anchors.json',[]):
        f=SOURCE/patch['file']; s=f.read_text(); count=s.count(patch['old'])
        if count!=patch.get('count',1): raise SystemExit('补丁锚点变化，请审核：'+patch['file']+' '+patch['old'][:70])
        f.write_text(s.replace(patch['old'],patch['new']))
    shutil.copy(ROOT/'scripts/CN.swift',SOURCE/'Compositor/CN.swift')
    for old in sorted(VENDOR.rglob('*')):
        if not old.is_file(): continue
        relative=old.relative_to(VENDOR); f=SOURCE/relative
        if f.exists() and old.read_bytes()==f.read_bytes(): continue
        # Every changed upstream text file, including deletions and build metadata.
        diffs.extend(difflib.unified_diff(old.read_text().splitlines(True),f.read_text().splitlines(True) if f.exists() else [],fromfile='a/'+str(relative),tofile='b/'+str(relative) if f.exists() else '/dev/null'))
    (ROOT/'patches/generated.patch').write_text(''.join(diffs))
    save(ROOT/'reports/upstream-sha256.json', {str(f.relative_to(VENDOR)): hashlib.sha256(f.read_bytes()).hexdigest() for f in VENDOR.rglob('*') if f.is_file()})
    save(ROOT/'translations/inventory.json',catalog)
    save(ROOT/'reports/display-sites.json',sites)
    save(ROOT/'reports/dynamic-review.json',audit)
    import_translations(args)
    print('已准备独立源码；字符串候选',len(catalog),'，显示边界',len(sites),'，动态待审',len(audit))

def placeholders(s): return sorted(re.findall(r'\{\d+\}',s))
def import_translations(args):
    catalog=load(ROOT/'translations/inventory.json'); cache=load(ROOT/'translations/machine.zh-CN.json'); cache.update(load(ROOT/'translations/zh-CN.json'))
    bad={k:v for k,v in cache.items() if not isinstance(v,str) or placeholders(k)!=placeholders(v)}
    if bad: raise SystemExit('占位符不一致：'+repr(list(bad)[:5]))
    save(SOURCE/'Compositor/zh-CN.json',cache)
    missing={k:v for k,v in catalog.items() if k not in cache}
    save(ROOT/'reports/untranslated.json',missing)
    display = load(ROOT/'reports/display-sites.json', [])
    display_keys = {x['key'] for x in display if 'key' in x}
    save(ROOT/'reports/untranslated-ui.json', {k: catalog.get(k, []) for k in sorted(display_keys) if k not in cache})
    # Inventory is broad and includes code identifiers. Coverage is deliberately not a UI completeness claim.
    save(ROOT/'reports/summary.json',{'commit':(ROOT/'UPSTREAM_COMMIT').read_text().strip(),'inventory':len(catalog),'dictionary':len(cache),'untranslated_candidates':len(missing),'literal_ui_keys':len(display_keys),'missing_literal_ui_keys':len(display_keys-cache.keys()),'xcode_build':'NOT VERIFIED','ui_review':'NOT VERIFIED'})
    xc={'sourceLanguage':'en','strings':{},'version':'1.0'}
    for k in sorted(catalog):
        if k in cache:
            xc['strings'][k]={'extractionState':'manual','localizations':{'zh-Hans':{'stringUnit':{'state':'translated','value':cache[k]}}}}
    save(SOURCE/'Compositor/Localizable.xcstrings',xc)

def translate(args):
    key=os.environ.get('COMPOSITOR_TRANSLATE_API_KEY')
    if not key: raise SystemExit('请设置 COMPOSITOR_TRANSLATE_API_KEY；不读取其他凭证。')
    if not args.url.startswith('https://'): raise SystemExit('翻译地址必须使用 HTTPS')
    inv=load(ROOT/'translations/inventory.json'); human=load(ROOT/'translations/zh-CN.json'); machine=load(ROOT/'translations/machine.zh-CN.json')
    # Only display candidates by default; --all includes identifiers and should be reviewed carefully.
    keys=list(inv) if args.all else list(dict.fromkeys(x['key'] for x in load(ROOT/'reports/display-sites.json',[]) if 'key' in x))
    pending=[k for k in keys if k not in human and k not in machine]
    for start in range(0,len(pending),args.batch):
        batch=pending[start:start+args.batch]
        body={'model':args.model,'messages':[{'role':'system','content':'Translate image editor UI into Simplified Chinese using Photoshop terms. Return ONLY a JSON object mapping original strings to translations. Preserve {0} numbered placeholders exactly, shortcuts and units. Never translate identifiers.'},{'role':'user','content':json.dumps(batch,ensure_ascii=False)}],'temperature':0}
        req=urllib.request.Request(args.url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=120) as response: data=json.load(response)
        content=data['choices'][0]['message']['content'].strip()
        if content.startswith('```'): content='\n'.join(content.splitlines()[1:-1])
        result=json.loads(content)
        if set(result)!=set(batch) or any(not isinstance(v,str) or placeholders(k)!=placeholders(v) for k,v in result.items()): raise SystemExit('翻译响应不完整或占位符变化；已保留之前缓存。')
        machine.update(result); save(ROOT/'translations/machine.zh-CN.json',machine)
        print('已缓存',min(start+args.batch,len(pending)),'/',len(pending))
    import_translations(args)

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('fetch'); f.add_argument('--ref',default='origin/main')
    for name in ['prepare','import','report']: sub.add_parser(name)
    t=sub.add_parser('translate'); t.add_argument('--url',required=True,help='完整 OpenAI-compatible /chat/completions HTTPS URL'); t.add_argument('--model',required=True); t.add_argument('--batch',type=int,default=25); t.add_argument('--all',action='store_true')
    a=p.parse_args()
    if getattr(a,'batch',1)<1: p.error('batch 必须大于 0')
    {'fetch':fetch,'prepare':prepare,'translate':translate,'import':import_translations,'report':import_translations}[a.command](a)
if __name__=='__main__': main()
