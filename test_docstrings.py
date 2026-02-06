"""Tests for docstring detection in StaticAnalyzer."""

from unittest.mock import MagicMock

import pytest

from static_analyzer import StaticAnalyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_added_lines(file: str, lines: list[str]) -> list[dict[str, str]]:
    """Build the added_lines structure expected by _check_docstrings."""
    return [{"file": file, "content": line} for line in lines]


def _check(analyzer: StaticAnalyzer, file: str, lines: list[str]) -> list[str]:
    """Shortcut: run _check_docstrings and return the suggestions list."""
    return analyzer._check_docstrings(_make_added_lines(file, lines))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def analyzer():
    cfg = MagicMock()

    def _get(path, default=None):
        if path == "review.check_docstrings":
            return True
        if path == "review.docstring_min_lines":
            return 0
        return default

    cfg.get.side_effect = _get
    return StaticAnalyzer(cfg)


@pytest.fixture()
def analyzer_disabled():
    cfg = MagicMock()
    cfg.get.return_value = False  # check_docstrings disabled
    return StaticAnalyzer(cfg)


# ===================================================================
# A. Basic detection — undocumented definition → flag
# ===================================================================


class TestBasicDetectionPython:
    def test_function(self, analyzer):
        result = _check(analyzer, "app.py", ["def foo():", "    pass"])
        assert any("foo" in s for s in result)

    def test_async_function(self, analyzer):
        result = _check(analyzer, "app.py", ["async def bar():", "    pass"])
        assert any("bar" in s for s in result)

    def test_class(self, analyzer):
        result = _check(analyzer, "app.py", ["class MyClass:", "    pass"])
        assert any("MyClass" in s for s in result)


class TestBasicDetectionJS:
    def test_function_declaration(self, analyzer):
        result = _check(analyzer, "app.js", ["function greet(name) {"])
        assert any("greet" in s for s in result)

    def test_arrow_function(self, analyzer):
        result = _check(analyzer, "app.js", ["const add = (a, b) => {"])
        assert any("add" in s for s in result)

    def test_class(self, analyzer):
        result = _check(analyzer, "app.js", ["class Widget {"])
        assert any("Widget" in s for s in result)

    def test_async_function(self, analyzer):
        result = _check(analyzer, "app.js", ["async function fetchData() {"])
        assert any("fetchData" in s for s in result)


class TestBasicDetectionJava:
    def test_method(self, analyzer):
        result = _check(analyzer, "Main.java", ["    public void run() {"])
        assert any("run" in s for s in result)

    def test_class(self, analyzer):
        result = _check(analyzer, "Main.java", ["public class Main {"])
        assert any("Main" in s for s in result)


class TestBasicDetectionC:
    def test_function(self, analyzer):
        result = _check(analyzer, "main.c", ["int main(int argc, char **argv) {"])
        assert any("main" in s for s in result)

    def test_void_function(self, analyzer):
        result = _check(analyzer, "util.c", ["void helper(void) {"])
        assert any("helper" in s for s in result)


class TestBasicDetectionGo:
    def test_function(self, analyzer):
        result = _check(analyzer, "main.go", ["func main() {"])
        assert any("main" in s for s in result)

    def test_method(self, analyzer):
        result = _check(analyzer, "svc.go", ["func (s *Service) Start() {"])
        assert any("Start" in s for s in result)


class TestBasicDetectionRust:
    def test_function(self, analyzer):
        result = _check(analyzer, "main.rs", ["fn main() {"])
        assert any("main" in s for s in result)

    def test_pub_function(self, analyzer):
        result = _check(analyzer, "lib.rs", ["pub fn new() -> Self {"])
        assert any("new" in s for s in result)


# ===================================================================
# B. Documented definitions → no flag
# ===================================================================


class TestDocumentedPython:
    def test_function_with_docstring(self, analyzer):
        result = _check(
            analyzer, "app.py", ["def foo():", '    """Docstring."""', "    pass"]
        )
        assert not any("foo" in s for s in result)

    def test_class_with_docstring(self, analyzer):
        result = _check(
            analyzer, "app.py", ["class Foo:", '    """A class."""', "    pass"]
        )
        assert not any("Foo" in s for s in result)


class TestDocumentedJS:
    def test_function_with_jsdoc(self, analyzer):
        result = _check(
            analyzer, "app.js", ["/** Does stuff. */", "function greet(name) {"]
        )
        assert not any("greet" in s for s in result)

    def test_arrow_with_jsdoc(self, analyzer):
        result = _check(
            analyzer, "app.js", ["/** Adds two numbers. */", "const add = (a, b) => {"]
        )
        assert not any("add" in s for s in result)


class TestDocumentedJava:
    def test_method_with_javadoc(self, analyzer):
        result = _check(
            analyzer,
            "Main.java",
            ["    /** Runs the app. */", "    public void run() {"],
        )
        assert not any("run" in s for s in result)


class TestDocumentedC:
    def test_function_with_doxygen(self, analyzer):
        result = _check(
            analyzer,
            "main.c",
            ["/** Entry point. */", "int main(int argc, char **argv) {"],
        )
        assert not any("main" in s for s in result)

    def test_function_with_triple_slash(self, analyzer):
        result = _check(
            analyzer, "util.c", ["/// Helper function.", "void helper(void) {"]
        )
        assert not any("helper" in s for s in result)


class TestDocumentedGo:
    def test_function_with_comment(self, analyzer):
        result = _check(
            analyzer, "main.go", ["// main is the entry point.", "func main() {"]
        )
        assert not any("main" in s for s in result)


class TestDocumentedRust:
    def test_function_with_doc_comment(self, analyzer):
        result = _check(analyzer, "main.rs", ["/// Entry point.", "fn main() {"])
        assert not any("main" in s for s in result)


# ===================================================================
# C. Edge cases — per-language improved patterns
# ===================================================================


class TestEdgeCasesJS:
    def test_export_default_function(self, analyzer):
        result = _check(analyzer, "app.js", ["export default function handler(req) {"])
        assert any("handler" in s for s in result)

    def test_export_default_class(self, analyzer):
        result = _check(analyzer, "app.js", ["export default class App {"])
        assert any("App" in s for s in result)

    def test_class_method_shorthand(self, analyzer):
        result = _check(analyzer, "app.js", ["    render() {"])
        assert any("render" in s for s in result)

    def test_single_param_arrow(self, analyzer):
        result = _check(analyzer, "app.js", ["const square = x => {"])
        assert any("square" in s for s in result)

    def test_function_expression(self, analyzer):
        result = _check(analyzer, "app.js", ["const greet = function(name) {"])
        assert any("greet" in s for s in result)

    def test_if_not_detected(self, analyzer):
        """Keywords like if/for/while should NOT be detected as functions."""
        result = _check(analyzer, "app.js", ["if (x) {", "    return;", "}"])
        assert not any("if" in s for s in result)

    def test_for_not_detected(self, analyzer):
        result = _check(analyzer, "app.js", ["for (let i = 0; i < 10; i++) {", "}"])
        assert not result

    def test_while_not_detected(self, analyzer):
        result = _check(analyzer, "app.js", ["while (true) {", "}"])
        assert not result


class TestEdgeCasesJava:
    def test_synchronized_method(self, analyzer):
        result = _check(
            analyzer,
            "App.java",
            ["    public synchronized void process() {"],
        )
        assert any("process" in s for s in result)

    def test_generic_method(self, analyzer):
        result = _check(
            analyzer, "App.java", ["    public <T> List convert(T input) {"]
        )
        assert any("convert" in s for s in result)

    def test_enum(self, analyzer):
        result = _check(analyzer, "Color.java", ["public enum Color {"])
        assert any("Color" in s for s in result)

    def test_record(self, analyzer):
        result = _check(analyzer, "Point.java", ["public record Point(int x, int y) {"])
        assert any("Point" in s for s in result)

    def test_array_return_type(self, analyzer):
        result = _check(analyzer, "Util.java", ["    public int[] getValues() {"])
        assert any("getValues" in s for s in result)


class TestEdgeCasesC:
    def test_bool_return(self, analyzer):
        result = _check(analyzer, "check.c", ["bool is_valid(int x) {"])
        assert any("is_valid" in s for s in result)

    def test_double_pointer(self, analyzer):
        result = _check(analyzer, "mem.c", ["void** allocate(size_t n) {"])
        assert any("allocate" in s for s in result)

    def test_size_t_param(self, analyzer):
        result = _check(analyzer, "buf.c", ["size_t buffer_len(void) {"])
        assert any("buffer_len" in s for s in result)

    def test_virtual_method(self, analyzer):
        result = _check(analyzer, "base.h", ["virtual void update(int dt) {"])
        assert any("update" in s for s in result)

    def test_namespace_return(self, analyzer):
        result = _check(analyzer, "app.cpp", ["std::string getName(void) {"])
        assert any("getName" in s for s in result)

    def test_reference_return(self, analyzer):
        result = _check(analyzer, "vec.cpp", ["int& at(size_t idx) {"])
        assert any("at" in s for s in result)


class TestEdgeCasesGo:
    def test_generic_function(self, analyzer):
        result = _check(analyzer, "util.go", ["func Map[T any](items []T) []T {"])
        assert any("Map" in s for s in result)

    def test_dotted_receiver(self, analyzer):
        result = _check(analyzer, "svc.go", ["func (s *pkg.Service) Run() {"])
        assert any("Run" in s for s in result)


class TestEdgeCasesRust:
    def test_unsafe_fn(self, analyzer):
        result = _check(analyzer, "ffi.rs", ["pub unsafe fn transmute(ptr: *mut u8) {"])
        assert any("transmute" in s for s in result)

    def test_pub_super(self, analyzer):
        result = _check(analyzer, "inner.rs", ["pub(super) fn helper() {"])
        assert any("helper" in s for s in result)

    def test_pub_in_path(self, analyzer):
        result = _check(analyzer, "lib.rs", ["pub(in crate::utils) fn internal() {"])
        assert any("internal" in s for s in result)

    def test_const_fn(self, analyzer):
        result = _check(analyzer, "lib.rs", ["const fn max_size() -> usize {"])
        assert any("max_size" in s for s in result)

    def test_extern_c_fn(self, analyzer):
        result = _check(analyzer, "ffi.rs", ['extern "C" fn callback(x: i32) -> i32 {'])
        assert any("callback" in s for s in result)

    def test_type_alias(self, analyzer):
        result = _check(
            analyzer,
            "types.rs",
            ["pub type Result<T> = std::result::Result<T, Error>;"],
        )
        assert any("Result" in s for s in result)

    def test_mod(self, analyzer):
        result = _check(analyzer, "lib.rs", ["pub mod utils {"])
        assert any("utils" in s for s in result)


# ===================================================================
# D. Extension aliases
# ===================================================================


class TestExtensionAliases:
    def test_ts_uses_js_patterns(self, analyzer):
        result = _check(analyzer, "app.ts", ["function greet(name: string) {"])
        assert any("greet" in s for s in result)

    def test_tsx_uses_js_patterns(self, analyzer):
        result = _check(analyzer, "App.tsx", ["export default function App() {"])
        assert any("App" in s for s in result)

    def test_jsx_uses_js_patterns(self, analyzer):
        result = _check(analyzer, "Button.jsx", ["const Button = (props) => {"])
        assert any("Button" in s for s in result)

    def test_cpp_uses_c_patterns(self, analyzer):
        result = _check(analyzer, "util.cpp", ["void process(int n) {"])
        assert any("process" in s for s in result)

    def test_h_uses_c_patterns(self, analyzer):
        result = _check(analyzer, "util.h", ["int calculate(double x) {"])
        assert any("calculate" in s for s in result)


# ===================================================================
# E. Disabled config
# ===================================================================


class TestDisabledConfig:
    def test_no_suggestions_when_disabled(self, analyzer_disabled):
        """When check_docstrings is False, analyze_diff should skip docstring checks."""
        # We test through analyze_diff because the config gate lives there
        result = analyzer_disabled.analyze_diff(
            "--- a/app.py\n+++ b/app.py\n+def foo():\n+    pass\n"
        )
        assert not any("docstring" in s.lower() for s in result.suggestions)


# ===================================================================
# F. Edge cases — general
# ===================================================================


class TestGeneralEdgeCases:
    def test_empty_input(self, analyzer):
        result = _check(analyzer, "app.py", [])
        assert result == []

    def test_unknown_extension(self, analyzer):
        result = _check(analyzer, "script.rb", ["def hello", "end"])
        assert result == []

    def test_definition_on_first_line(self, analyzer):
        result = _check(analyzer, "app.js", ["function first() {"])
        assert any("first" in s for s in result)

    def test_definition_on_last_line_python(self, analyzer):
        result = _check(analyzer, "app.py", ["def last():"])
        assert any("last" in s for s in result)

    def test_doc_comment_too_far_away(self, analyzer):
        """Doc comment 4+ lines before definition should not count."""
        result = _check(
            analyzer,
            "app.js",
            [
                "/** This is a doc comment. */",
                "",
                "",
                "",
                "function farAway() {",
            ],
        )
        assert any("farAway" in s for s in result)

    def test_multiple_definitions_mixed(self, analyzer):
        """Mix of documented and undocumented in one file."""
        result = _check(
            analyzer,
            "app.py",
            [
                "def no_docs():",
                "    pass",
                "",
                "def has_docs():",
                '    """Has a docstring."""',
                "    pass",
            ],
        )
        assert any("no_docs" in s for s in result)
        assert not any("has_docs" in s for s in result)


# ===================================================================
# G. Minimum body lines threshold (docstring_min_lines)
# ===================================================================


@pytest.fixture()
def analyzer_min5():
    """Analyzer with docstring_min_lines=5."""
    cfg = MagicMock()

    def _get(path, default=None):
        if path == "review.check_docstrings":
            return True
        if path == "review.docstring_min_lines":
            return 5
        return default

    cfg.get.side_effect = _get
    return StaticAnalyzer(cfg)


@pytest.fixture()
def analyzer_min1():
    """Analyzer with docstring_min_lines=1."""
    cfg = MagicMock()

    def _get(path, default=None):
        if path == "review.check_docstrings":
            return True
        if path == "review.docstring_min_lines":
            return 1
        return default

    cfg.get.side_effect = _get
    return StaticAnalyzer(cfg)


class TestMinLines:
    def test_python_short_function_no_flag(self, analyzer_min5):
        """Python function with body < 5 lines should not be flagged."""
        result = _check(
            analyzer_min5,
            "app.py",
            ["def short():", "    x = 1", "    return x"],
        )
        assert not any("short" in s for s in result)

    def test_python_long_function_flagged(self, analyzer_min5):
        """Python function with body >= 5 lines should be flagged."""
        result = _check(
            analyzer_min5,
            "app.py",
            [
                "def long_func():",
                "    a = 1",
                "    b = 2",
                "    c = 3",
                "    d = 4",
                "    return a + b + c + d",
            ],
        )
        assert any("long_func" in s for s in result)

    def test_js_short_arrow_no_flag(self, analyzer_min5):
        """Short JS arrow function should not be flagged."""
        result = _check(
            analyzer_min5,
            "app.js",
            ["const add = (a, b) => {", "    return a + b;", "}"],
        )
        assert not any("add" in s for s in result)

    def test_js_long_function_flagged(self, analyzer_min5):
        """Long JS function should be flagged."""
        result = _check(
            analyzer_min5,
            "app.js",
            [
                "function process(data) {",
                "    const a = data.a;",
                "    const b = data.b;",
                "    const c = a + b;",
                "    const d = c * 2;",
                "    return d;",
                "}",
            ],
        )
        assert any("process" in s for s in result)

    def test_go_short_func_no_flag(self, analyzer_min5):
        """Short Go function should not be flagged."""
        result = _check(
            analyzer_min5,
            "main.go",
            ["func add(a, b int) int {", "    return a + b", "}"],
        )
        assert not any("add" in s for s in result)

    def test_threshold_zero_always_flags(self, analyzer):
        """Default threshold 0 means all functions are checked."""
        result = _check(
            analyzer,
            "app.py",
            ["def tiny():", "    pass"],
        )
        assert any("tiny" in s for s in result)

    def test_threshold_one_skips_single_line(self, analyzer_min1):
        """Threshold 1 should skip functions with 0 body lines but flag those with >= 1."""
        # Function with no body lines in diff (definition only)
        result_empty = _check(analyzer_min1, "app.py", ["def empty():"])
        assert not any("empty" in s for s in result_empty)

        # Function with 1 body line should be flagged
        result_one = _check(analyzer_min1, "app.py", ["def one_liner():", "    pass"])
        assert any("one_liner" in s for s in result_one)

    def test_class_short_body_no_flag(self, analyzer_min5):
        """Class with short body should not be flagged."""
        result = _check(
            analyzer_min5,
            "app.py",
            ["class Small:", "    x = 1"],
        )
        assert not any("Small" in s for s in result)
