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


@pytest.mark.parametrize(
    "args",
    [
        ["--input", TEST_MODEL],
        ["--input", TEST_MODEL, "--context-url", TEST_CONTEXT, SPDX3_CONTEXT_URL],
    ],
)
class TestOutput:
    def test_output_exists(self, args):
        p = subprocess.run(
            ["shacl2code", "generate"] + args + ["cddl", "--output", "-"],
            check=True,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        )

        assert "Document = { label.@graph => [ * AnyClass ] } / { ~AnyClass }" in p.stdout
        assert "AnyClass = $AnyClass" in p.stdout
        assert "AnyObject = { * any => any }" in p.stdout

    def test_trailing_whitespace(self, args):
        p = subprocess.run(
            ["shacl2code", "generate"] + args + ["cddl", "--output", "-"],
            check=True,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        )

        for num, line in enumerate(p.stdout.splitlines()):
            assert (
                re.search(r"\s+$", line) is None
            ), f"Line {num + 1} has trailing whitespace"

    def test_tabs(self, args):
        p = subprocess.run(
            ["shacl2code", "generate"] + args + ["cddl", "--output", "-"],
            check=True,
            stdout=subprocess.PIPE,
            encoding="utf-8",
        )

        for num, line in enumerate(p.stdout.splitlines()):
            assert "\t" not in line, f"Line {num + 1} has tabs"


def test_label_const_maps():
    p = subprocess.run(
        ["shacl2code", "generate", "--input", TEST_MODEL, "cddl", "--output", "-"],
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )

    label_map = re.findall(r"^(label\.[^ ]+) = (\d+)$", p.stdout, re.MULTILINE)
    assert label_map[0] == ("label.@graph", "1")
    assert label_map[1] == ("label.type", "2")
    assert label_map[2] == ("label.@id", "3")

    label_nums = [int(v) for _, v in label_map]
    assert label_nums == list(range(1, label_nums[-1] + 1))

    const_map = re.findall(r"^(const\.[^ ]+) = (\d+)$", p.stdout, re.MULTILINE)
    const_nums = [int(v) for _, v in const_map]
    assert const_nums
    assert const_nums[0] == 1001
    assert const_nums == list(range(1001, 1001 + len(const_nums)))


def test_class_layering_and_cardinality():
    p = subprocess.run(
        [
            "shacl2code",
            "generate",
            "--input",
            TEST_MODEL,
            "--context-url",
            TEST_CONTEXT,
            SPDX3_CONTEXT_URL,
            "cddl",
            "--output",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )

    out = p.stdout
    assert "test_class = { label.type => const.test_class" in out
    assert "test_class_derived =" in out
    assert "test_class_props = {" in out
    assert "prop_test_class_string_scalar_prop = tstr" in out
    assert "?label.test_class_string_scalar_prop => prop_test_class_string_scalar_prop" in out
    assert (
        "label.test_class_required_string_list_prop => [ 1*2 prop_test_class_required_required_string_list_prop ]"
        in out
    )
    assert "$label.type /= const.test_class" in out
    assert "$AnyClass /= test_class" in out
