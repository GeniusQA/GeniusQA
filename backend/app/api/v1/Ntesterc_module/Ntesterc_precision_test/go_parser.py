#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
Go 覆盖率解析器 — 解析 `go test -coverprofile=coverage.out` 产出的文本。

Go 标准工具链只输出「代码块」覆盖（无方法级、无分支级明细），粒度到行。
这里把覆盖率映射到与 Cobertura 对齐的 CoberturaResult 结构（行覆盖），
方法数记为 0，指令/类覆盖按行覆盖推导。

coverage.out 文本示例：
    mode: set
    github.com/foo/bar/main.go:10.12,14.2 3 1
    github.com/foo/bar/main.go:20.5,20.30 2 0

每行：file:StartLine.StartCol,EndLine.EndCol numStmt count
  - count > 0 表示这块代码被执行（覆盖）
  - count == 0 表示未执行（未覆盖）
同一行可能出现在多个块中，按「覆盖优先」合并。
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

from .cobertura_parser import (
    CoberturaClass,
    CoberturaPackage,
    CoberturaResult,
)


class GoCoverageParseError(Exception):
    """Raised when the content is not a valid Go coverage profile."""


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _parse_go_coverage(content: str) -> CoberturaResult:
    """把 go coverage.out 文本解析为 CoberturaResult（行覆盖粒度）。"""
    # file_path -> {"covered": set[int], "missed": set[int]}
    files: Dict[str, Dict[str, Set[int]]] = {}

    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("mode:"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        loc = parts[0]
        try:
            count = int(parts[-1])
        except ValueError:
            continue
        if ":" not in loc:
            continue
        fpath, rng = loc.rsplit(":", 1)
        m = re.match(r"(\d+)\.\d+,(\d+)\.\d+", rng)
        if not m:
            continue
        sl = int(m.group(1))
        el = int(m.group(2))

        f = files.setdefault(fpath, {"covered": set(), "missed": set()})
        for ln in range(sl, el + 1):
            if count > 0:
                f["covered"].add(ln)
                f["missed"].discard(ln)
            else:
                if ln not in f["covered"]:
                    f["missed"].add(ln)

    packages: Dict[str, CoberturaPackage] = {}
    for fpath, data in files.items():
        norm = _normalize_path(fpath)
        if "/" in norm:
            dir_part, file_name = norm.rsplit("/", 1)
            pkg_name = dir_part
            class_name = file_name[:-3] if file_name.endswith(".go") else file_name
        else:
            pkg_name = "(root)"
            class_name = fpath[:-3] if fpath.endswith(".go") else fpath

        pkg = packages.setdefault(pkg_name, CoberturaPackage(name=pkg_name))
        cls = CoberturaClass(
            name=class_name,
            filename=norm,
            line_covered=len(data["covered"]),
            line_missed=len(data["missed"]),
            methods=[],
        )
        pkg.classes.append(cls)

    packages_list = list(packages.values())
    package_count = len(packages_list)
    class_count = sum(len(p.classes) for p in packages_list)
    method_count = 0  # Go coverage.out 不提供方法级明细
    total_covered = sum(c.line_covered for p in packages_list for c in p.classes)
    total_lines = total_covered + sum(c.line_missed for p in packages_list for c in p.classes)
    line_rate = (total_covered / total_lines) if total_lines else 0.0
    coverage_rate = f"{round(line_rate * 100, 1)}%"

    return CoberturaResult(
        line_rate=line_rate,
        branch_rate=0.0,
        packages=packages_list,
        package_count=package_count,
        class_count=class_count,
        method_count=method_count,
        coverage_rate=coverage_rate,
    )


class GoCoverageParser:
    """Parser for Go `go test -coverprofile` text output."""

    def validate(self, content: str) -> bool:
        stripped = content.lstrip()
        if not stripped.startswith("mode:"):
            return False
        # 至少要有一行合法 coverage 记录
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("mode:"):
                continue
            if ":" in line and len(line.split()) >= 3:
                return True
        return False

    def parse(self, content: str) -> CoberturaResult:
        if not self.validate(content):
            raise GoCoverageParseError(
                "Invalid Go coverage profile: missing 'mode:' header or coverage records"
            )
        return _parse_go_coverage(content)
