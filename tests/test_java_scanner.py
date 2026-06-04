import pytest
import textwrap
import java_scanner
from java_scanner import (
    _parse_pom_xml,
    _parse_build_gradle,
    _parse_app_config,
    _find_base_package,
    _detect_architecture,
    _resolve_features,
    scan_java_project,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared POM / Gradle strings
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_POM = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <project>
      <groupId>com.example</groupId>
      <artifactId>demo</artifactId>
      <parent>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
      </parent>
      <properties>
        <java.version>17</java.version>
      </properties>
      <dependencies>
        <dependency>
          <groupId>org.springframework.boot</groupId>
          <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
          <groupId>org.postgresql</groupId>
          <artifactId>postgresql</artifactId>
        </dependency>
        <dependency>
          <groupId>io.jsonwebtoken</groupId>
          <artifactId>jjwt-api</artifactId>
        </dependency>
        <dependency>
          <groupId>org.springframework.boot</groupId>
          <artifactId>spring-boot-starter-security</artifactId>
        </dependency>
      </dependencies>
    </project>
""")

MINIMAL_GRADLE = textwrap.dedent("""\
    plugins {
        id 'org.springframework.boot' version '3.1.0'
        id 'java'
    }

    sourceCompatibility = '21'

    dependencies {
        implementation 'org.springframework.boot:spring-boot-starter-web'
        implementation 'org.postgresql:postgresql'
        implementation 'io.jsonwebtoken:jjwt-api'
        implementation 'org.springframework.boot:spring-boot-starter-data-jpa'
    }
""")


def _java_file(pkg, class_name, annotation=''):
    return textwrap.dedent(f"""\
        package {pkg};

        {annotation}
        public class {class_name} {{}}
    """)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def maven_project(tmp_path):
    """Layered Spring Boot / Maven project (controller/service/repository/model dirs)."""
    (tmp_path / 'pom.xml').write_text(MINIMAL_POM)

    res = tmp_path / 'src' / 'main' / 'resources'
    res.mkdir(parents=True)
    (res / 'application.properties').write_text(
        'server.port=9090\n'
        'spring.datasource.url=jdbc:postgresql://localhost:5432/mydb\n'
        'spring.datasource.username=admin\n'
    )

    base = tmp_path / 'src' / 'main' / 'java' / 'com' / 'example' / 'demo'
    for layer in ('controller', 'service', 'repository', 'model'):
        (base / layer).mkdir(parents=True, exist_ok=True)

    (base / 'controller' / 'UserController.java').write_text(
        _java_file('com.example.demo.controller', 'UserController', '@RestController')
    )
    (base / 'controller' / 'ProductController.java').write_text(
        _java_file('com.example.demo.controller', 'ProductController', '@RestController')
    )
    (base / 'service' / 'UserService.java').write_text(
        _java_file('com.example.demo.service', 'UserService', '@Service')
    )
    (base / 'service' / 'ProductService.java').write_text(
        _java_file('com.example.demo.service', 'ProductService', '@Service')
    )
    (base / 'repository' / 'UserRepository.java').write_text(
        _java_file('com.example.demo.repository', 'UserRepository', '@Repository')
    )
    (base / 'model' / 'User.java').write_text(
        _java_file('com.example.demo.model', 'User', '@Entity')
    )
    return tmp_path


@pytest.fixture
def gradle_project(tmp_path):
    """Domain-driven Spring Boot / Gradle project (auth/, product/ package dirs)."""
    (tmp_path / 'build.gradle').write_text(MINIMAL_GRADLE)

    res = tmp_path / 'src' / 'main' / 'resources'
    res.mkdir(parents=True)
    (res / 'application.yml').write_text(
        'server:\n'
        '  port: 8090\n'
        'spring:\n'
        '  datasource:\n'
        '    url: jdbc:postgresql://localhost:5432/gradledb\n'
    )

    base = tmp_path / 'src' / 'main' / 'java' / 'com' / 'example'
    (base / 'auth').mkdir(parents=True)
    (base / 'product').mkdir(parents=True)

    (base / 'auth' / 'AuthController.java').write_text(
        _java_file('com.example.auth', 'AuthController', '@RestController')
    )
    (base / 'auth' / 'AuthService.java').write_text(
        _java_file('com.example.auth', 'AuthService', '@Service')
    )
    (base / 'product' / 'ProductController.java').write_text(
        _java_file('com.example.product', 'ProductController', '@RestController')
    )
    (base / 'product' / 'ProductRepository.java').write_text(
        _java_file('com.example.product', 'ProductRepository', '@Repository')
    )
    return tmp_path


# ─────────────────────────────────────────────────────────────────────────────
# TestParsePomXml
# ─────────────────────────────────────────────────────────────────────────────

class TestParsePomXml:
    def test_detects_spring_boot_from_parent(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(MINIMAL_POM)
        result = _parse_pom_xml(str(tmp_path / 'pom.xml'))
        assert result['framework'] == 'spring-boot'

    def test_reads_java_version(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(MINIMAL_POM)
        assert _parse_pom_xml(str(tmp_path / 'pom.xml'))['java_version'] == '17'

    def test_reads_spring_boot_version(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(MINIMAL_POM)
        assert _parse_pom_xml(str(tmp_path / 'pom.xml'))['spring_boot_version'] == '3.2.0'

    def test_reads_group_and_artifact_id(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(MINIMAL_POM)
        result = _parse_pom_xml(str(tmp_path / 'pom.xml'))
        assert result['group_id'] == 'com.example'
        assert result['artifact_id'] == 'demo'

    def test_reads_all_dependencies(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(MINIMAL_POM)
        deps = [d['artifactId'] for d in _parse_pom_xml(str(tmp_path / 'pom.xml'))['raw_deps']]
        assert 'spring-boot-starter-web'       in deps
        assert 'postgresql'                     in deps
        assert 'jjwt-api'                       in deps
        assert 'spring-boot-starter-security'   in deps

    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert _parse_pom_xml(str(tmp_path / 'nonexistent.xml')) == {}

    def test_invalid_xml_returns_empty_dict(self, tmp_path):
        (tmp_path / 'pom.xml').write_text('not xml at all <<<')
        assert _parse_pom_xml(str(tmp_path / 'pom.xml')) == {}

    def test_pom_without_parent_no_framework(self, tmp_path):
        (tmp_path / 'pom.xml').write_text(textwrap.dedent("""\
            <?xml version="1.0"?>
            <project>
              <groupId>com.foo</groupId>
              <artifactId>bar</artifactId>
              <dependencies/>
            </project>
        """))
        result = _parse_pom_xml(str(tmp_path / 'pom.xml'))
        assert result['framework'] is None
        assert result['java_version'] is None


# ─────────────────────────────────────────────────────────────────────────────
# TestParseBuildGradle
# ─────────────────────────────────────────────────────────────────────────────

class TestParseBuildGradle:
    def test_detects_spring_boot_from_plugin(self, tmp_path):
        (tmp_path / 'build.gradle').write_text(MINIMAL_GRADLE)
        assert _parse_build_gradle(str(tmp_path / 'build.gradle'))['framework'] == 'spring-boot'

    def test_reads_java_version(self, tmp_path):
        (tmp_path / 'build.gradle').write_text(MINIMAL_GRADLE)
        assert _parse_build_gradle(str(tmp_path / 'build.gradle'))['java_version'] == '21'

    def test_reads_spring_boot_version(self, tmp_path):
        (tmp_path / 'build.gradle').write_text(MINIMAL_GRADLE)
        assert _parse_build_gradle(str(tmp_path / 'build.gradle'))['spring_boot_version'] == '3.1.0'

    def test_reads_dependencies(self, tmp_path):
        (tmp_path / 'build.gradle').write_text(MINIMAL_GRADLE)
        deps = [d['artifactId'] for d in _parse_build_gradle(str(tmp_path / 'build.gradle'))['raw_deps']]
        assert 'spring-boot-starter-web' in deps
        assert 'postgresql'              in deps

    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert _parse_build_gradle(str(tmp_path / 'nonexistent.gradle')) == {}

    def test_gradle_kts_version_syntax(self, tmp_path):
        (tmp_path / 'build.gradle.kts').write_text(textwrap.dedent("""\
            plugins {
                id("org.springframework.boot") version "3.2.1"
                id("java")
            }
            java.sourceCompatibility = JavaVersion.VERSION_17
            dependencies {
                implementation("org.springframework.boot:spring-boot-starter-web")
            }
        """))
        result = _parse_build_gradle(str(tmp_path / 'build.gradle.kts'))
        assert result['spring_boot_version'] == '3.2.1'
        assert result['framework'] == 'spring-boot'
        assert result['java_version'] == '17'


# ─────────────────────────────────────────────────────────────────────────────
# TestParseAppConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestParseAppConfig:
    def test_reads_port_from_properties(self, tmp_path):
        (tmp_path / 'application.properties').write_text('server.port=9090\n')
        assert _parse_app_config(str(tmp_path))['server_port'] == 9090

    def test_reads_datasource_url_from_properties(self, tmp_path):
        (tmp_path / 'application.properties').write_text(
            'spring.datasource.url=jdbc:postgresql://localhost:5432/mydb\n'
        )
        result = _parse_app_config(str(tmp_path))
        assert result['db_url'] == 'jdbc:postgresql://localhost:5432/mydb'
        assert result['db_type'] == 'postgresql'

    def test_reads_mysql_type(self, tmp_path):
        (tmp_path / 'application.properties').write_text(
            'spring.datasource.url=jdbc:mysql://localhost:3306/db\n'
        )
        assert _parse_app_config(str(tmp_path))['db_type'] == 'mysql'

    def test_reads_port_from_yml(self, tmp_path):
        (tmp_path / 'application.yml').write_text('server:\n  port: 8090\n')
        assert _parse_app_config(str(tmp_path))['server_port'] == 8090

    def test_reads_datasource_url_from_yml(self, tmp_path):
        (tmp_path / 'application.yml').write_text(
            'spring:\n'
            '  datasource:\n'
            '    url: jdbc:postgresql://db:5432/prod\n'
        )
        result = _parse_app_config(str(tmp_path))
        assert result['db_type'] == 'postgresql'
        assert 'prod' in result['db_url']

    def test_properties_beats_yml_for_port(self, tmp_path):
        (tmp_path / 'application.properties').write_text('server.port=1111\n')
        (tmp_path / 'application.yml').write_text('server:\n  port: 9999\n')
        assert _parse_app_config(str(tmp_path))['server_port'] == 1111

    def test_default_port_when_no_config(self, tmp_path):
        assert _parse_app_config(str(tmp_path))['server_port'] == 8080

    def test_db_type_none_when_no_datasource(self, tmp_path):
        (tmp_path / 'application.properties').write_text('server.port=8080\n')
        assert _parse_app_config(str(tmp_path))['db_type'] is None


# ─────────────────────────────────────────────────────────────────────────────
# TestFindBasePackage
# ─────────────────────────────────────────────────────────────────────────────

class TestFindBasePackage:
    def _cls(self, pkg):
        return {'package': pkg, 'class_name': 'X', 'annotations': set(), 'mappings': []}

    def test_common_three_segment_prefix(self):
        classes = [self._cls('com.example.app.auth'),
                   self._cls('com.example.app.product')]
        assert _find_base_package(classes) == 'com.example.app'

    def test_single_class_returns_its_package(self):
        assert _find_base_package([self._cls('com.example')]) == 'com.example'

    def test_no_common_prefix_returns_empty(self):
        classes = [self._cls('com.foo'), self._cls('org.bar')]
        assert _find_base_package(classes) == ''

    def test_empty_list_returns_empty(self):
        assert _find_base_package([]) == ''

    def test_empty_package_strings_ignored(self):
        classes = [self._cls(''), self._cls('com.example')]
        assert _find_base_package(classes) == 'com.example'

    def test_identical_packages(self):
        classes = [self._cls('com.example'), self._cls('com.example')]
        assert _find_base_package(classes) == 'com.example'


# ─────────────────────────────────────────────────────────────────────────────
# TestDetectArchitecture
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectArchitecture:
    def _cls(self, pkg):
        return {'package': pkg, 'class_name': 'X', 'annotations': set(), 'mappings': []}

    def test_layered_majority_of_layer_dirs(self):
        classes = [
            self._cls('com.example.controller'),
            self._cls('com.example.service'),
            self._cls('com.example.repository'),
            self._cls('com.example.model'),
        ]
        assert _detect_architecture(classes, 'com.example') == 'layered'

    def test_domain_non_layer_dirs(self):
        classes = [
            self._cls('com.example.auth'),
            self._cls('com.example.product'),
            self._cls('com.example.order'),
        ]
        assert _detect_architecture(classes, 'com.example') == 'domain'

    def test_empty_classes_returns_domain(self):
        assert _detect_architecture([], 'com.example') == 'domain'

    def test_mixed_majority_wins(self):
        # 3 layer dirs, 1 domain → layered
        classes = [
            self._cls('com.example.controller'),
            self._cls('com.example.service'),
            self._cls('com.example.repository'),
            self._cls('com.example.auth'),
        ]
        assert _detect_architecture(classes, 'com.example') == 'layered'

    def test_exactly_half_layer_is_domain(self):
        # 50% → not > 0.5 → domain
        classes = [
            self._cls('com.example.controller'),
            self._cls('com.example.auth'),
        ]
        assert _detect_architecture(classes, 'com.example') == 'domain'


# ─────────────────────────────────────────────────────────────────────────────
# TestResolveFeatures
# ─────────────────────────────────────────────────────────────────────────────

class TestResolveFeatures:
    def _dep(self, artifact_id):
        return {'artifactId': artifact_id}

    def test_web_feature_and_framework(self):
        features, _, fw = _resolve_features([self._dep('spring-boot-starter-web')])
        assert features['has_web'] is True
        assert fw == 'spring-boot'

    def test_security_feature(self):
        features, _, _ = _resolve_features([self._dep('spring-boot-starter-security')])
        assert features['has_security'] is True

    def test_jpa_feature(self):
        features, _, _ = _resolve_features([self._dep('spring-boot-starter-data-jpa')])
        assert features['has_jpa'] is True

    def test_jwt_feature_from_jjwt(self):
        features, _, _ = _resolve_features([self._dep('jjwt-api')])
        assert features['has_jwt'] is True

    def test_postgresql_db_type(self):
        _, db_type, _ = _resolve_features([self._dep('postgresql')])
        assert db_type == 'postgresql'

    def test_mysql_db_type(self):
        _, db_type, _ = _resolve_features([self._dep('mysql-connector-j')])
        assert db_type == 'mysql'

    def test_aws_s3_feature(self):
        features, _, _ = _resolve_features([self._dep('s3')])
        assert features['has_aws_s3'] is True

    def test_lombok_feature(self):
        features, _, _ = _resolve_features([self._dep('lombok')])
        assert features['has_lombok'] is True

    def test_first_db_wins(self):
        # postgresql first, then h2 — postgresql should win
        _, db_type, _ = _resolve_features([self._dep('postgresql'), self._dep('h2')])
        assert db_type == 'postgresql'

    def test_unknown_dep_produces_no_features(self):
        features, db, fw = _resolve_features([self._dep('some-random-library')])
        assert fw is None
        assert db is None
        assert all(v is False for v in features.values())

    def test_empty_deps_returns_defaults(self):
        features, db, fw = _resolve_features([])
        assert fw is None and db is None
        assert all(v is False for v in features.values())


# ─────────────────────────────────────────────────────────────────────────────
# TestScanJavaProject — integration
# ─────────────────────────────────────────────────────────────────────────────

class TestScanJavaProject:
    def test_result_has_all_required_keys(self, maven_project):
        result = scan_java_project(str(maven_project))
        for key in ('root', 'language', 'build_tool', 'java_version',
                    'framework', 'spring_boot_version', 'base_package',
                    'architecture', 'modules', 'features',
                    'server_port', 'db_type', 'db_url', 'raw_deps'):
            assert key in result, f"Missing key: {key}"

    def test_language_is_java(self, maven_project):
        assert scan_java_project(str(maven_project))['language'] == 'java'

    def test_maven_build_tool(self, maven_project):
        assert scan_java_project(str(maven_project))['build_tool'] == 'maven'

    def test_maven_java_version(self, maven_project):
        assert scan_java_project(str(maven_project))['java_version'] == '17'

    def test_maven_spring_boot_version(self, maven_project):
        assert scan_java_project(str(maven_project))['spring_boot_version'] == '3.2.0'

    def test_maven_framework_spring_boot(self, maven_project):
        assert scan_java_project(str(maven_project))['framework'] == 'spring-boot'

    def test_maven_server_port_from_properties(self, maven_project):
        assert scan_java_project(str(maven_project))['server_port'] == 9090

    def test_maven_db_type_postgresql(self, maven_project):
        assert scan_java_project(str(maven_project))['db_type'] == 'postgresql'

    def test_maven_feature_has_web(self, maven_project):
        assert scan_java_project(str(maven_project))['features']['has_web'] is True

    def test_maven_feature_has_security(self, maven_project):
        assert scan_java_project(str(maven_project))['features']['has_security'] is True

    def test_maven_feature_has_jwt(self, maven_project):
        assert scan_java_project(str(maven_project))['features']['has_jwt'] is True

    def test_maven_detects_user_and_product_modules(self, maven_project):
        names = {m['name'] for m in scan_java_project(str(maven_project))['modules']}
        assert 'user' in names
        assert 'product' in names

    def test_maven_modules_with_controllers_are_services(self, maven_project):
        for mod in scan_java_project(str(maven_project))['modules']:
            if mod['controllers']:
                assert mod['type'] == 'service'

    def test_maven_layered_architecture(self, maven_project):
        assert scan_java_project(str(maven_project))['architecture'] == 'layered'

    def test_gradle_build_tool(self, gradle_project):
        assert scan_java_project(str(gradle_project))['build_tool'] == 'gradle'

    def test_gradle_java_version(self, gradle_project):
        assert scan_java_project(str(gradle_project))['java_version'] == '21'

    def test_gradle_port_from_yml(self, gradle_project):
        assert scan_java_project(str(gradle_project))['server_port'] == 8090

    def test_gradle_db_type_from_yml_url(self, gradle_project):
        assert scan_java_project(str(gradle_project))['db_type'] == 'postgresql'

    def test_gradle_domain_architecture(self, gradle_project):
        assert scan_java_project(str(gradle_project))['architecture'] == 'domain'

    def test_gradle_domain_modules_by_package(self, gradle_project):
        names = {m['name'] for m in scan_java_project(str(gradle_project))['modules']}
        assert 'auth' in names
        assert 'product' in names

    def test_gradle_jpa_feature(self, gradle_project):
        assert scan_java_project(str(gradle_project))['features']['has_jpa'] is True

    def test_empty_project_has_defaults(self, tmp_path):
        result = scan_java_project(str(tmp_path))
        assert result['build_tool'] is None
        assert result['server_port'] == 8080
        assert result['db_type'] is None
        assert result['modules'] == []

    def test_base_package_detected(self, maven_project):
        result = scan_java_project(str(maven_project))
        assert result['base_package'] == 'com.example.demo'
