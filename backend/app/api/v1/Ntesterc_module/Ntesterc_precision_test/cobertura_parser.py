#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
Cobertura XML 解析器 — 用于解析 Python coverage.py / pytest-cov 产出的
coverage.xml（Cobertura 格式），与 JaCoCo 解析器接口对齐。

示例 Cobertura 根节点:
    <coverage lines-covered="120" lines-valid="200" line-rate="0.6"
              branches-covered="10" branches-valid="20" branch-rate="0.5" ...>
      <packages>
        <package name="backend/app/api">
          <classes>
            <class name="backend/app/api/foo" filename="foo.py" line-rate="0.6" branch-rate="0.5">
              <methods>
                <method name="bar" line-rate="1.0">
                  <lines><line number="10" hits="1"/></lines>
                </method>
              </methods>
              <lines>
                <line number="10" hits="1"/>
                <line number="11" hits="0" branch="true" condition-coverage="50% (1/2)"/>
              </lines>
            </class>
          </classes>
        </package>
      </packages>
    </coverage>
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional


class CoberturaParseError(Exception):
    """Raised when the XML is not a valid Cobertura report."""


@dataclass
class CoberturaMethod:
    name: str
    line_covered: int = 0
    line_missed: int = 0
    branch_covered: int = 0
    branch_missed: int = 0


@dataclass
class CoberturaClass:
    name: str
    filename: str = ""
    line_covered: int = 0
    line_missed: int = 0
    branch_covered: int = 0
    branch_missed: int = 0
    methods: List[CoberturaMethod] = field(default_factory=list)


@dataclass
class CoberturaPackage:
    name: str
    classes: List[CoberturaClass] = field(default_factory=list)


@dataclass
class CoberturaResult:
    line_rate: float = 0.0
    branch_rate: float = 0.0
    packages: List[CoberturaPackage] = field(default_factory=list)
    package_count: int = 0
    class_count: int = 0
    method_count: int = 0
    coverage_rate: str = "0.0%"


def _parse_condition_coverage(text: Optional[str]) -> tuple[int, int]:
    """从 condition-coverage 文本(如 '50% (1/2)')解析出 (covered, missed)。"""
    if not text:
        return 0, 0
    m = re.search(r"\(?\s*(\d+)\s*/\s*(\d+)\s*\)?", text)
    if m:
        covered = int(m.group(1))
        total = int(m.group(2))
        return covered, max(total - covered, 0)
    return 0, 0


def _parse_lines(lines_el: Optional[ET.Element]) -> tuple[int, int, int, int]:
    """返回 (line_covered, line_missed, branch_covered, branch_missed)。"""
    line_covered = line_missed = branch_covered = branch_missed = 0
    if lines_el is None:
        return line_covered, line_missed, branch_covered, branch_missed
    for line in lines_el.findall("line"):
        try:
            hits = int(line.get("hits", "0"))
        except ValueError:
            hits = 0
        if hits > 0:
            line_covered += 1
        else:
            line_missed += 1
        if line.get("branch") == "true":
            cov, miss = _parse_condition_coverage(line.get("condition-coverage"))
            branch_covered += cov
            branch_missed += miss
    return line_covered, line_missed, branch_covered, branch_missed


def _parse_method(method_el: ET.Element) -> CoberturaMethod:
    name = method_el.get("name", "")
    lc, lm, bc, bm = _parse_lines(method_el.find("lines"))
    return CoberturaMethod(
        name=name,
        line_covered=lc,
        line_missed=lm,
        branch_covered=bc,
        branch_missed=bm,
    )


def _parse_class(class_el: ET.Element) -> CoberturaClass:
    name = class_el.get("name", "")
    filename = class_el.get("filename", "")
    methods: List[CoberturaMethod] = []
    for m in class_el.findall("methods/method"):
        methods.append(_parse_method(m))
    lc, lm, bc, bm = _parse_lines(class_el.find("lines"))
    return CoberturaClass(
        name=name,
        filename=filename,
        line_covered=lc,
        line_missed=lm,
        branch_covered=bc,
        branch_missed=bm,
        methods=methods,
    )


def _parse_package(pkg_el: ET.Element) -> CoberturaPackage:
    name = pkg_el.get("name", "")
    classes: List[CoberturaClass] = []
    for c in pkg_el.findall("classes/class"):
        classes.append(_parse_class(c))
    return CoberturaPackage(name=name, classes=classes)


class CoberturaParser:
    """Parser for Cobertura XML coverage reports (Python coverage.py)."""

    def validate(self, xml_content: bytes) -> bool:
        try:
            root = ET.fromstring(xml_content)
            return root.tag == "coverage" and root.find("packages/package") is not None
        except ET.ParseError:
            return False

    def parse(self, xml_content: bytes) -> CoberturaResult:
        if not self.validate(xml_content):
            raise CoberturaParseError(
                "Invalid Cobertura XML: missing <coverage> root or <package> children"
            )

        root = ET.fromstring(xml_content)
        try:
            line_rate = float(root.get("line-rate", "0"))
        except ValueError:
            line_rate = 0.0
        try:
            branch_rate = float(root.get("branch-rate", "0"))
        except ValueError:
            branch_rate = 0.0

        packages: List[CoberturaPackage] = []
        for pkg in root.findall("packages/package"):
            packages.append(_parse_package(pkg))

        package_count = len(packages)
        class_count = sum(len(p.classes) for p in packages)
        method_count = sum(
            len(c.methods) for p in packages for c in p.classes
        )

        # 优先用根节点 line-rate；否则用明细汇总计算
        if line_rate <= 0.0:
            total_covered = sum(c.line_covered for p in packages for c in p.classes)
            total_lines = total_covered + sum(c.line_missed for p in packages for c in p.classes)
            line_rate = (total_covered / total_lines) if total_lines else 0.0

        coverage_rate = f"{round(line_rate * 100, 1)}%"

        return CoberturaResult(
            line_rate=line_rate,
            branch_rate=branch_rate,
            packages=packages,
            package_count=package_count,
            class_count=class_count,
            method_count=method_count,
            coverage_rate=coverage_rate,
        )
