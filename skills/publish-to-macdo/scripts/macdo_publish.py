#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import webbrowser
from ipaddress import ip_address
from urllib import error, request
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


SCHEMA = "https://mac.do/schemas/tool-manifest-v1.json"
TOP_LEVEL_FIELDS = {
    "schema",
    "name",
    "summary",
    "description",
    "type",
    "categories",
    "tags",
    "primary_url",
    "demo_url",
    "source_url",
    "creator",
    "runtime",
    "access",
    "permissions",
    "created_with",
    "license",
}
CREATOR_FIELDS = {"name", "url"}
RUNTIME_FIELDS = {"framework", "package_manager", "build_command", "output_dir"}
ACCESS_FIELDS = {"pricing", "login_required", "china_reachable"}
SUPPORTED_TYPES = {
    "web",
    "mobile",
    "desktop",
    "browser_extension",
    "cli",
    "api",
    "library",
    "plugin",
    "workflow",
    "bot",
    "agent",
    "dataset",
    "document",
    "other",
}


def main():
    args = parse_args()
    api_base = args.api_base.rstrip("/")
    if args.status_id:
        credential = require_publishing_credential(args, api_base)
        response = fetch_submission_status(api_base, credential, args.status_id)
        print(json.dumps(response, indent=2, ensure_ascii=False))
        return

    project = Path(args.project).expanduser().resolve()
    if not project.exists() or not project.is_dir():
        fail(f"Project directory does not exist: {project}")

    manifest_path = project / "macdo.json"
    manifest = read_manifest(manifest_path)
    detected = detect_project(project)
    manifest = merge_manifest(manifest, args, detected)
    validate_manifest(manifest)
    write_manifest(manifest_path, manifest)

    print(f"Wrote {manifest_path}")
    if args.dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return

    credential = require_publishing_credential(args, api_base)

    response = submit_manifest(api_base, credential, manifest, args.idempotency_key)
    print(json.dumps(response, indent=2, ensure_ascii=False))


def parse_args():
    parser = argparse.ArgumentParser(description="Generate and submit a mac.do manifest payload")
    parser.add_argument("--project", default=".", help="Local project directory")
    parser.add_argument("--api-base", default=os.environ.get("MACDO_API_BASE", "https://app-api.mac.do"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--token-file", default=os.environ.get("MACDO_TOKEN_FILE"))
    parser.add_argument("--no-device-auth", action="store_true",
                        help="Fail instead of starting browser/device authorization when no credential exists")
    parser.add_argument("--primary-url", default=None)
    parser.add_argument("--demo-url", default=None)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--type", choices=sorted(SUPPORTED_TYPES), default=None)
    parser.add_argument("--framework", default=None)
    parser.add_argument("--package-manager", default=None)
    parser.add_argument("--build-command", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--creator-name", default=None)
    parser.add_argument("--creator-url", default=None)
    parser.add_argument("--status-id", default=None, help="Fetch an existing submission status by id")
    parser.add_argument("--idempotency-key", default=os.environ.get("MACDO_IDEMPOTENCY_KEY"),
                        help="Reuse this key to safely retry the same submission")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def require_publishing_credential(args, api_base):
    api_key = args.api_key or os.environ.get("MACDO_API_KEY")
    if api_key:
        return api_key
    env_token = os.environ.get("MACDO_PUBLISHING_TOKEN")
    if env_token:
        return env_token
    cached_token = read_cached_token(args, api_base)
    if cached_token:
        return cached_token
    if args.no_device_auth:
        fail("A mac.do publishing credential is required. Sign in once with device authorization or set MACDO_API_KEY.")
    return authorize_device(args, api_base)


def token_file(args):
    if args.token_file:
        return Path(args.token_file).expanduser()
    return Path.home() / ".macdo" / "publishing-token.json"


def read_cached_token(args, api_base):
    path = token_file(args)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("api_base") != api_base:
        return None
    token = payload.get("access_token")
    return token if isinstance(token, str) and token.strip() else None


def write_cached_token(args, api_base, token, scope):
    path = token_file(args)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "api_base": api_base,
        "access_token": token,
        "token_type": "Bearer",
        "scope": scope,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def authorize_device(args, api_base):
    start = post_json(f"{api_base}/api/publishing-authorizations/device", {
        "client_name": "publish-to-macdo skill",
    })
    device_code = start.get("device_code")
    verification_uri = start.get("verification_uri")
    verification_uri_complete = start.get("verification_uri_complete") or verification_uri
    user_code = start.get("user_code")
    expires_in = int(start.get("expires_in") or 600)
    interval = max(1, int(start.get("interval") or 3))
    if not device_code or not verification_uri or not user_code:
        fail("mac.do did not return a complete device authorization response")

    print("Authorize mac.do publishing:")
    print(f"  Open: {verification_uri_complete}")
    print(f"  Code: {user_code}")
    if not os.environ.get("MACDO_NO_BROWSER"):
        try:
            webbrowser.open(verification_uri_complete)
        except Exception:
            pass

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = post_json_allow_error(f"{api_base}/api/publishing-authorizations/token", {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
        })
        if "access_token" in response:
            token = response["access_token"]
            write_cached_token(args, api_base, token, response.get("scope"))
            print(f"mac.do publishing authorized. Token saved to {token_file(args)}")
            return token
        error_code = response.get("error")
        if error_code == "authorization_pending":
            continue
        if error_code == "slow_down":
            interval += 1
            continue
        fail(response.get("error_description") or f"Device authorization failed: {error_code}")
    fail("Device authorization timed out before approval")


def post_json(url, payload):
    response = post_json_allow_error(url, payload)
    if "error" in response:
        fail(response.get("error_description") or response["error"])
    return response


def post_json_allow_error(url, payload):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "publish-to-macdo-skill/0.1",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            fail(f"mac.do authorization failed with HTTP {exc.code}: {detail}")
    except error.URLError as exc:
        fail(f"mac.do authorization failed: {exc.reason}")


def read_manifest(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid existing macdo.json: {exc}")


def detect_project(project):
    package = read_package_json(project / "package.json")
    dependencies = {}
    if package:
        dependencies.update(package.get("dependencies", {}))
        dependencies.update(package.get("devDependencies", {}))

    project_type = "other"
    framework = "unknown"
    package_manager = detect_package_manager(project) or ("npm" if package else None)
    build_command = detect_build_command(package, package_manager)
    output_dir = None
    description = package.get("description") if package else None
    name = package.get("name") if package else project.name

    extension_manifest = read_package_json(project / "manifest.json")
    if extension_manifest and extension_manifest.get("manifest_version"):
        project_type = "browser_extension"
        framework = "browser-extension"
        output_dir = "."
        name = extension_manifest.get("name") or name
        description = description or extension_manifest.get("description")
    elif has_any(project, "android", "ios") or (project / "pubspec.yaml").exists() or "react-native" in dependencies or "expo" in dependencies:
        project_type = "mobile"
        framework = detect_mobile_framework(project, dependencies)
        package_manager = package_manager or detect_mobile_package_manager(project)
        build_command = build_command or detect_mobile_build_command(framework)
        mobile = detect_mobile_metadata(project)
        name = mobile.get("name") or name
        description = description or mobile.get("description")
    elif "electron" in dependencies or (project / "src-tauri").exists() or (project / "tauri.conf.json").exists():
        project_type = "desktop"
        framework = "tauri" if (project / "src-tauri").exists() or (project / "tauri.conf.json").exists() else "electron"
        output_dir = "dist"
    elif is_node_web(project, dependencies):
        project_type = "web"
        framework = detect_node_web_framework(project, dependencies)
        output_dir = detect_output_dir(framework)
    elif package and package.get("bin"):
        project_type = "cli"
        framework = "node-cli"
    elif package and (package.get("main") or package.get("module") or package.get("types")):
        project_type = "library"
        framework = "node-package"
    elif is_python_project(project):
        python = detect_python_project(project)
        project_type = python["type"]
        framework = python["framework"]
        package_manager = python["package_manager"]
        build_command = python["build_command"]
        description = description or python["description"]
        name = python["name"] or name
    elif (project / "pom.xml").exists() or (project / "build.gradle").exists() or (project / "build.gradle.kts").exists():
        java = detect_java_project(project)
        project_type = java["type"]
        framework = java["framework"]
        package_manager = java["package_manager"]
        build_command = java["build_command"]
        name = java.get("name") or name
        description = description or java.get("description")
    elif (project / "Cargo.toml").exists():
        rust = detect_rust_project(project)
        project_type = rust["type"]
        framework = rust["framework"]
        package_manager = "cargo"
        build_command = "cargo build --release"
        name = rust.get("name") or name
        description = description or rust.get("description")
    elif (project / "go.mod").exists():
        go = detect_go_project(project)
        project_type = go["type"]
        framework = go["framework"]
        package_manager = "go"
        build_command = "go build ./..."
        name = go.get("name") or name
        description = description or go.get("description")
    elif has_workflow_files(project):
        project_type = "workflow"
        framework = "workflow"

    return {
        "type": project_type,
        "name": titleize(name),
        "summary": description,
        "description": description,
        "runtime": {
            "framework": framework,
            "package_manager": package_manager,
            "build_command": build_command,
            "output_dir": output_dir,
        },
    }


def read_package_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def read_text(path, limit=80_000):
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def has_any(project, *names):
    return any((project / name).exists() for name in names)


def is_node_web(project, dependencies):
    return (
        "next" in dependencies
        or "astro" in dependencies
        or "vite" in dependencies
        or "react" in dependencies
        or (project / "next.config.js").exists()
        or (project / "next.config.mjs").exists()
        or (project / "astro.config.mjs").exists()
        or (project / "vite.config.js").exists()
        or (project / "vite.config.ts").exists()
        or (project / "index.html").exists()
    )


def detect_node_web_framework(project, dependencies):
    if "next" in dependencies or (project / "next.config.js").exists() or (project / "next.config.mjs").exists():
        return "next"
    if "astro" in dependencies or (project / "astro.config.mjs").exists():
        return "astro"
    if "vite" in dependencies or (project / "vite.config.js").exists() or (project / "vite.config.ts").exists():
        return "vite"
    if "react" in dependencies:
        return "react"
    if (project / "index.html").exists():
        return "static-html"
    return "web"


def detect_mobile_framework(project, dependencies):
    if (project / "pubspec.yaml").exists():
        return "flutter"
    if "react-native" in dependencies:
        return "react-native"
    if "expo" in dependencies:
        return "expo"
    if (project / "android").exists() and (project / "ios").exists():
        return "native-mobile"
    if (project / "android").exists():
        return "android"
    if (project / "ios").exists():
        return "ios"
    return "mobile"


def detect_mobile_package_manager(project):
    if (project / "pubspec.yaml").exists():
        return "flutter"
    if (project / "android" / "gradlew").exists() or (project / "build.gradle").exists() or (project / "build.gradle.kts").exists():
        return "gradle"
    if list(project.glob("*.xcodeproj")) or list(project.glob("*.xcworkspace")):
        return "xcode"
    return None


def detect_mobile_build_command(framework):
    return {
        "flutter": "flutter build",
        "react-native": "npx react-native build",
        "expo": "npx expo export",
        "android": "./gradlew assembleRelease",
    }.get(framework)


def detect_mobile_metadata(project):
    pubspec = read_text(project / "pubspec.yaml")
    if pubspec:
        return {
            "name": extract_yaml_string(pubspec, "name"),
            "description": extract_yaml_string(pubspec, "description"),
        }
    return {}


def is_python_project(project):
    return any((project / name).exists() for name in ("pyproject.toml", "setup.py", "requirements.txt", "Pipfile"))


def detect_python_project(project):
    pyproject = read_text(project / "pyproject.toml")
    requirements = read_text(project / "requirements.txt")
    setup = read_text(project / "setup.py")
    combined = (pyproject + "\n" + requirements + "\n" + setup).lower()
    package_manager = "poetry" if "[tool.poetry]" in combined else "pip"
    name = extract_toml_string(pyproject, "name")
    description = extract_toml_string(pyproject, "description")
    if any(marker in combined for marker in ("fastapi", "flask", "django", "litestar", "starlite")):
        framework = first_marker(combined, ["fastapi", "flask", "django", "litestar"])
        return {
            "type": "api",
            "framework": framework,
            "package_manager": package_manager,
            "build_command": None,
            "name": name,
            "description": description,
        }
    if any(marker in combined for marker in ("streamlit", "gradio", "dash")):
        framework = first_marker(combined, ["streamlit", "gradio", "dash"])
        return {
            "type": "web",
            "framework": framework,
            "package_manager": package_manager,
            "build_command": None,
            "name": name,
            "description": description,
        }
    if any(marker in combined for marker in ("typer", "click", "argparse")):
        return {
            "type": "cli",
            "framework": "python-cli",
            "package_manager": package_manager,
            "build_command": None,
            "name": name,
            "description": description,
        }
    if any(marker in combined for marker in ("langchain", "llama-index", "crewai", "autogen")):
        return {
            "type": "agent",
            "framework": first_marker(combined, ["langchain", "llama-index", "crewai", "autogen"]),
            "package_manager": package_manager,
            "build_command": None,
            "name": name,
            "description": description,
        }
    return {
        "type": "library",
        "framework": "python-package",
        "package_manager": package_manager,
        "build_command": "python -m build" if "build-system" in combined else None,
        "name": name,
        "description": description,
    }


def detect_java_project(project):
    pom = read_text(project / "pom.xml")
    gradle = read_text(project / "build.gradle") + "\n" + read_text(project / "build.gradle.kts")
    combined = (pom + "\n" + gradle).lower()
    metadata = parse_pom_metadata(project / "pom.xml") if (project / "pom.xml").exists() else {}
    package_manager = "maven" if (project / "pom.xml").exists() else "gradle"
    build_command = "./mvnw package" if (project / "mvnw").exists() else "mvn package"
    if package_manager == "gradle":
        build_command = "./gradlew build" if (project / "gradlew").exists() else "gradle build"
    base = {
        "package_manager": package_manager,
        "build_command": build_command,
        "name": metadata.get("name"),
        "description": metadata.get("description"),
    }
    if "spring-boot" in combined or "org.springframework.boot" in combined:
        return dict(base, type="api", framework="spring-boot")
    if "javafx" in combined:
        return dict(base, type="desktop", framework="javafx")
    return dict(base, type="library", framework="java")


def detect_rust_project(project):
    cargo = read_text(project / "Cargo.toml").lower()
    original = read_text(project / "Cargo.toml")
    metadata = {
        "name": extract_toml_string(original, "name"),
        "description": extract_toml_string(original, "description"),
    }
    if "tauri" in cargo:
        return dict(metadata, type="desktop", framework="tauri")
    if "[[bin]]" in cargo or "clap" in cargo:
        return dict(metadata, type="cli", framework="rust-cli")
    if "axum" in cargo or "actix-web" in cargo or "rocket" in cargo:
        return dict(metadata, type="api", framework=first_marker(cargo, ["axum", "actix-web", "rocket"]))
    return dict(metadata, type="library", framework="rust-crate")


def detect_go_project(project):
    gomod = read_text(project / "go.mod").lower()
    module = extract_go_module(read_text(project / "go.mod"))
    metadata = {"name": module.split("/")[-1] if module else None}
    if any(marker in gomod for marker in ("gin-gonic", "gofiber", "echo", "grpc")):
        return dict(metadata, type="api", framework=first_marker(gomod, ["gin", "fiber", "echo", "grpc"]))
    if (project / "cmd").exists():
        return dict(metadata, type="cli", framework="go-cli")
    return dict(metadata, type="library", framework="go-module")


def has_workflow_files(project):
    return any(
        path.exists()
        for path in (
            project / ".github" / "workflows",
            project / "n8n.json",
            project / "workflow.json",
            project / "openapi.yaml",
            project / "openapi.json",
        )
    )


def extract_toml_string(text, key):
    prefix = key + " = "
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
            if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
                return value[1:-1]
    return None


def extract_yaml_string(text, key):
    prefix = key + ":"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
            if not value:
                return None
            if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
                return value[1:-1]
            return value
    return None


def extract_go_module(text):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("module "):
            return stripped[len("module "):].strip()
    return None


def parse_pom_metadata(path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return {}

    def child_text(name):
        for child in root:
            if child.tag.rsplit("}", 1)[-1] == name and child.text:
                return child.text.strip()
        return None

    return {
        "name": child_text("name") or child_text("artifactId"),
        "description": child_text("description"),
    }


def first_marker(text, markers):
    for marker in markers:
        if marker in text:
            return marker
    return markers[0]


def detect_package_manager(project):
    if (project / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (project / "yarn.lock").exists():
        return "yarn"
    if (project / "bun.lockb").exists() or (project / "bun.lock").exists():
        return "bun"
    if (project / "package-lock.json").exists():
        return "npm"
    return None


def detect_build_command(package, package_manager):
    if not package:
        return None
    scripts = package.get("scripts", {})
    if "build" not in scripts:
        return None
    manager = package_manager or "npm"
    if manager == "npm":
        return "npm run build"
    return f"{manager} build"


def detect_output_dir(framework):
    return {
        "next": ".next",
        "astro": "dist",
        "vite": "dist",
        "react": "dist",
        "static-html": ".",
    }.get(framework)


def merge_manifest(existing, args, detected):
    manifest = dict(existing)
    manifest.setdefault("schema", SCHEMA)
    manifest["type"] = first_present(args.type, manifest.get("type"), detected.get("type"), "other")
    manifest["name"] = first_present(args.name, manifest.get("name"), detected.get("name"))
    manifest["summary"] = first_present(args.summary, manifest.get("summary"), detected.get("summary"))
    manifest["description"] = first_present(args.description, manifest.get("description"), detected.get("description"), manifest.get("summary"))
    primary_url = first_present(args.primary_url, args.demo_url, manifest.get("primary_url"), manifest.get("demo_url"))
    if primary_url:
        manifest["primary_url"] = primary_url
    manifest["source_url"] = first_present(args.source_url, manifest.get("source_url"))
    manifest.setdefault("categories", ["productivity"])
    manifest.setdefault("tags", ["vibe-coding"])
    manifest.setdefault("permissions", [])
    manifest.setdefault("created_with", ["Codex"])
    manifest.setdefault("license", "unknown")

    creator = dict(manifest.get("creator") or {})
    creator["name"] = first_present(args.creator_name, creator.get("name"), "Unknown creator")
    if args.creator_url or creator.get("url"):
        creator["url"] = first_present(args.creator_url, creator.get("url"))
    manifest["creator"] = creator

    runtime = dict(detected.get("runtime") or {})
    runtime.update(manifest.get("runtime") or {})
    runtime["framework"] = first_present(args.framework, runtime.get("framework"))
    runtime["package_manager"] = first_present(args.package_manager, runtime.get("package_manager"))
    runtime["build_command"] = first_present(args.build_command, runtime.get("build_command"))
    runtime["output_dir"] = first_present(args.output_dir, runtime.get("output_dir"))
    manifest["runtime"] = {key: value for key, value in runtime.items() if value}

    access = dict(manifest.get("access") or {})
    access.setdefault("pricing", "free")
    access.setdefault("login_required", False)
    access.setdefault("china_reachable", "unknown")
    manifest["access"] = access
    return {key: value for key, value in manifest.items() if value is not None}


def first_present(*values):
    for value in values:
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        elif value is not None:
            return value
    return None


def validate_manifest(manifest):
    required = ["schema", "name", "summary", "description", "type"]
    missing = [key for key in required if not manifest.get(key)]
    if not manifest.get("primary_url") and not manifest.get("demo_url"):
        missing.append("primary_url")
    if missing:
        fail("Missing required manifest fields: " + ", ".join(missing))
    validate_allowed_fields(manifest, "manifest", TOP_LEVEL_FIELDS)
    validate_allowed_fields(manifest.get("creator"), "creator", CREATOR_FIELDS)
    validate_allowed_fields(manifest.get("runtime"), "runtime", RUNTIME_FIELDS)
    validate_allowed_fields(manifest.get("access"), "access", ACCESS_FIELDS)
    if manifest.get("schema") != SCHEMA:
        fail(f"schema must be {SCHEMA}")
    if manifest.get("type") not in SUPPORTED_TYPES:
        fail("type must be one of: " + ", ".join(sorted(SUPPORTED_TYPES)))
    validate_list_limit(manifest.get("categories"), "categories", 6)
    validate_list_limit(manifest.get("tags"), "tags", 12)
    validate_list_limit(manifest.get("permissions"), "permissions", 12)
    validate_list_limit(manifest.get("created_with"), "created_with", 8)
    access = manifest.get("access") or {}
    validate_enum(access.get("pricing"), "access.pricing", {"free", "freemium", "paid", "unknown"})
    validate_enum(access.get("china_reachable"), "access.china_reachable", {"yes", "no", "partial", "unknown"})
    validate_public_http_url(manifest.get("primary_url"), "primary_url")
    validate_public_http_url(manifest.get("demo_url"), "demo_url")
    validate_public_http_url(manifest.get("source_url"), "source_url")
    validate_public_http_url((manifest.get("creator") or {}).get("url"), "creator.url")


def validate_allowed_fields(value, label, allowed):
    if value is None:
        return
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        fail(f"Unknown {label} fields: " + ", ".join(unknown))


def validate_list_limit(value, field, limit):
    if value is None:
        return
    if not isinstance(value, list):
        fail(f"{field} must be an array")
    if len(value) > limit:
        fail(f"{field} must contain {limit} items or fewer")


def validate_enum(value, field, allowed):
    if value is None:
        return
    if value not in allowed:
        fail(f"{field} must be one of: " + ", ".join(sorted(allowed)))


def validate_public_http_url(value, field):
    if not value:
        return
    if len(value) > 500:
        fail(f"{field} must be 500 characters or fewer")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        fail(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        fail(f"{field} must not include username or password information")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or "." not in host:
        fail(f"{field} must use a public host")
    try:
        if not ip_address(host).is_global:
            fail(f"{field} must use a public host")
    except ValueError:
        pass


def write_manifest(path, manifest):
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def submit_manifest(api_base, credential, manifest, idempotency_key):
    body = json.dumps(manifest).encode("utf-8")
    retry_key = idempotency_key or default_idempotency_key(manifest)
    req = request.Request(
        f"{api_base}/api/submissions",
        data=body,
        headers={
            "Authorization": f"Bearer {credential}",
            "Idempotency-Key": retry_key,
            "Content-Type": "application/json",
            "User-Agent": "publish-to-macdo-skill/0.1",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        fail(format_http_error(exc.code, detail))
    except error.URLError as exc:
        fail(f"Submission failed: {exc.reason}")


def default_idempotency_key(manifest):
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"skill-{digest}"


def fetch_submission_status(api_base, credential, submission_id):
    req = request.Request(
        f"{api_base}/api/submissions/{submission_id}",
        headers={
            "Authorization": f"Bearer {credential}",
            "User-Agent": "publish-to-macdo-skill/0.1",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        fail(format_http_error(exc.code, detail))
    except error.URLError as exc:
        fail(f"Status lookup failed: {exc.reason}")


def format_http_error(status_code, body):
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return f"Submission failed with HTTP {status_code}: {body}"

    message = payload.get("message") or body
    details = payload.get("details") or []
    request_id = payload.get("request_id")
    parts = [f"Submission failed with HTTP {status_code}: {message}"]
    if details:
        parts.append("Details: " + "; ".join(str(detail) for detail in details))
    if request_id:
        parts.append(f"Request ID: {request_id}")
    return "\n".join(parts)


def titleize(value):
    if not value:
        return value
    cleaned = value.replace("-", " ").replace("_", " ").strip()
    if " " in cleaned and any(character.isupper() for character in cleaned):
        return cleaned
    return " ".join(part.capitalize() for part in cleaned.split())


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
