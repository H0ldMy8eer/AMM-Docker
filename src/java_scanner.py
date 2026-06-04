"""
java_scanner.py — Java project scanner for AMM-Docker.

Parses Maven/Gradle build files, Spring Boot application config, and
Java source annotations to profile a Java monolith's dependencies and
module structure. No third-party libraries required.
"""
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict

# ─────────────────────────────────────────────────────────────────────────────
# Dependency → feature mapping
# ─────────────────────────────────────────────────────────────────────────────

# Maven artifactId (lowercase) → set of tags applied to the result dict.
# 'framework' sets result['framework'], 'feature' flips result['features'][key],
# 'db' sets result['db_type'] if not already set.
_ARTIFACT_MAP = {
    # Spring Boot starters
    'spring-boot-starter-web':              {'framework': 'spring-boot', 'feature': 'web'},
    'spring-boot-starter-webflux':          {'framework': 'spring-boot', 'feature': 'webflux'},
    'spring-boot-starter-security':         {'feature': 'security'},
    'spring-boot-starter-data-jpa':         {'feature': 'jpa'},
    'spring-boot-starter-data-redis':       {'feature': 'redis'},
    'spring-boot-starter-data-mongodb':     {'feature': 'mongodb'},
    'spring-boot-starter-actuator':         {'feature': 'actuator'},
    'spring-boot-starter-amqp':             {'feature': 'rabbitmq'},
    'spring-boot-starter-mail':             {'feature': 'mail'},
    'spring-boot-starter-cache':            {'feature': 'cache'},
    'spring-cloud-starter-gateway':         {'feature': 'gateway'},
    'spring-kafka':                         {'feature': 'kafka'},
    # JWT
    'jjwt-api':                             {'feature': 'jwt'},
    'jjwt-impl':                            {'feature': 'jwt'},
    'jjwt-jackson':                         {'feature': 'jwt'},
    'java-jwt':                             {'feature': 'jwt'},
    'nimbus-jose-jwt':                      {'feature': 'jwt'},
    # Database drivers
    'postgresql':                           {'db': 'postgresql'},
    'mysql-connector-j':                    {'db': 'mysql'},
    'mysql-connector-java':                 {'db': 'mysql'},
    'h2':                                   {'db': 'h2'},
    'mssql-jdbc':                           {'db': 'mssql'},
    'mariadb-java-client':                  {'db': 'mariadb'},
    # AWS
    's3':                                   {'feature': 'aws-s3'},
    'aws-java-sdk-s3':                      {'feature': 'aws-s3'},
    'aws-java-sdk-core':                    {'feature': 'aws'},
    # Other
    'lombok':                               {'feature': 'lombok'},
    'mapstruct':                            {'feature': 'mapstruct'},
    'liquibase-core':                       {'feature': 'liquibase'},
    'flyway-core':                          {'feature': 'flyway'},
    'springdoc-openapi-starter-webmvc-ui':  {'feature': 'swagger'},
    'springfox-swagger2':                   {'feature': 'swagger'},
}

# Default feature flags returned when all are absent
_FEATURE_DEFAULTS = {
    'has_web':       False,
    'has_webflux':   False,
    'has_security':  False,
    'has_jwt':       False,
    'has_jpa':       False,
    'has_redis':     False,
    'has_mongodb':   False,
    'has_kafka':     False,
    'has_rabbitmq':  False,
    'has_aws_s3':    False,
    'has_aws':       False,
    'has_lombok':    False,
    'has_liquibase': False,
    'has_flyway':    False,
    'has_swagger':   False,
    'has_actuator':  False,
    'has_gateway':   False,
}

# ─────────────────────────────────────────────────────────────────────────────
# Java source analysis constants
# ─────────────────────────────────────────────────────────────────────────────

# Spring / JPA annotations that determine a class's role
_CONTROLLER_ANNOTATIONS = frozenset({
    'RestController', 'Controller',
    'RestControllerAdvice', 'ControllerAdvice',
})
_SERVICE_ANNOTATIONS  = frozenset({'Service', 'Component'})
_REPO_ANNOTATIONS     = frozenset({'Repository'})
_ENTITY_ANNOTATIONS   = frozenset({'Entity', 'MappedSuperclass'})

# First-level package segments that indicate a *layered* (not domain-driven)
# architecture.  When the majority of sub-packages are layer names, we group
# classes by their class-name prefix instead of package segment.
_LAYER_DIRS = frozenset({
    'controller', 'controllers',
    'service',    'services',
    'repository', 'repositories', 'repo',
    'model',      'models',
    'entity',     'entities',
    'config',     'configuration', 'configs',
    'dto',        'dtos', 'request', 'response',
    'mapper',     'mappers',
    'util',       'utils', 'helper', 'helpers',
    'exception',  'exceptions', 'error', 'errors',
    'security',   'filter', 'filters',
    'event',      'events', 'listener',
    'aspect',     'aop', 'scheduler',
})

# Suffixes stripped when deriving a domain name from a class name
_CLASS_SUFFIXES = (
    'RestController', 'Controller',
    'ServiceImpl', 'Service',
    'RepositoryImpl', 'Repository',
    'Entity', 'Dto', 'Request', 'Response',
    'Mapper', 'Config', 'Configuration',
)

# ─────────────────────────────────────────────────────────────────────────────
# Regex patterns
# ─────────────────────────────────────────────────────────────────────────────

_JAVA_PACKAGE_RE  = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
_JAVA_CLASS_RE    = re.compile(
    r'(?:public|protected|private)?\s*(?:abstract\s+)?'
    r'(?:class|interface|enum)\s+(\w+)',
    re.MULTILINE,
)
_JAVA_ANNOT_RE    = re.compile(
    r'@(RestController|Controller|Service|Repository|Entity|Component'
    r'|Configuration|SpringBootApplication|RestControllerAdvice'
    r'|ControllerAdvice|MappedSuperclass)\b'
)
_JAVA_MAPPING_RE  = re.compile(
    r'@(?:Request|Get|Post|Put|Delete|Patch)Mapping'
    r'(?:\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\'])?'
)

# Gradle dependency coordinates
_GRADLE_DEP_RE    = re.compile(
    r'(?:implementation|api|compile|runtimeOnly|compileOnly)'
    r'\s+["\']([^"\']+)["\']'
)
_GRADLE_JAVA_RE   = re.compile(
    r'(?:sourceCompatibility|javaVersion|java\.sourceCompatibility)'
    r'\s*[=:]\s*(?:JavaVersion\.VERSION_)?["\']?([\d.]+)["\']?'
)
_GRADLE_PLUGIN_RE = re.compile(
    r'["\']org\.springframework\.boot["\']\)?\s+version\s+["\']([^"\']+)["\']'
)

# application.properties patterns
_PROP_PORT_RE     = re.compile(r'^server\.port\s*=\s*(\d+)', re.MULTILINE)
_PROP_DS_URL_RE   = re.compile(r'^spring\.datasource\.url\s*=\s*(jdbc:[^\s]+)', re.MULTILINE)
_PROP_DS_USER_RE  = re.compile(r'^spring\.datasource\.username\s*=\s*(.+)', re.MULTILINE)

# application.yml patterns (2-4 spaces indent is most common)
_YAML_PORT_RE     = re.compile(r'(?m)^\s{2,6}port\s*:\s*(\d+)')
_YAML_DS_URL_RE   = re.compile(r'(?m)^\s+url\s*:\s*(jdbc:[^\s\n]+)')


# ─────────────────────────────────────────────────────────────────────────────
# Build-file parsers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_ns(tag):
    """Strip XML namespace prefix '{uri}tag' → 'tag'."""
    return tag.split('}', 1)[1] if '}' in tag else tag


def _parse_pom_xml(pom_path):
    """
    Parse a Maven pom.xml.

    Returns a dict with keys: raw_deps, java_version, framework,
    spring_boot_version, group_id, artifact_id.
    """
    try:
        tree = ET.parse(pom_path)
    except Exception:
        return {}

    root_el = tree.getroot()
    result = {
        'raw_deps':            [],
        'java_version':        None,
        'framework':           None,
        'spring_boot_version': None,
        'group_id':            None,
        'artifact_id':         None,
    }

    # Top-level metadata and direct children
    for child in root_el:
        t = _strip_ns(child.tag)
        text = (child.text or '').strip()

        if t == 'groupId' and text:
            result['group_id'] = text
        elif t == 'artifactId' and text:
            result['artifact_id'] = text
        elif t == 'properties':
            for prop in child:
                if _strip_ns(prop.tag) == 'java.version' and prop.text:
                    result['java_version'] = prop.text.strip()
        elif t == 'parent':
            sb_found = False
            for pc in child:
                pt = _strip_ns(pc.tag)
                if pt == 'artifactId' and (pc.text or '').strip() == 'spring-boot-starter-parent':
                    sb_found = True
                    result['framework'] = 'spring-boot'
                if pt == 'version' and pc.text:
                    result['spring_boot_version'] = pc.text.strip()
            # If parent is spring-boot but version came before artifactId, keep it
            if not sb_found:
                result['spring_boot_version'] = None

    # All <dependency> elements anywhere in the file
    for dep_el in root_el.iter():
        if _strip_ns(dep_el.tag) != 'dependency':
            continue
        dep = {_strip_ns(c.tag): (c.text or '').strip() for c in dep_el}
        if dep.get('artifactId'):
            result['raw_deps'].append(dep)

    return result


def _parse_build_gradle(gradle_path):
    """
    Parse a Gradle build file (build.gradle or build.gradle.kts) using regex.

    Returns the same shape as _parse_pom_xml.
    """
    try:
        with open(gradle_path, 'r', encoding='utf-8') as fh:
            content = fh.read()
    except Exception:
        return {}

    result = {
        'raw_deps':            [],
        'java_version':        None,
        'framework':           None,
        'spring_boot_version': None,
        'group_id':            None,
        'artifact_id':         None,
    }

    m = _GRADLE_JAVA_RE.search(content)
    if m:
        result['java_version'] = m.group(1)

    m = _GRADLE_PLUGIN_RE.search(content)
    if m:
        result['framework'] = 'spring-boot'
        result['spring_boot_version'] = m.group(1)

    if 'org.springframework.boot' in content and result['framework'] is None:
        result['framework'] = 'spring-boot'

    for m in _GRADLE_DEP_RE.finditer(content):
        coord = m.group(1)
        parts = coord.split(':')
        if len(parts) >= 2:
            dep = {
                'groupId':    parts[0],
                'artifactId': parts[1],
                'version':    parts[2] if len(parts) > 2 else None,
            }
            result['raw_deps'].append(dep)
            if 'spring-boot' in parts[0] and result['framework'] is None:
                result['framework'] = 'spring-boot'

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Application config parser
# ─────────────────────────────────────────────────────────────────────────────

def _db_type_from_url(url):
    u = url.lower()
    if 'postgresql' in u or 'postgres' in u: return 'postgresql'
    if 'mysql' in u:                         return 'mysql'
    if 'mariadb' in u:                       return 'mariadb'
    if ':h2:' in u:                          return 'h2'
    if 'sqlserver' in u or 'mssql' in u:    return 'mssql'
    if 'oracle' in u:                        return 'oracle'
    return None


def _parse_app_config(resources_dir):
    """
    Parse application.properties and/or application.yml.

    Returns: {server_port, db_url, db_type, db_username}
    application.properties takes precedence over .yml when both exist.
    """
    result = {
        'server_port': 8080,
        'db_url':      None,
        'db_type':     None,
        'db_username': None,
    }

    props_path = os.path.join(resources_dir, 'application.properties')
    yml_paths  = [
        os.path.join(resources_dir, 'application.yml'),
        os.path.join(resources_dir, 'application.yaml'),
    ]

    def _apply_props(content):
        m = _PROP_PORT_RE.search(content)
        if m:
            result['server_port'] = int(m.group(1))
        m = _PROP_DS_URL_RE.search(content)
        if m:
            result['db_url']  = m.group(1)
            result['db_type'] = _db_type_from_url(m.group(1))
        m = _PROP_DS_USER_RE.search(content)
        if m:
            result['db_username'] = m.group(1).strip()

    def _apply_yml(content):
        m = _YAML_PORT_RE.search(content)
        if m:
            result['server_port'] = int(m.group(1))
        m = _YAML_DS_URL_RE.search(content)
        if m:
            result['db_url']  = m.group(1).strip()
            result['db_type'] = _db_type_from_url(m.group(1))

    if os.path.isfile(props_path):
        try:
            _apply_props(open(props_path, encoding='utf-8').read())
        except Exception:
            pass
    else:
        for yf in yml_paths:
            if os.path.isfile(yf):
                try:
                    _apply_yml(open(yf, encoding='utf-8').read())
                except Exception:
                    pass
                break

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Java source-file scanner
# ─────────────────────────────────────────────────────────────────────────────

def _parse_java_file(fpath):
    """
    Return a dict describing the first public class/interface in a .java file.

    Keys: package, class_name, annotations, mappings.
    Returns None on read failure.
    """
    try:
        with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except Exception:
        return None

    m = _JAVA_PACKAGE_RE.search(content)
    package = m.group(1) if m else ''

    m = _JAVA_CLASS_RE.search(content)
    class_name = m.group(1) if m else os.path.basename(fpath)[:-5]

    annotations = set(_JAVA_ANNOT_RE.findall(content))
    mappings    = [m.group(1) for m in _JAVA_MAPPING_RE.finditer(content) if m.group(1)]

    return {
        'package':     package,
        'class_name':  class_name,
        'annotations': annotations,
        'mappings':    mappings,
    }


def _find_base_package(classes):
    """
    Return the longest common package prefix shared by all classes.

    E.g. ['com.example.app.auth', 'com.example.app.product'] → 'com.example.app'
    """
    packages = [c['package'] for c in classes if c['package']]
    if not packages:
        return ''

    split = [p.split('.') for p in packages]
    min_len = min(len(p) for p in split)

    common = []
    for i in range(min_len):
        seg = split[0][i]
        if all(p[i] == seg for p in split):
            common.append(seg)
        else:
            break

    return '.'.join(common)


def _extract_domain_from_class_name(class_name):
    """
    Strip well-known suffixes and return a lowercase domain token.

    AuthController → 'auth'
    UserServiceImpl → 'user'
    """
    name = class_name
    for suffix in _CLASS_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[:-len(suffix)]
            break
    return name.lower().strip('_') or class_name.lower()


def _detect_architecture(classes, base_package):
    """
    Return 'layered' if the majority of first sub-package segments are layer
    names (controller, service, …); otherwise return 'domain'.
    """
    bp_depth = len(base_package.split('.')) if base_package else 0
    first_segs = []
    for cls in classes:
        parts = cls['package'].split('.') if cls['package'] else []
        sub = parts[bp_depth:]
        if sub:
            first_segs.append(sub[0].lower())

    if not first_segs:
        return 'domain'
    layer_ratio = sum(1 for s in first_segs if s in _LAYER_DIRS) / len(first_segs)
    return 'layered' if layer_ratio > 0.5 else 'domain'


def _group_into_modules(classes, base_package):
    """
    Group Java classes into logical domain modules.

    Layered arch (controller/, service/, …): groups by class-name prefix.
    Domain-driven arch (auth/, product/, …): groups by package segment.

    Returns: {domain_name: {controllers, services, repositories, entities, other}}
    """
    style   = _detect_architecture(classes, base_package)
    bp_depth = len(base_package.split('.')) if base_package else 0

    buckets = defaultdict(lambda: {
        'controllers': [], 'services': [],
        'repositories': [], 'entities': [], 'other': [],
    })

    for cls in classes:
        parts = cls['package'].split('.') if cls['package'] else []
        sub   = parts[bp_depth:]

        if not sub:
            domain = '_root'
        elif style == 'layered':
            domain = _extract_domain_from_class_name(cls['class_name'])
        else:
            first = sub[0].lower()
            if first in _LAYER_DIRS and len(sub) > 1:
                domain = sub[1].lower()
            elif first in _LAYER_DIRS:
                domain = _extract_domain_from_class_name(cls['class_name'])
            else:
                domain = first

        annots = cls['annotations']
        if annots & _CONTROLLER_ANNOTATIONS:
            buckets[domain]['controllers'].append(cls['class_name'])
        elif annots & _SERVICE_ANNOTATIONS:
            buckets[domain]['services'].append(cls['class_name'])
        elif annots & _REPO_ANNOTATIONS:
            buckets[domain]['repositories'].append(cls['class_name'])
        elif annots & _ENTITY_ANNOTATIONS:
            buckets[domain]['entities'].append(cls['class_name'])
        else:
            buckets[domain]['other'].append(cls['class_name'])

    return dict(buckets)


# ─────────────────────────────────────────────────────────────────────────────
# Feature resolver
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_features(raw_deps):
    """
    Map raw dependency list to feature flags, db_type, and framework string.

    Returns (features_dict, db_type, framework).
    """
    features  = dict(_FEATURE_DEFAULTS)
    db_type   = None
    framework = None

    for dep in raw_deps:
        artifact = dep.get('artifactId', '').lower()
        tags = _ARTIFACT_MAP.get(artifact, {})

        if 'framework' in tags:
            framework = tags['framework']

        feat = tags.get('feature')
        if feat:
            key = 'has_' + feat.replace('-', '_')
            if key in features:
                features[key] = True

        if 'db' in tags and db_type is None:
            db_type = tags['db']

    return features, db_type, framework


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def scan_java_project(root_path):
    """
    Scan a Java/Maven/Gradle project and return its full profile.

    Returns:
        {
            'root':                str,
            'language':            'java',
            'build_tool':          'maven'|'gradle'|'gradle-kts'|None,
            'java_version':        str|None,
            'framework':           'spring-boot'|'unknown'|None,
            'spring_boot_version': str|None,
            'base_package':        str,
            'architecture':        'layered'|'domain',
            'modules': [
                {
                    'name':         str,
                    'type':         'service'|'shared',
                    'controllers':  [str, ...],
                    'services':     [str, ...],
                    'repositories': [str, ...],
                    'entities':     [str, ...],
                },
                ...
            ],
            'features':    {has_security, has_jwt, has_jpa, ...},
            'server_port': int,
            'db_type':     str|None,
            'db_url':      str|None,
            'raw_deps':    [{groupId, artifactId, version?}, ...],
        }
    """
    print(f"☕ [JAVA-SCANNER] Начинаю анализ: {root_path}")

    try:
        entries = set(os.listdir(root_path))
    except OSError:
        entries = set()

    # ── Build file ────────────────────────────────────────────────────────────
    if 'pom.xml' in entries:
        build_tool  = 'maven'
        build_info  = _parse_pom_xml(os.path.join(root_path, 'pom.xml'))
    elif 'build.gradle.kts' in entries:
        build_tool  = 'gradle-kts'
        build_info  = _parse_build_gradle(os.path.join(root_path, 'build.gradle.kts'))
    elif 'build.gradle' in entries:
        build_tool  = 'gradle'
        build_info  = _parse_build_gradle(os.path.join(root_path, 'build.gradle'))
    else:
        build_tool  = None
        build_info  = {}

    raw_deps = build_info.get('raw_deps', [])
    features, db_type_deps, framework_deps = _resolve_features(raw_deps)

    framework           = build_info.get('framework') or framework_deps or 'unknown'
    java_version        = build_info.get('java_version')
    spring_boot_version = build_info.get('spring_boot_version')

    print(f"   ☕ [JAVA-SCANNER] build_tool={build_tool}  framework={framework}"
          f"  java={java_version}  sb_ver={spring_boot_version}")

    # ── Application config ────────────────────────────────────────────────────
    resources_dir = os.path.join(root_path, 'src', 'main', 'resources')
    config = _parse_app_config(resources_dir)

    db_type = config['db_type'] or db_type_deps
    print(f"   ☕ [JAVA-SCANNER] port={config['server_port']}  db={db_type}  url={config['db_url']}")

    # ── Java sources ──────────────────────────────────────────────────────────
    java_src = os.path.join(root_path, 'src', 'main', 'java')
    classes  = []

    if os.path.isdir(java_src):
        for dirpath, _, filenames in os.walk(java_src):
            for fname in filenames:
                if fname.endswith('.java'):
                    info = _parse_java_file(os.path.join(dirpath, fname))
                    if info:
                        classes.append(info)

    print(f"   ☕ [JAVA-SCANNER] Java-файлов: {len(classes)}")

    base_package  = _find_base_package(classes)
    architecture  = _detect_architecture(classes, base_package)
    print(f"   ☕ [JAVA-SCANNER] base_package={base_package!r}  arch={architecture}")

    grouped = _group_into_modules(classes, base_package)

    # ── Build modules list ────────────────────────────────────────────────────
    modules = []
    for domain in sorted(grouped):
        if domain == '_root':
            continue

        contents    = grouped[domain]
        module_type = 'service' if contents['controllers'] else 'shared'

        module = {
            'name':         domain,
            'type':         module_type,
            'controllers':  contents['controllers'],
            'services':     contents['services'],
            'repositories': contents['repositories'],
            'entities':     contents['entities'],
        }
        modules.append(module)

        icon = '🚀' if module_type == 'service' else '📚'
        print(f"   {icon} [JAVA-MODULE] {module_type}: {domain}  "
              f"ctrl={len(contents['controllers'])}  "
              f"svc={len(contents['services'])}  "
              f"repo={len(contents['repositories'])}  "
              f"entity={len(contents['entities'])}")

    active_features = [k for k, v in features.items() if v]
    print(f"   ☕ [JAVA-SCANNER] Фичи: {active_features}")

    return {
        'root':                root_path,
        'language':            'java',
        'build_tool':          build_tool,
        'java_version':        java_version,
        'framework':           framework,
        'spring_boot_version': spring_boot_version,
        'base_package':        base_package,
        'architecture':        architecture,
        'modules':             modules,
        'features':            features,
        'server_port':         config['server_port'],
        'db_type':             db_type,
        'db_url':              config['db_url'],
        'raw_deps':            raw_deps,
    }


_JAVA_IMPORT_RE = re.compile(r'^\s*import\s+([\w.]+)\s*;', re.MULTILINE)


def analyze_java_import_graph(modules, java_root, base_package):
    """
    Build a directed import graph between Java domain modules.

    Walks all .java files under src/main/java/{base_package}/,
    determines each file's domain from its package declaration,
    then looks for import statements that reference other known domains.

    Returns: [{'from': str, 'to': str}, ...]
    """
    module_names = {m['name'] for m in modules}
    bp_parts     = base_package.split('.') if base_package else []
    bp_depth     = len(bp_parts)

    java_src = os.path.join(java_root, 'src', 'main', 'java')
    if not os.path.isdir(java_src):
        return []

    edges = []
    seen  = set()

    for dirpath, _, filenames in os.walk(java_src):
        for fname in filenames:
            if not fname.endswith('.java'):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                content = open(fpath, 'r', encoding='utf-8', errors='replace').read()
            except Exception:
                continue

            # Determine which domain this file belongs to
            m = _JAVA_PACKAGE_RE.search(content)
            if not m:
                continue
            pkg_parts = m.group(1).split('.')
            sub = pkg_parts[bp_depth:]
            if not sub:
                continue
            src_domain = sub[0].lower()
            if src_domain not in module_names:
                continue

            # Collect all imports that reference another domain
            for imp in _JAVA_IMPORT_RE.findall(content):
                if not imp.startswith(base_package + '.'):
                    continue
                imp_sub = imp[len(base_package) + 1:].split('.')
                if not imp_sub:
                    continue
                tgt_domain = imp_sub[0].lower()
                if tgt_domain in module_names and tgt_domain != src_domain:
                    key = (src_domain, tgt_domain)
                    if key not in seen:
                        seen.add(key)
                        edges.append({'from': src_domain, 'to': tgt_domain})

    return edges


if __name__ == '__main__':
    pass
