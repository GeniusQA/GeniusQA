#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @author: GeniusQA
"""
Istanbul (nyc / c8 / jest --coverage) lcov 覆盖率解析器。

nyc 默认产出 lcov 文本格式（也可 `nyc report --reporter=cobertura` 产出
Cobertura XML，直接复用 CoberturaParser）。此解析器处理 lcov 文本，并将结果
转换为与 CoberturaParser 完全相同的 CoberturaResult 结构，便于统一入库展示。

lcov 文本示例：
    TN:
    SF:/abs/path/src/utils/calc.js
    FN:10,add
    FNDA:3,add
    FNF:2
    FNH:2
    DA:10,1
    DA:11,0
    BRDA:10,0,0,1
    BRDA:10,0,1,0
    end_of_record
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .cobertura_parser import (
    CoberturaClass,
    CoberturaMethod,
    CoberturaPackage,
    CoberturaResult,
)


class IstanbulParseError(Exception):
    """Raised when the content is not a valid lcov report."""


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _parse_lcov(content: str) -> CoberturaResult:
    """把 lcov 文本解析为 CoberturaResult。"""
    packages: Dict[str, CoberturaPackage] = {}

    cur_sf: str | None = None
    cur_lines: Dict[int, int] = {}            # line_no -> hit count
    cur_branches: Dict[Tuple[int, int, int], int] = {}  # (line, block, branch) -> taken
    cur_fns: Dict[str, int] = {}              # fn_name -> line
    cur_fnda: Dict[str, int] = {}             # fn_name -> hits

    def flush_record() -> None:
        nonlocal cur_sf, cur_lines, cur_branches, cur_fns, cur_fnda
        if not cur_sf:
            return
        sf = _normalize_path(cur_sf)
        if "/" in sf:
            dir_part, file_name = sf.rsplit("/", 1)
        else:
            dir_part, file_name = "(root)", sf
        pkg_name = dir_part or "(root)"
        pkg = packages.setdefault(pkg_name, CoberturaPackage(name=pkg_name))

        line_covered = sum(1 for h in cur_lines.values() if h > 0)
        line_missed = sum(1 for h in cur_lines.values() if h == 0)

        # 分支：每个 (line, block) 有 branch=0 / branch=1 两支
        bmap: Dict[Tuple[int, int], List[int]] = {}
        for (ln, blk, br), taken in cur_branches.items():
            bmap.setdefault((ln, blk), [0, 0])
            bmap[(ln, blk)][br] = taken
        branch_covered = 0
        branch_missed = 0
        for _key, (t, f) in bmap.items():
            branch_covered += 1 if t > 0 else 0
            branch_covered += 1 if f > 0 else 0
            branch_missed += 1 if t == 0 else 0
            branch_missed += 1 if f == 0 else 0

        methods: List[CoberturaMethod] = []
        for name in cur_fns:
            hits = cur_fnda.get(name, 0)
            methods.append(CoberturaMethod(
                name=name,
                line_covered=1 if hits > 0 else 0,
                line_missed=0 if hits > 0 else 1,
            ))

        cls = CoberturaClass(
            name=file_name,
            filename=sf,
            line_covered=line_covered,
            line_missed=line_missed,
            branch_covered=branch_covered,
            branch_missed=branch_missed,
            methods=methods,
        )
        pkg.classes.append(cls)

        cur_sf = None
        cur_lines = {}
        cur_branches = {}
        cur_fns = {}
        cur_fnda = {}

    for raw in content.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("SF:"):
            if cur_sf is not None:
                flush_record()
            cur_sf = line[len("SF:"):].strip()
        elif line.startswith("DA:"):
            m = re.match(r"DA:(\d+),(-?\d+)", line)
            if m:
                cur_lines[int(m.group(1))] = int(m.group(2))
        elif line.startswith("BRDA:"):
            m = re.match(r"BRDA:(\d+),(\d+),(\d+),(-?\d+)", line)
            if m:
                cur_branches[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = int(m.group(4))
        elif line.startswith("FN:"):
            m = re.match(r"FN:(\d+),(.+)", line)
            if m:
                cur_fns[m.group(2).strip()] = int(m.group(1))
        elif line.startswith("FNDA:"):
            m = re.match(r"FNDA:(-?\d+),(.+)", line)
            if m:
                cur_fnda[m.group(2).strip()] = int(m.group(1))
        elif line.startswith("end_of_record"):
            flush_record()

    if cur_sf is not None:
        flush_record()

    packages_list = list(packages.values())
    package_count = len(packages_list)
    class_count = sum(len(p.classes) for p in packages_list)
    method_count = sum(len(c.methods) for p in packages_list for c in p.classes)
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


class IstanbulLcovParser:
    """Parser for Istanbul (nyc) lcov coverage reports."""

    def validate(self, content: str) -> bool:
        return "SF:" in content and ("end_of_record" in content or "DA:" in content)

    def parse(self, content: str) -> CoberturaResult:
        if not self.validate(content):
            raise IstanbulParseError("Invalid lcov content: missing 'SF:' / 'DA:' markers")
        return _parse_lcov(content)
