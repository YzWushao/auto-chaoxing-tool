"""Maven lifecycle adapter for official SDK tools; does not invoke Gradle."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parent
TARGET=ROOT/'target'

def run(*args):
    subprocess.run([str(arg) for arg in args],check=True,cwd=ROOT)

def quote_arg(value):
    return '"'+str(value).replace('\\','/').replace('"','\\"')+'"'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--maven',required=True);parser.add_argument('--repository',required=True)
    options=parser.parse_args()
    pom=ET.parse(ROOT/'pom.xml').getroot();ns={'m':'http://maven.apache.org/POM/4.0.0'}
    version=pom.findtext('m:version',namespaces=ns);version_code=pom.findtext('m:properties/m:android.versionCode',namespaces=ns)
    if not version or not version_code or not version_code.isdigit():raise RuntimeError('Missing Android version in pom.xml')
    sdk=Path(os.environ['ANDROID_HOME']);jdk=Path(os.environ['JAVA_HOME']);tools=sdk/'build-tools'/'35.0.0'
    java=jdk/'bin'/'java.exe';javac=jdk/'bin'/'javac.exe';aapt=tools/'aapt2.exe';android=sdk/'platforms'/'android-35'/'android.jar'
    for path in (java,javac,aapt,android):
        if not path.exists():raise RuntimeError('Missing Android build tool: '+str(path))
    TARGET.mkdir(exist_ok=True)
    work=TARGET/'sdk-build'
    if work.exists():
        if work.resolve().parent!=TARGET.resolve():raise RuntimeError('Invalid build directory')
        shutil.rmtree(work)
    work.mkdir();unpacked=work/'libraries';unpacked.mkdir()
    policy_classes=work/'policy-tests';policy_classes.mkdir()
    run(javac,'-encoding','UTF-8','-d',policy_classes,ROOT/'app/src/main/java/top/autochaoxing/mobile/AutoZoomPolicy.java',
        ROOT/'tests/top/autochaoxing/mobile/AutoZoomPolicyTest.java')
    run(java,'-cp',policy_classes,'top.autochaoxing.mobile.AutoZoomPolicyTest')
    tooling=TARGET/'manifest-tools';tooling.mkdir(exist_ok=True)
    run(options.maven,'-B','-f',ROOT/'tools'/'pom.xml','-Dmaven.repo.local='+options.repository,
        'org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies','-DoutputDirectory='+str(tooling))
    manifests=[];packages=set();jars=[];resources=[];assets={};native={};legal={};jar_notices={}
    for index,artifact in enumerate(sorted((TARGET/'dependencies').rglob('*'))):
        if artifact.suffix=='.jar':jars.append(artifact)
        if artifact.suffix!='.aar':continue
        destination=unpacked/str(index)
        with zipfile.ZipFile(artifact) as bundle:bundle.extractall(destination)
        manifest=destination/'AndroidManifest.xml'
        if manifest.exists():
            manifests.append(manifest);package=ET.parse(manifest).getroot().get('package')
            if package:packages.add(package)
        jars.extend(destination.glob('*.jar'));jars.extend((destination/'libs').glob('*.jar'))
        res=destination/'res'
        if res.exists() and any(res.rglob('*.*')):
            compiled=work/(str(index)+'-res.zip');run(aapt,'compile','--dir',res,'-o',compiled);resources.append(compiled)
        for category,folder,collection in (('assets','assets',assets),('lib','jni',native)):
            location=destination/folder
            if location.exists():
                for file in location.rglob('*'):
                    if file.is_file():
                        key=category+'/'+file.relative_to(location).as_posix()
                        if key in collection and collection[key].read_bytes()!=file.read_bytes():raise RuntimeError('Conflicting asset '+key)
                        collection[key]=file
        if (destination/'META-INF').exists():
            for file in (destination/'META-INF').rglob('*'):
                if file.is_file():legal[artifact.stem+'/'+file.name]=file
        for file in destination.iterdir():
            if file.is_file() and any(word in file.name.lower() for word in ('license','notice','copyright')):
                legal[artifact.stem+'/'+file.name]=file
    manifest=work/'AndroidManifest.xml';tool_cp=os.pathsep.join(str(p) for p in tooling.glob('*.jar'))
    merge_classes=work/'manifest-classes';merge_classes.mkdir()
    run(javac,'-encoding','UTF-8','-cp',tool_cp,'-d',merge_classes,ROOT/'tools'/'MergeManifest.java')
    run(java,'-cp',str(merge_classes)+os.pathsep+tool_cp,'MergeManifest',ROOT/'app/src/main/AndroidManifest.xml',manifest,version_code,version,*manifests)
    generated=work/'generated';generated.mkdir()
    application=work/'app-res.zip';run(aapt,'compile','--dir',ROOT/'app/src/main/res','-o',application)
    resource_apk=work/'resources.ap_'
    link=[aapt,'link','-I',android,'--manifest',manifest,'--java',generated,'--auto-add-overlay','--extra-packages',':'.join(sorted(packages)),
          '--min-sdk-version','26','--target-sdk-version','35','-o',resource_apk]
    for resource in [*resources,application]:link.extend(['-R',resource])
    run(*link)
    classes=work/'classes';classes.mkdir()
    sources=[*(ROOT/'app/src/main/java').rglob('*.java'),*generated.rglob('*.java')]
    args=['-encoding','UTF-8','-source','17','-target','17','-Xlint:deprecation','-cp',os.pathsep.join(str(p) for p in [android,*jars]),'-d',classes,*sources]
    response=work/'javac.args';response.write_text('\n'.join(quote_arg(v) for v in args),encoding='utf-8')
    run(javac,'@'+str(response))
    combined=work/'program.jar';seen={}
    with zipfile.ZipFile(combined,'w',zipfile.ZIP_DEFLATED) as output:
        for file in classes.rglob('*.class'):
            key=file.relative_to(classes).as_posix();seen[key]=file.read_bytes();output.writestr(key,seen[key])
        for jar in jars:
            with zipfile.ZipFile(jar) as bundle:
                for name in bundle.namelist():
                    if name.startswith('META-INF/') and any(word in name.upper() for word in ('LICENSE','NOTICE','COPYRIGHT')) and not name.endswith('/'):
                        jar_notices[jar.parent.name+'-'+jar.stem+'/'+name]=bundle.read(name)
                    if not name.endswith('.class') or name.startswith('META-INF/') or name=='module-info.class':continue
                    content=bundle.read(name)
                    if name in seen:
                        if seen[name]!=content:raise RuntimeError('Conflicting dependency class '+name)
                    else:seen[name]=content;output.writestr(name,content)
    dex=work/'dex';dex.mkdir()
    run(java,'-Xmx2g','-cp',tools/'lib/d8.jar','com.android.tools.r8.D8','--release','--min-api','26','--lib',android,'--output',dex,combined)
    unsigned=work/'unsigned.apk';shutil.copyfile(resource_apk,unsigned)
    with zipfile.ZipFile(unsigned,'a',zipfile.ZIP_DEFLATED) as output:
        for file in dex.glob('*.dex'):output.write(file,file.name)
        for key,file in {**assets,**native}.items():output.write(file,key,compress_type=zipfile.ZIP_STORED)
        for name,file in legal.items():output.write(file,'assets/dependency-notices/'+name)
        for name,content in jar_notices.items():output.writestr('assets/dependency-notices/'+name,content)
        output.write(ROOT.parent/'LICENSE','assets/LICENSE-AGPL-3.0.txt')
        output.write(ROOT.parent/'THIRD_PARTY.md','assets/THIRD_PARTY.md')
        output.write(ROOT.parent/'NOTICE.md','assets/NOTICE.md')
    aligned=work/'aligned.apk';run(tools/'zipalign.exe','-P','16','-f','4',unsigned,aligned)
    output=TARGET/('auto-chaoxing-tool-'+version+'-release.apk')
    required=('AUTO_CHAOXING_ANDROID_KEYSTORE','AUTO_CHAOXING_ANDROID_STORE_PASSWORD','AUTO_CHAOXING_ANDROID_KEY_PASSWORD')
    if not all(os.environ.get(key) for key in required):raise RuntimeError('Release signing configuration is required')
    run(java,'-jar',tools/'lib/apksigner.jar','sign','--ks',os.environ[required[0]],'--ks-key-alias','auto-chaoxing',
        '--ks-pass','env:'+required[1],'--key-pass','env:'+required[2],'--out',output,aligned)
    run(java,'-jar',tools/'lib/apksigner.jar','verify','--verbose',output)
    run(tools/'zipalign.exe','-c','-P','16','4',output)
    print('Maven Android APK:',output,flush=True)

if __name__=='__main__':main()
