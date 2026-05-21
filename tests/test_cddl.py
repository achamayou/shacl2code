#
# Copyright (c) 2026 Joshua Watt
#
# SPDX-License-Identifier: MIT

import re
import subprocess
from pathlib import Path

import pytest

THIS_FILE = Path(__file__)
THIS_DIR = THIS_FILE.parent

TEST_MODEL = THIS_DIR / "data" / "model" / "test.ttl"
TEST_CONTEXT = THIS_DIR / "data" / "model" / "test-context.json"
SPDX3_CONTEXT_URL = "https://spdx.github.io/spdx-3-model/context.json"
SYMBOL = r"\$?[A-Za-z_][A-Za-z0-9_]*(?:\.[@A-Za-z0-9_]+)*"
BUILTIN_SYMBOLS = {"any", "bool", "ge", "int", "regexp", "tstr", "uint"}


def generate_cddl(args):
    p = subprocess.run(
        ["shacl2code", "generate"] + args + ["cddl", "--output", "-"],
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    return p.stdout


def get_definition_lines(cddl):
    return re.findall(rf"^({SYMBOL})\s*(?:/)?=\s*(.+)$", cddl, re.MULTILINE)


@pytest.mark.parametrize(
    "args",
    [
        ["--input", TEST_MODEL],
        ["--input", TEST_MODEL, "--context-url", TEST_CONTEXT, SPDX3_CONTEXT_URL],
    ],
)
class TestOutput:
    def test_output_contains_core_sockets(self, args):
        out = generate_cddl(args)

        assert "Document = { label.@graph => [ * AnyClass ] } / { ~AnyClass }" in out
        assert "SHACLClass = { label.type => $label.type }" in out
        assert "AnyClass = $AnyClass" in out
        assert "AnyObject = { * any => any }" in out

    def test_trailing_whitespace(self, args):
        out = generate_cddl(args)

        for num, line in enumerate(out.splitlines()):
            assert (
                re.search(r"\s+$", line) is None
            ), f"Line {num + 1} has trailing whitespace"

    def test_tabs(self, args):
        out = generate_cddl(args)

        for num, line in enumerate(out.splitlines()):
            assert "\t" not in line, f"Line {num + 1} has tabs"


def test_label_const_maps():
    out = generate_cddl(["--input", TEST_MODEL])
    label_map = re.findall(r"^(label\.[^ ]+) = (\d+)$", out, re.MULTILINE)
    assert label_map[0] == ("label.@graph", "1")
    assert label_map[1] == ("label.type", "2")
    assert label_map[2] == ("label.@id", "3")

    label_nums = [int(v) for _, v in label_map]
    assert label_nums == list(range(1, label_nums[-1] + 1))

    const_map = re.findall(r"^(const\.[^ ]+) = (\d+)$", out, re.MULTILINE)
    const_nums = [int(v) for _, v in const_map]
    assert const_nums
    assert const_nums[0] == 1001
    assert const_nums == list(range(1001, 1001 + len(const_nums)))


def test_label_const_maps_are_stable_across_runs():
    out1 = generate_cddl(["--input", TEST_MODEL])
    out2 = generate_cddl(["--input", TEST_MODEL])
    assert re.findall(r"^(label\.[^ ]+) = (\d+)$", out1, re.MULTILINE) == re.findall(
        r"^(label\.[^ ]+) = (\d+)$", out2, re.MULTILINE
    )
    assert re.findall(r"^(const\.[^ ]+) = (\d+)$", out1, re.MULTILINE) == re.findall(
        r"^(const\.[^ ]+) = (\d+)$", out2, re.MULTILINE
    )


def test_class_layering_and_cardinality(test_cddl):
    out = test_cddl
    assert "test_class = { label.type => const.test_class" in out
    assert "test_class_derived =" in out
    assert "test_class_props = {" in out
    assert re.search(r"prop_test_class_.*string_scalar_prop = tstr", out)
    assert re.search(
        r"\?label\.test_class_string_scalar_prop => prop_test_class_.*string_scalar_prop",
        out,
    )
    assert re.search(
        r"label\.test_class_required_string_list_prop => \[ 1\*2 prop_test_class_required_.*required_string_list_prop \]",
        out,
    )
    assert "$label.type /= const.test_class" in out
    assert "$AnyClass /= test_class" in out


def test_schema_references(test_cddl):
    definitions = {name for name, _ in get_definition_lines(test_cddl)}
    rhs_references = []

    for _, rhs in get_definition_lines(test_cddl):
        rhs = re.sub(r'"[^"]*"', "", rhs)
        rhs_references.extend(re.findall(SYMBOL, rhs))

    for symbol in rhs_references:
        if symbol in BUILTIN_SYMBOLS:
            continue
        assert symbol in definitions, f"{symbol} is referenced but not defined"


def test_semantic_type_mapping_coverage(test_cddl):
    out = test_cddl

    assert "prop_test_class_test_class_boolean_prop = bool" in out
    assert "prop_test_class_test_class_integer_prop = int" in out
    assert "prop_test_class_test_class_nonnegative_integer_prop = uint" in out
    assert "prop_test_class_test_class_positive_integer_prop = uint .ge 1" in out
    assert "prop_test_class_test_class_datetime_scalar_prop = #6.1(uint)" in out
    assert "prop_test_class_test_class_datetimestamp_scalar_prop = #6.1(uint)" in out
    assert 'prop_test_class_test_class_regex = tstr .regexp "^foo\\\\d"' in out
    assert (
        'prop_test_class_test_class_float_prop = tstr .regexp "-?[0-9]+(\\\\.[0-9]*)?"'
        in out
    )


def test_context_and_non_context_modes_emit_same_core_shape():
    base = generate_cddl(["--input", TEST_MODEL])
    with_context = generate_cddl(
        ["--input", TEST_MODEL, "--context-url", TEST_CONTEXT, SPDX3_CONTEXT_URL]
    )

    for marker in (
        "Document = { label.@graph => [ * AnyClass ] } / { ~AnyClass }",
        "AnyClass = $AnyClass",
        "AnyObject = { * any => any }",
        "test_class_props = {",
        "$label.type /=",
    ):
        assert marker in base
        assert marker in with_context
