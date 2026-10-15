#!/usr/bin/env python3
"""Focused regression checks for localization and protection of upstream content."""
import importlib.util, json, subprocess, tempfile, unittest, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
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
        self.assertEqual(m.load(ROOT/'reports/untranslated-ui.json'),{})
    def test_bundle_isolation(self):
        self.assertIn('local.compositor.zhcn',(ROOT/'scripts/build.sh').read_text())
        s=(ROOT/'build/source/Compositor/IO/CompositorApplicationDelegate.swift').read_text()
        self.assertNotIn('try self?.updater.start()',s)
    def test_unused_updater_is_removed(self):
        built=ROOT/'build/source'
        for f in (built/'Compositor').rglob('*.swift'):
            self.assertNotRegex(f.read_text(),r'\b(import Sparkle|SPUUpdater|UpdateDriver|UpdaterDelegate)\b',str(f))
        self.assertNotIn('Sparkle',(built/'Compositor.xcodeproj/project.pbxproj').read_text())
        self.assertFalse((built/'Compositor.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved').exists())
        self.assertNotIn('<key>SU',(built/'Config/Info.plist').read_text())
        self.assertNotIn('temporary-exception.mach-lookup',(built/'Config/Compositor.entitlements').read_text())
        self.assertIn('com.apple.security.app-sandbox',(built/'Config/Compositor.entitlements').read_text())
        self.assertNotIn('disable-library-validation',(built/'Config/Compositor.entitlements').read_text())
    def test_blend_identifiers(self):
        s=(ROOT/'build/source/Compositor/UI/BlendModePicker.swift').read_text()
        self.assertIn('representedObject = mode.rawValue',s)
        self.assertNotIn('LayerBlendMode(rawValue: $0.title)',s)

if __name__=='__main__':unittest.main(verbosity=2)
