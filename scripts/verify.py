#!/usr/bin/env python3
"""Focused regression checks for localization and protection of upstream content."""
import importlib.util, json, subprocess, tempfile, unittest, re, sys, shutil, plistlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
ALLOW_UNTRANSLATED = '--allow-untranslated' in sys.argv
if ALLOW_UNTRANSLATED: sys.argv.remove('--allow-untranslated')
spec=importlib.util.spec_from_file_location('localize',ROOT/'scripts/localize.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class LocalizationTests(unittest.TestCase):
    def rewrite(self,s):
        return m.rewrite(s,'Compositor/UI/Test.swift',{},[],[])
    def test_identity_and_user_content(self):
        s='enum Mode: String { case normal = "Normal" }\nText(layer.name)\nlet key = "Save"\nText("Save")'
        r=self.rewrite(s)
        self.assertIn('case normal = "Normal"',r)
        self.assertIn('Text(layer.name)',r)
        self.assertIn('let key = "Save"',r)
        self.assertIn('Text(CN.text("Save"))',r)
    def test_interpolation_and_comments(self):
        s='// Text("Comment")\nText("Undo \\(history.name)")\nText("\\(flag ? "Hide" : "Show") \\(layer.name)")'
        r=self.rewrite(s)
        self.assertTrue(r.startswith('// Text("Comment")'))
        self.assertIn('CN.text("Undo \\(history.name)")',r)
        self.assertEqual(m.decode('"\\(flag ? "Hide" : "Show") \\(layer.name)"'),'{0} {1}')
    def test_dynamic_display(self):
        self.assertEqual(self.rewrite('Text(mode.rawValue).tag(mode)'), 'Text(CN.text(mode.rawValue)).tag(mode)')
    def test_no_overlap(self):
        self.assertEqual(self.rewrite('Button("Save") { Text("Apply") }'), 'Button(CN.text("Save")) { Text(CN.text("Apply")) }')
    def test_placeholders(self):
        for k,v in m.load(ROOT/'translations/zh-CN.json').items(): self.assertEqual(m.placeholders(k),m.placeholders(v),k)
    def test_original_models_unchanged(self):
        base=ROOT/'vendor/Compositor'; built=ROOT/'build/source'
        for f in (base/'Compositor').rglob('*.swift'):
            if f.relative_to(base).as_posix() == 'Compositor/IO/UpdateDriver.swift':
                self.assertFalse((built/f.relative_to(base)).exists())
                continue
            original=f.read_text(); localized=(built/f.relative_to(base)).read_text()
            pattern=r'^\s*case [^\n]*= "[^"\n]+"[^\n]*$'
            self.assertEqual(re.findall(pattern,original,re.M),re.findall(pattern,localized,re.M),str(f))
        for f in (base/'Compositor').rglob('*Manifest*.swift'):
            self.assertEqual(f.read_bytes(),(built/f.relative_to(base)).read_bytes())
    def test_literal_coverage(self):
        missing = m.load(ROOT/'reports/untranslated-ui.json')
        if missing and ALLOW_UNTRANSLATED:
            self.skipTest(str(len(missing))+' new UI strings use English fallback; see untranslated-ui.json')
        self.assertEqual(missing,{})
    def test_bundle_isolation(self):
        self.assertIn('local.compositor.zhcn',(ROOT/'scripts/build.sh').read_text())
        s=(ROOT/'build/source/Compositor/IO/CompositorApplicationDelegate.swift').read_text()
        self.assertNotIn('try self?.updater.start()',s)
    def test_unused_updater_is_removed(self):
        built=ROOT/'build/source'
        for f in (built/'Compositor').rglob('*.swift'):
            self.assertNotRegex(f.read_text(),r'\b(import Sparkle|SPUUpdater|UpdateDriver|UpdaterDelegate)\b',str(f))
        self.assertNotIn('Sparkle',(built/'Compositor.xcodeproj/project.pbxproj').read_text())
        for resolved in built.rglob('Package.resolved'):
            data=m.load(resolved)
            pins=data.get('object', data).get('pins', [])
            self.assertFalse(any(p.get('identity', p.get('package', '')).lower()=='sparkle' for p in pins))
        self.assertNotIn('<key>SU',(built/'Config/Info.plist').read_text())
        self.assertNotIn('$(PRODUCT_BUNDLE_IDENTIFIER)-spks',(built/'Config/Compositor.entitlements').read_text())
        self.assertNotIn('$(PRODUCT_BUNDLE_IDENTIFIER)-spki',(built/'Config/Compositor.entitlements').read_text())
        self.assertIn('com.apple.security.app-sandbox',(built/'Config/Compositor.entitlements').read_text())
        self.assertNotIn('disable-library-validation',(built/'Config/Compositor.entitlements').read_text())
    def test_blend_identifiers(self):
        s=(ROOT/'build/source/Compositor/UI/BlendModePicker.swift').read_text()
        self.assertIn('representedObject = mode.rawValue',s)
        self.assertNotIn('LayerBlendMode(rawValue: $0.title)',s)

class UpstreamUpgradeTests(unittest.TestCase):
    def copies(self, directory):
        vendor=Path(directory)/'vendor'; source=Path(directory)/'source'
        shutil.copytree(ROOT/'vendor/Compositor',vendor)
        return vendor,source
    def test_new_build_and_dependency_version_are_supported(self):
        from upstream_compat import apply_compat
        with tempfile.TemporaryDirectory() as directory:
            vendor,source=self.copies(directory)
            project=vendor/'Compositor.xcodeproj/project.pbxproj'
            project.write_text(re.sub(r'CURRENT_PROJECT_VERSION = [0-9]+;', 'CURRENT_PROJECT_VERSION = 82;', re.sub(r'minimumVersion = [0-9.]+;', 'minimumVersion = 2.11.0;', project.read_text())))
            before=project.read_bytes(); shutil.copytree(vendor,source)
            report=apply_compat(source,vendor)
            self.assertEqual(report['personalBuild'],83)
            self.assertEqual(project.read_bytes(),before)
            prepared=(source/'Compositor.xcodeproj/project.pbxproj').read_bytes()
            apply_compat(source,vendor)
            self.assertEqual((source/'Compositor.xcodeproj/project.pbxproj').read_bytes(),prepared)
    def test_other_dependencies_and_entitlements_are_preserved(self):
        from upstream_compat import apply_compat
        with tempfile.TemporaryDirectory() as directory:
            vendor,source=self.copies(directory)
            lock=vendor/'Compositor.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved'
            value=m.load(lock); value['pins'].append({'identity':'other-library','location':'https://example.org/other','kind':'remoteSourceControl','state':{'revision':'abc','version':'1.0.0'}});m.save(lock,value)
            entitlement=vendor/'Config/Compositor.entitlements';value=plistlib.loads(entitlement.read_bytes());value['com.apple.security.temporary-exception.mach-lookup.global-name'].append('existing.other.service');entitlement.write_bytes(plistlib.dumps(value))
            shutil.copytree(vendor,source);apply_compat(source,vendor)
            self.assertTrue(any(pin.get('identity')=='other-library' for pin in m.load(source/lock.relative_to(vendor))['pins']))
            services=plistlib.loads((source/entitlement.relative_to(vendor)).read_bytes())['com.apple.security.temporary-exception.mach-lookup.global-name']
            original=plistlib.loads(entitlement.read_bytes())['com.apple.security.temporary-exception.mach-lookup.global-name']
            self.assertEqual(services,[service for service in original if service not in ['$(PRODUCT_BUNDLE_IDENTIFIER)-spks','$(PRODUCT_BUNDLE_IDENTIFIER)-spki']])
    def test_unknown_updater_code_stops_before_modifying_files(self):
        from upstream_compat import apply_compat, CompatibilityError
        with tempfile.TemporaryDirectory() as directory:
            vendor,source=self.copies(directory)
            driver=vendor/'Compositor/IO/UpdateDriver.swift';driver.write_text(driver.read_text()+'\nstruct NewUnrelatedFeature {}\n')
            shutil.copytree(vendor,source)
            project=source/'Compositor.xcodeproj/project.pbxproj';before=project.read_bytes()
            with self.assertRaises(CompatibilityError):apply_compat(source,vendor)
            self.assertEqual(project.read_bytes(),before)

if __name__=='__main__':unittest.main(verbosity=2)
