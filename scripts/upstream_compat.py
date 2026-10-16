#!/usr/bin/env python3
"""Structural, fail-closed compatibility changes for the generated build copy.

The pristine vendor snapshot is only read.  No Xcode/macOS utilities or third-party
packages are needed, so the same preparation runs on Linux and macOS.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import plistlib
import re


class CompatibilityError(ValueError):
    """An upstream layout changed in a way that requires a reviewed adapter."""


@dataclass
class _Token:
    value: str
    start: int
    end: int
    quoted: bool = False


@dataclass
class _Node:
    kind: str
    value: object
    start: int
    end: int


@dataclass
class _Entry:
    key: _Token
    value: _Node
    end: int


@dataclass
class _Item:
    value: _Node
    end: int
    comma: bool


def _lex(text):
    """OpenStep tokens with offsets; comments and quoted braces are opaque."""
    result = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0:
                raise CompatibilityError('Unterminated pbxproj comment')
            i = end + 2
        elif text[i] in '{}()=;,':
            result.append(_Token(text[i], i, i + 1))
            i += 1
        elif text[i] == '"':
            start = i
            i += 1
            value = []
            while i < len(text) and text[i] != '"':
                if text[i] == '\\':
                    i += 1
                    if i >= len(text):
                        raise CompatibilityError('Unterminated pbxproj escape')
                    value.append({'n': '\n', 'r': '\r', 't': '\t'}.get(text[i], text[i]))
                else:
                    value.append(text[i])
                i += 1
            if i >= len(text):
                raise CompatibilityError('Unterminated pbxproj string')
            i += 1
            result.append(_Token(''.join(value), start, i, True))
        else:
            start = i
            while i < len(text) and not text[i].isspace() and text[i] not in '{}()=;,"':
                if text.startswith(('//', '/*'), i):
                    break
                i += 1
            if i == start:
                raise CompatibilityError('Unexpected pbxproj token')
            result.append(_Token(text[start:i], start, i))
    return result


class _Parser:
    def __init__(self, text):
        self.tokens = _lex(text)
        self.index = 0

    def take(self, expected=None):
        if self.index >= len(self.tokens):
            raise CompatibilityError('Unexpected end of pbxproj')
        token = self.tokens[self.index]
        if expected is not None and (token.quoted or token.value != expected):
            raise CompatibilityError(f'Expected {expected!r} in pbxproj, got {token.value!r}')
        self.index += 1
        return token

    def peek(self):
        return (self.tokens[self.index].value if not self.tokens[self.index].quoted else None) if self.index < len(self.tokens) else None

    def node(self):
        token = self.take()
        if token.quoted:
            return _Node('atom', token.value, token.start, token.end)
        if token.value == '{':
            entries = {}
            while self.peek() != '}':
                key = self.take()
                if (not key.quoted and key.value in set('{}()=;,')) or key.value in entries:
                    raise CompatibilityError(f'Invalid/duplicate pbxproj key: {key.value}')
                self.take('=')
                value = self.node()
                end = self.take(';').end
                entries[key.value] = _Entry(key, value, end)
            return _Node('dict', entries, token.start, self.take('}').end)
        if token.value == '(':
            items = []
            while self.peek() != ')':
                value = self.node()
                comma = self.peek() == ','
                end = self.take(',').end if comma else value.end
                items.append(_Item(value, end, comma))
                if not comma and self.peek() != ')':
                    raise CompatibilityError('Missing comma in pbxproj array')
            return _Node('array', items, token.start, self.take(')').end)
        if token.value in '}()=;,':
            raise CompatibilityError('Unexpected punctuation in pbxproj value')
        return _Node('atom', token.value, token.start, token.end)


def _parse(text):
    parser = _Parser(text)
    root = parser.node()
    if parser.index != len(parser.tokens) or root.kind != 'dict':
        raise CompatibilityError('Expected one complete pbxproj dictionary')
    return root


def _entry(node, key, kind=None, optional=False):
    if node.kind != 'dict':
        raise CompatibilityError('Expected a pbxproj dictionary')
    entry = node.value.get(key)
    if entry is None:
        if optional:
            return None
        raise CompatibilityError(f'Missing pbxproj field: {key}')
    if kind is not None and entry.value.kind != kind:
        raise CompatibilityError(f'Unexpected pbxproj field type: {key}')
    return entry


def _atom(node, key, optional=False):
    entry = _entry(node, key, 'atom', optional)
    return None if entry is None else entry.value.value


def _objects(root):
    entries = _entry(root, 'objects', 'dict').value.value
    for object_id, entry in entries.items():
        if not re.fullmatch(r'[0-9A-Fa-f]{24}', object_id) or entry.value.kind != 'dict':
            raise CompatibilityError('Unexpected pbxproj object identifier or object value')
        _atom(entry.value, 'isa')
    return entries


def _all_atoms(node):
    if node.kind == 'atom':
        yield node
    elif node.kind == 'dict':
        for entry in node.value.values():
            yield from _all_atoms(entry.value)
    else:
        for item in node.value:
            yield from _all_atoms(item.value)


def _official_sparkle(url):
    if not isinstance(url, str):
        return False
    normalized = url.rstrip('/').lower()
    if normalized.endswith('.git'):
        normalized = normalized[:-4]
    return normalized == 'https://github.com/sparkle-project/sparkle'


def _whole_line(text, start, end):
    """Include indentation/newline only if the removed entry owns its line."""
    left = text.rfind('\n', 0, start) + 1
    right = text.find('\n', end)
    right = len(text) if right < 0 else right
    if not text[left:start].strip() and not text[end:right].strip():
        return left, right + (right < len(text))
    return start, end


def _sparkle_edits(text, root, objects):
    packages = [key for key, entry in objects.items()
                if _atom(entry.value, 'isa') == 'XCRemoteSwiftPackageReference'
                and _official_sparkle(_atom(entry.value, 'repositoryURL', True))]
    products = [key for key, entry in objects.items()
                if _atom(entry.value, 'isa') == 'XCSwiftPackageProductDependency'
                and _atom(entry.value, 'productName', True) == 'Sparkle']
    if not packages and not products:
        return [], []
    if len(packages) != 1 or len(products) != 1:
        raise CompatibilityError('Expected exactly one official Sparkle package and product')
    package, product = packages[0], products[0]
    if _atom(objects[product].value, 'package') != package:
        raise CompatibilityError('Sparkle product does not refer to the official Sparkle package')
    builds = [key for key, entry in objects.items()
              if _atom(entry.value, 'isa') == 'PBXBuildFile'
              and _atom(entry.value, 'productRef', True) == product]
    if len(builds) != 1:
        raise CompatibilityError('Expected exactly one Sparkle PBXBuildFile')
    build = builds[0]
    edits = []
    expected_refs = {build: 1, product: 2, package: 2}
    for object_id, expected in expected_refs.items():
        if sum(atom.value == object_id for atom in _all_atoms(root)) != expected:
            raise CompatibilityError(f'Unexpected Sparkle reference cardinality: {object_id}')
    array_specs = ((build, 'PBXFrameworksBuildPhase', 'files'),
                   (product, 'PBXNativeTarget', 'packageProductDependencies'),
                   (package, 'PBXProject', 'packageReferences'))
    for object_id, owner_type, field_name in array_specs:
        matches = []
        for owner in objects.values():
            if _atom(owner.value, 'isa') != owner_type:
                continue
            field_entry = _entry(owner.value, field_name, 'array', True)
            if field_entry is not None:
                matches.extend(item for item in field_entry.value.value
                               if item.value.kind == 'atom' and item.value.value == object_id)
        if len(matches) != 1:
            raise CompatibilityError(f'Expected one Sparkle reference in {owner_type}.{field_name}')
        item = matches[0]
        if not item.comma:
            raise CompatibilityError('Sparkle array reference must have an explicit comma')
        start, end = _whole_line(text, item.value.start, item.end)
        edits.append((start, end, ''))
    for object_id in (build, product, package):
        entry = objects[object_id]
        start, end = _whole_line(text, entry.key.start, entry.end)
        edits.append((start, end, ''))
    return edits, [build, product, package]


def _target_configurations(objects):
    """Resolve target -> configuration list -> settings, validating every link."""
    result = {}
    applications = []
    for target_id, entry in objects.items():
        target = entry.value
        if _atom(target, 'isa') != 'PBXNativeTarget':
            continue
        if _atom(target, 'productType') == 'com.apple.product-type.application':
            applications.append(target_id)
        config_list_id = _atom(target, 'buildConfigurationList')
        config_list = objects.get(config_list_id)
        if config_list is None or _atom(config_list.value, 'isa') != 'XCConfigurationList':
            raise CompatibilityError('Target has an invalid build configuration list')
        config_items = _entry(config_list.value, 'buildConfigurations', 'array').value.value
        if not config_items:
            raise CompatibilityError('Target has no build configurations')
        configs = {}
        for item in config_items:
            if item.value.kind != 'atom' or item.value.value in configs:
                raise CompatibilityError('Invalid/duplicate target configuration reference')
            config_id = item.value.value
            config = objects.get(config_id)
            if config is None or _atom(config.value, 'isa') != 'XCBuildConfiguration':
                raise CompatibilityError('Invalid target build configuration')
            settings = _entry(config.value, 'buildSettings', 'dict').value
            version = _entry(settings, 'CURRENT_PROJECT_VERSION', 'atom', True)
            if version is not None and not re.fullmatch(r'[0-9]+', version.value.value):
                raise CompatibilityError('CURRENT_PROJECT_VERSION must be a literal integer')
            configs[config_id] = version
        result[target_id] = configs
    if len(applications) != 1:
        raise CompatibilityError('Expected exactly one Compositor application target')
    app = applications[0]
    if _atom(objects[app].value, 'name') != 'Compositor':
        raise CompatibilityError('Unexpected application target name')
    return result, app


def _version_edits(vendor_objects, source_objects):
    baseline_configs, app_id = _target_configurations(vendor_objects)
    source_configs, source_app_id = _target_configurations(source_objects)
    if source_app_id != app_id or baseline_configs.keys() != source_configs.keys():
        raise CompatibilityError('Generated target structure differs from the vendor snapshot')
    app_versions = [entry.value.value for entry in baseline_configs[app_id].values() if entry is not None]
    if len(app_versions) != len(baseline_configs[app_id]) or len(set(app_versions)) != 1:
        raise CompatibilityError('Application configurations must share one numeric build version')
    upstream = int(app_versions[0])
    if upstream < 1:
        raise CompatibilityError('Upstream application build must be positive')
    personal = upstream + 1
    edits = []
    for target_id, configs in baseline_configs.items():
        if configs.keys() != source_configs[target_id].keys():
            raise CompatibilityError('Generated configuration structure differs from vendor')
        for config_id, original in configs.items():
            current = source_configs[target_id][config_id]
            if (original is None) != (current is None):
                raise CompatibilityError('Generated version settings differ from vendor')
            if original is None:
                continue
            if current.value.value not in (original.value.value, str(personal)):
                raise CompatibilityError('Generated build version was changed unexpectedly')
            edits.append((current.value.start, current.value.end, str(personal)))
    return edits, upstream, personal


def _region_edits(text, root, objects):
    project_id = _atom(root, 'rootObject')
    project = objects.get(project_id)
    if project is None or _atom(project.value, 'isa') != 'PBXProject':
        raise CompatibilityError('Invalid pbxproj root project reference')
    regions = _entry(project.value, 'knownRegions', 'array', True)
    if regions is None:
        return [], False
    items = regions.value.value
    if any(item.value.kind != 'atom' for item in items):
        raise CompatibilityError('knownRegions must contain language names')
    if any(item.value.value == 'zh-Hans' for item in items):
        return [], False
    close = regions.value.end - 1
    line_start = text.rfind('\n', 0, close) + 1
    close_indent = text[line_start:close]
    if not close_indent.strip() and '\n' in text[regions.value.start:close]:
        prefix = ''
        if items and not items[-1].comma:
            prefix = ','
            return [(items[-1].value.end, items[-1].value.end, prefix),
                    (line_start, line_start, close_indent + '\t"zh-Hans",\n')], True
        return [(line_start, line_start, close_indent + '\t"zh-Hans",\n')], True
    separator = ', ' if items and not items[-1].comma else ' '
    return [(close, close, separator + '"zh-Hans",')], True


def _apply_edits(text, edits):
    ordered = sorted(edits, key=lambda edit: (edit[0], edit[1]))
    for left, right in zip(ordered, ordered[1:]):
        if left[1] > right[0]:
            raise CompatibilityError('Overlapping compatibility changes')
    for start, end, replacement in reversed(ordered):
        text = text[:start] + replacement + text[end:]
    return text


def _swift_comment_end(text, i):
    if text.startswith('//', i):
        end = text.find('\n', i)
        return len(text) if end < 0 else end
    if text.startswith('/*', i):
        depth = 1
        j = i + 2
        while j < len(text) and depth:
            if text.startswith('/*', j):
                depth += 1
                j += 2
            elif text.startswith('*/', j):
                depth -= 1
                j += 2
            else:
                j += 1
        if depth:
            raise CompatibilityError('Unterminated Swift comment')
        return j
    return None


def _swift_string_end(text, i):
    match = re.match(r'(#+)?("""|")', text[i:])
    if not match:
        return None
    hashes = match.group(1) or ''
    delimiter = match.group(2)
    end_delimiter = delimiter + hashes
    escape = '\\' + hashes
    j = i + len(match.group(0))
    while j < len(text):
        if text.startswith(end_delimiter, j):
            return j + len(end_delimiter)
        if text.startswith(escape + '(', j):
            j = _swift_balanced_end(text, j + len(escape), '(', ')')
        elif text.startswith(escape, j):
            j += len(escape) + 1
        else:
            j += 1
    raise CompatibilityError('Unterminated Swift string')


def _swift_balanced_end(text, i, opening, closing):
    depth = 1
    j = i + 1
    while j < len(text):
        end = _swift_comment_end(text, j)
        if end is None:
            end = _swift_string_end(text, j)
        if end is not None:
            j = end
            continue
        if text[j] == opening:
            depth += 1
        elif text[j] == closing:
            depth -= 1
            if not depth:
                return j + 1
        j += 1
    raise CompatibilityError('Unbalanced Swift update-driver declaration')


def _validate_update_driver(text):
    """Only delete a file containing the two reviewed updater-only types."""
    expected = {'UpdateDriver': 'SPUUserDriver', 'UpdaterDelegate': 'SPUUpdaterDelegate'}
    imports, declarations = set(), set()
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        end = _swift_comment_end(text, i)
        if end is not None:
            i = end
            continue
        imported = re.match(r'import\s+([A-Za-z_]\w*)\b', text[i:])
        if imported:
            name = imported.group(1)
            if name not in {'AppKit', 'Sparkle'} or name in imports:
                raise CompatibilityError(f'Unknown/duplicate import in UpdateDriver.swift: {name}')
            imports.add(name)
            i += imported.end()
            continue
        declaration = re.match(
            r'(?:@MainActor\s+)?final\s+class\s+([A-Za-z_]\w*)\s*:\s*'
            r'NSObject\s*,\s*([A-Za-z_]\w*)\s*\{', text[i:])
        if not declaration:
            raise CompatibilityError('Unknown top-level code in UpdateDriver.swift; review before deleting')
        name, protocol = declaration.groups()
        if expected.get(name) != protocol or name in declarations:
            raise CompatibilityError('Unknown/duplicate update-driver class or protocol')
        declarations.add(name)
        i = _swift_balanced_end(text, i + declaration.end() - 1, '{', '}')
    if declarations != set(expected) or imports != {'AppKit', 'Sparkle'}:
        raise CompatibilityError('UpdateDriver.swift does not match the reviewed updater-only structure')


def _checked_path(base, relative):
    path = base / relative
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError as error:
        raise CompatibilityError('Compatibility path escapes the generated source copy') from error
    return path


def _plist_plan(path, remove_keys=(), remove_services=False):
    try:
        data = plistlib.loads(path.read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise CompatibilityError(f'Cannot read expected plist: {path.name}') from error
    if not isinstance(data, dict):
        raise CompatibilityError(f'Expected dictionary plist: {path.name}')
    removed = []
    for key in remove_keys:
        if key in data:
            del data[key]
            removed.append(key)
    if remove_services:
        key = 'com.apple.security.temporary-exception.mach-lookup.global-name'
        if key in data:
            services = data[key]
            if not isinstance(services, list) or not all(isinstance(item, str) for item in services):
                raise CompatibilityError('mach-lookup entitlement must be an array of service names')
            known = {'$(PRODUCT_BUNDLE_IDENTIFIER)-spks', '$(PRODUCT_BUNDLE_IDENTIFIER)-spki'}
            removed.extend(item for item in services if item in known)
            data[key] = [item for item in services if item not in known]
            if not data[key]:
                del data[key]
    return plistlib.dumps(data, sort_keys=False), removed


def _resolved_plan(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise CompatibilityError('Cannot read Package.resolved') from error
    if not isinstance(data, dict):
        raise CompatibilityError('Package.resolved must be a dictionary')
    container = data.get('object', data)
    if not isinstance(container, dict) or not isinstance(container.get('pins'), list):
        raise CompatibilityError('Unknown Package.resolved pin structure')
    pins = container['pins']
    retained, removed = [], []
    for pin in pins:
        if not isinstance(pin, dict):
            raise CompatibilityError('Invalid Package.resolved pin')
        if _official_sparkle(pin.get('location', pin.get('repositoryURL'))):
            identity = pin.get('identity', pin.get('package', 'Sparkle'))
            if not isinstance(identity, str) or identity.lower() != 'sparkle':
                raise CompatibilityError('Official Sparkle pin has an unexpected identity')
            removed.append(pin)
        else:
            retained.append(pin)
    if len(removed) > 1:
        raise CompatibilityError('Multiple official Sparkle pins require manual review')
    if not removed:
        return path.read_bytes(), 0
    if not retained:
        return None, len(removed)
    container['pins'] = retained
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode(), len(removed)


def apply_compat(source: Path, vendor: Path) -> dict:
    """Prepare generated sources without changing identifiers or the vendor tree.

    All structural checks finish before the first write. Running this twice is
    idempotent: the personal build always derives from the pristine vendor build.
    """
    source, vendor = Path(source).resolve(), Path(vendor).resolve()
    if source == vendor or source in vendor.parents or vendor in source.parents:
        raise CompatibilityError('Generated source and vendor must be separate directory trees')
    relative_project = Path('Compositor.xcodeproj/project.pbxproj')
    project_path = _checked_path(source, relative_project)
    vendor_path = _checked_path(vendor, relative_project)
    vendor_text = vendor_path.read_text(encoding='utf-8')
    text = project_path.read_text(encoding='utf-8')
    vendor_root, root = _parse(vendor_text), _parse(text)
    vendor_objects, objects = _objects(vendor_root), _objects(root)
    edits, removed_objects = _sparkle_edits(text, root, objects)
    # Validate the unmodified snapshot's dependency graph as well, even on a
    # repeated preparation where the generated copy has already been stripped.
    _sparkle_edits(vendor_text, vendor_root, vendor_objects)
    version_edits, upstream, personal = _version_edits(vendor_objects, objects)
    region_edits, added_language = _region_edits(text, root, objects)
    updated_project = _apply_edits(text, edits + version_edits + region_edits)
    _parse(updated_project)
    plans = {project_path: updated_project.encode('utf-8')}
    removed = {'objects': removed_objects, 'files': [], 'infoKeys': [],
               'machLookupServices': [], 'packagePins': 0}
    driver = _checked_path(source, Path('Compositor/IO/UpdateDriver.swift'))
    vendor_driver = _checked_path(vendor, Path('Compositor/IO/UpdateDriver.swift'))
    if vendor_driver.exists():
        _validate_update_driver(vendor_driver.read_text(encoding='utf-8'))
    if driver.exists():
        _validate_update_driver(driver.read_text(encoding='utf-8'))
        plans[driver] = None
        removed['files'].append(str(driver.relative_to(source)))
    info = _checked_path(source, Path('Config/Info.plist'))
    plans[info], removed['infoKeys'] = _plist_plan(info, (
        'SUEnableInstallerLauncherService', 'SUFeedURL', 'SUPublicEDKey', 'SUEnableAutomaticChecks'))
    entitlements = _checked_path(source, Path('Config/Compositor.entitlements'))
    plans[entitlements], removed['machLookupServices'] = _plist_plan(entitlements, remove_services=True)
    for resolved in source.rglob('Package.resolved'):
        resolved = _checked_path(source, resolved.relative_to(source))
        plans[resolved], count = _resolved_plan(resolved)
        removed['packagePins'] += count
        if plans[resolved] is None:
            removed['files'].append(str(resolved.relative_to(source)))
    for path, content in plans.items():
        if content is None:
            path.unlink()
        elif path.read_bytes() != content:
            path.write_bytes(content)
    return {'upstreamBuild': upstream, 'personalBuild': personal,
            'buildSettingsUpdated': len(version_edits), 'addedZhHans': added_language,
            'removed': removed}
