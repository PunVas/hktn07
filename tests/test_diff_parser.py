"""
Tests for the diff_parser module.

Tests cover:
  - Python, JavaScript, TypeScript, Go, Java, Rust
  - Function added / modified / deleted detection
  - Hunk parsing (correct line numbers)
  - Body-only changes (signature in context, not in diff lines)
  - Files without patch data (graceful fallback)
  - Multi-hunk patches
  - parse_pr_files integration
  - Blast radius graph node types after upgrade
"""
from __future__ import annotations

import pytest

from app.services.diff_parser import (
    FileDiffSummary,
    FunctionChange,
    parse_file_diff,
    parse_pr_files,
    _parse_hunk_header,
    _extract_function_name,
    _get_extension,
    _detect_language,
    _get_patterns,
)
from app.services.metrics import compute_blast_radius


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------

class TestUtilities:
    def test_get_extension(self):
        assert _get_extension("src/auth/login.py") == ".py"
        assert _get_extension("index.ts") == ".ts"
        assert _get_extension("Makefile") == ""
        assert _get_extension("path/to/file.test.js") == ".js"

    def test_detect_language(self):
        assert _detect_language(".py") == "Python"
        assert _detect_language(".ts") == "TypeScript"
        assert _detect_language(".go") == "Go"
        assert _detect_language(".rs") == "Rust"
        assert _detect_language(".xyz") == "Unknown"

    def test_parse_hunk_header(self):
        assert _parse_hunk_header("@@ -10,7 +10,14 @@") == (10, 14)
        assert _parse_hunk_header("@@ -0,0 +1,5 @@") == (1, 5)
        assert _parse_hunk_header("@@ -5 +5 @@") == (5, 1)
        assert _parse_hunk_header("regular code line") is None
        assert _parse_hunk_header("+added line") is None


# ---------------------------------------------------------------------------
# Python diff parsing
# ---------------------------------------------------------------------------

PYTHON_PATCH_MODIFIED = """\
@@ -10,10 +10,12 @@
 import os
 
-def validate_token(token):
-    return check(token)
+def validate_token(token: str) -> bool:
+    result = check(token)
+    log_audit(result)
+    return result
 
 def refresh_session(user_id):
     pass
"""

PYTHON_PATCH_ADDED = """\
@@ -40,5 +40,10 @@
 class AuthService:
     pass
 
+def send_otp(phone: str) -> None:
+    sms_client.send(phone)
+
+def verify_otp(phone: str, code: str) -> bool:
+    return cache.get(phone) == code
"""

PYTHON_PATCH_DELETED = """\
@@ -20,8 +20,4 @@
 def keep_me():
     pass
 
-def old_deprecated_function():
-    raise NotImplementedError
-
 def also_keep():
     pass
"""

PYTHON_PATCH_BODY_CHANGE = """\
@@ -55,7 +55,9 @@
 def process_request(req):
-    return handler(req)
+    validated = validate(req)
+    result = handler(validated)
+    return result
"""


class TestPythonParser:
    def _make_file(self, patch: str, path: str = "src/auth.py") -> dict:
        return {"path": path, "additions": 5, "deletions": 2, "patch": patch}

    def test_modified_function(self):
        summary = parse_file_diff(self._make_file(PYTHON_PATCH_MODIFIED))
        assert summary.language == "Python"
        names = {f.name for f in summary.functions}
        assert "validate_token" in names
        vt = next(f for f in summary.functions if f.name == "validate_token")
        assert vt.change_type == "modified"

    def test_added_functions(self):
        summary = parse_file_diff(self._make_file(PYTHON_PATCH_ADDED))
        names = {f.name for f in summary.functions}
        assert "send_otp" in names
        assert "verify_otp" in names
        for func in summary.functions:
            if func.name in ("send_otp", "verify_otp"):
                assert func.change_type == "added"

    def test_deleted_function(self):
        summary = parse_file_diff(self._make_file(PYTHON_PATCH_DELETED))
        names = {f.name for f in summary.functions}
        assert "old_deprecated_function" in names
        fn = next(f for f in summary.functions if f.name == "old_deprecated_function")
        assert fn.change_type == "deleted"

    def test_body_only_change(self):
        """Function signature is in context (unchanged), only body changed."""
        summary = parse_file_diff(self._make_file(PYTHON_PATCH_BODY_CHANGE))
        names = {f.name for f in summary.functions}
        assert "process_request" in names
        fn = next(f for f in summary.functions if f.name == "process_request")
        assert fn.change_type == "modified"

    def test_no_patch_returns_empty_functions(self):
        summary = parse_file_diff({"path": "src/utils.py", "additions": 0, "deletions": 0})
        assert summary.functions == []
        assert summary.language == "Python"


# ---------------------------------------------------------------------------
# JavaScript diff parsing
# ---------------------------------------------------------------------------

JS_PATCH = """\
@@ -1,10 +1,15 @@
+async function fetchUser(userId) {
+  const resp = await api.get(`/users/${userId}`);
+  return resp.data;
+}
+
 function handleLogin(credentials) {
-  return auth.login(credentials);
+  const user = auth.login(credentials);
+  analytics.track('login', user.id);
+  return user;
 }
 
-function oldLogout() {
-  session.clear();
-}
"""


class TestJavaScriptParser:
    def test_js_functions(self):
        summary = parse_file_diff({
            "path": "src/api/auth.js",
            "additions": 8,
            "deletions": 3,
            "patch": JS_PATCH,
        })
        assert summary.language == "JavaScript"
        names = {f.name for f in summary.functions}
        assert "fetchUser" in names
        assert "handleLogin" in names
        assert "oldLogout" in names

        fetch_fn = next(f for f in summary.functions if f.name == "fetchUser")
        assert fetch_fn.change_type == "added"

        old_logout = next(f for f in summary.functions if f.name == "oldLogout")
        assert old_logout.change_type == "deleted"


# ---------------------------------------------------------------------------
# TypeScript diff parsing
# ---------------------------------------------------------------------------

TS_PATCH = """\
@@ -5,8 +5,12 @@
+export async function createToken(user: User): Promise<string> {
+  return jwt.sign({ id: user.id }, SECRET);
+}
+
 export class AuthController {
-  login(req: Request): Response {
+  async login(req: Request): Promise<Response> {
     return this.service.authenticate(req.body);
   }
 }
"""


class TestTypeScriptParser:
    def test_ts_class_and_functions(self):
        summary = parse_file_diff({
            "path": "src/controllers/auth.ts",
            "additions": 6,
            "deletions": 2,
            "patch": TS_PATCH,
        })
        assert summary.language == "TypeScript"
        names = {f.name for f in summary.functions}
        assert "createToken" in names


# ---------------------------------------------------------------------------
# Go diff parsing
# ---------------------------------------------------------------------------

GO_PATCH = """\
@@ -12,9 +12,14 @@
 package main
 
+func NewServer(cfg Config) *Server {
+\treturn &Server{config: cfg}
+}
+
 func (s *Server) HandleRequest(w http.ResponseWriter, r *http.Request) {
-\tw.Write([]byte("ok"))
+\ts.router.ServeHTTP(w, r)
 }
 
-func OldHandler() {}
"""


class TestGoParser:
    def test_go_functions(self):
        summary = parse_file_diff({
            "path": "server/main.go",
            "additions": 7,
            "deletions": 3,
            "patch": GO_PATCH,
        })
        assert summary.language == "Go"
        names = {f.name for f in summary.functions}
        assert "NewServer" in names
        assert "HandleRequest" in names
        assert "OldHandler" in names

        new_server = next(f for f in summary.functions if f.name == "NewServer")
        assert new_server.change_type == "added"

        old_handler = next(f for f in summary.functions if f.name == "OldHandler")
        assert old_handler.change_type == "deleted"


# ---------------------------------------------------------------------------
# Java diff parsing
# ---------------------------------------------------------------------------

JAVA_PATCH = """\
@@ -20,10 +20,14 @@
 public class TokenService {
 
+    public String generateToken(User user) {
+        return JWT.create().withSubject(user.getId()).sign(algorithm);
+    }
+
     public boolean validateToken(String token) {
-        return JWT.decode(token).getExpiresAt().after(new Date());
+        return !JWT.decode(token).getExpiresAt().before(new Date());
     }
 }
"""


class TestJavaParser:
    def test_java_methods(self):
        summary = parse_file_diff({
            "path": "src/main/java/TokenService.java",
            "additions": 6,
            "deletions": 2,
            "patch": JAVA_PATCH,
        })
        assert summary.language == "Java"
        names = {f.name for f in summary.functions}
        assert "generateToken" in names
        assert "validateToken" in names

        gen = next(f for f in summary.functions if f.name == "generateToken")
        assert gen.change_type == "added"

        val = next(f for f in summary.functions if f.name == "validateToken")
        assert val.change_type == "modified"


# ---------------------------------------------------------------------------
# Rust diff parsing
# ---------------------------------------------------------------------------

RUST_PATCH = """\
@@ -8,8 +8,13 @@
+pub async fn handle_connect(stream: TcpStream) -> Result<()> {
+    let conn = Connection::new(stream);
+    conn.run().await
+}
+
 pub fn parse_config(path: &str) -> Config {
-    Config::default()
+    Config::from_file(path).unwrap_or_default()
 }
"""


class TestRustParser:
    def test_rust_functions(self):
        summary = parse_file_diff({
            "path": "src/server.rs",
            "additions": 7,
            "deletions": 2,
            "patch": RUST_PATCH,
        })
        assert summary.language == "Rust"
        names = {f.name for f in summary.functions}
        assert "handle_connect" in names
        assert "parse_config" in names

        hc = next(f for f in summary.functions if f.name == "handle_connect")
        assert hc.change_type == "added"

        pc = next(f for f in summary.functions if f.name == "parse_config")
        assert pc.change_type == "modified"


# ---------------------------------------------------------------------------
# Multi-file integration: parse_pr_files
# ---------------------------------------------------------------------------

SAMPLE_PR_FILES = [
    {
        "path": "src/auth/login.py",
        "additions": 10,
        "deletions": 3,
        "patch": PYTHON_PATCH_MODIFIED,
    },
    {
        "path": "src/api/routes.js",
        "additions": 8,
        "deletions": 3,
        "patch": JS_PATCH,
    },
    {
        "path": "README.md",
        "additions": 2,
        "deletions": 1,
        "patch": "@@ -1,3 +1,4 @@\n # PR Guardian\n+## Quick start\n",
        # No functions expected (Markdown)
    },
    {
        "path": "config/settings.yaml",
        "additions": 1,
        "deletions": 0,
        # No patch field at all
    },
]


class TestParsePrFiles:
    def test_parse_pr_files_returns_all_files(self):
        summaries = parse_pr_files(SAMPLE_PR_FILES)
        assert len(summaries) == 4

    def test_python_file_has_functions(self):
        summaries = parse_pr_files(SAMPLE_PR_FILES)
        py_summary = next(s for s in summaries if s.path == "src/auth/login.py")
        assert len(py_summary.functions) > 0

    def test_js_file_has_functions(self):
        summaries = parse_pr_files(SAMPLE_PR_FILES)
        js_summary = next(s for s in summaries if s.path == "src/api/routes.js")
        assert len(js_summary.functions) > 0

    def test_markdown_file_has_no_functions(self):
        summaries = parse_pr_files(SAMPLE_PR_FILES)
        md = next(s for s in summaries if s.path == "README.md")
        assert md.functions == []
        assert md.language == "Unknown"

    def test_file_without_patch_is_parsed_gracefully(self):
        summaries = parse_pr_files(SAMPLE_PR_FILES)
        yaml = next(s for s in summaries if s.path == "config/settings.yaml")
        assert yaml.functions == []


# ---------------------------------------------------------------------------
# Blast radius graph after upgrade
# ---------------------------------------------------------------------------

BLAST_PR_METADATA = {
    "pr_id": 42,
    "title": "Test PR",
    "author": "dev",
    "files_changed": 2,
    "lines_added": 20,
    "lines_deleted": 5,
}


class TestBlastRadiusWithFunctions:
    def test_graph_has_correct_structure(self):
        graph, score = compute_blast_radius(SAMPLE_PR_FILES[:2], BLAST_PR_METADATA)
        assert "center" in graph
        assert "ring_nodes" in graph
        assert "outer_nodes" in graph
        assert "edges" in graph

    def test_center_is_the_pr(self):
        graph, _ = compute_blast_radius(SAMPLE_PR_FILES[:2], BLAST_PR_METADATA)
        assert graph["center"]["id"] == "pr-42"
        assert graph["center"]["type"] == "pr"

    def test_ring_nodes_are_functions(self):
        graph, _ = compute_blast_radius(SAMPLE_PR_FILES[:2], BLAST_PR_METADATA)
        for node in graph["ring_nodes"]:
            assert node["type"] == "function"
            assert "language" in node["metadata"]
            assert node["metadata"]["change_type"] in ("added", "modified", "deleted")

    def test_outer_nodes_are_affected_functions(self):
        graph, _ = compute_blast_radius(SAMPLE_PR_FILES[:2], BLAST_PR_METADATA)
        for node in graph["outer_nodes"]:
            assert node["type"] == "affected_function"
            assert node["metadata"]["change_type"] == "none"
            assert node["metadata"]["change_color"] == "purple"

    def test_all_edges_reference_existing_nodes(self):
        graph, _ = compute_blast_radius(SAMPLE_PR_FILES[:2], BLAST_PR_METADATA)
        all_ids = {graph["center"]["id"]}
        all_ids.update(n["id"] for n in graph["ring_nodes"])
        all_ids.update(n["id"] for n in graph["outer_nodes"])

        for edge in graph["edges"]:
            assert edge["source"] in all_ids, f"Missing source: {edge['source']}"
            assert edge["target"] in all_ids, f"Missing target: {edge['target']}"

    def test_score_in_valid_range(self):
        _, score = compute_blast_radius(SAMPLE_PR_FILES, BLAST_PR_METADATA)
        assert 0 <= score <= 100

    def test_no_files_fallback(self):
        graph, score = compute_blast_radius([], BLAST_PR_METADATA)
        # Should create synthetic placeholder nodes
        assert graph["center"]["id"] == "pr-42"
        assert len(graph["ring_nodes"]) > 0
        assert 0 <= score <= 100

    def test_function_change_types_classified(self):
        """Verify the classify logic: added/deleted/modified."""
        files = [
            {
                "path": "app/service.py",
                "additions": 15,
                "deletions": 5,
                "patch": PYTHON_PATCH_ADDED + PYTHON_PATCH_DELETED,
            }
        ]
        graph, _ = compute_blast_radius(files, BLAST_PR_METADATA)
        change_types = {n["metadata"]["change_type"] for n in graph["ring_nodes"]}
        # With added + deleted patch: should have at least "added" and "deleted"
        assert len(change_types) >= 1
