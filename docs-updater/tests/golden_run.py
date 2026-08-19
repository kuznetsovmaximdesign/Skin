"""Прогон golden-кейсов: печатает «пройдено/провалено» по каждому.

По умолчанию использует локальную заглушку Ollama — прогон работает без моделей
и без сети. С флагом --live идёт в настоящий Ollama из config.yaml.

    python -m tests.golden_run
    python -m tests.golden_run --live
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend import config as config_module  # noqa: E402
from backend import drift, sections  # noqa: E402
from backend.checks import run_checks  # noqa: E402


def build_workspace(tmp_path: Path, ollama_host: str) -> Path:
    shutil.copytree(REPO_ROOT / "data" / "docs", tmp_path / "docs")
    for name in ("styleguide.md", "style-rules.yaml", "template.schema.yaml"):
        shutil.copy(REPO_ROOT / "data" / name, tmp_path / name)

    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    config["ollama"]["host"] = ollama_host
    config["paths"].update(
        {
            "docs_dir": str(tmp_path / "docs"),
            "style_guide": str(tmp_path / "styleguide.md"),
            "style_guides": [str(tmp_path / "styleguide.md")],
            "samples_dir": str(tmp_path / "samples"),
            "derived_guide": str(tmp_path / "derived-guide.md"),
            "index_file": str(tmp_path / "index.sqlite3"),
            "output_dir": str(tmp_path / "output"),
            "changesets_dir": str(tmp_path / "changesets"),
            "feedback_log": str(tmp_path / "feedback.jsonl"),
        }
    )
    config["checks"].update(
        {
            "prose_rules": str(tmp_path / "style-rules.yaml"),
            "template_schema": str(tmp_path / "template.schema.yaml"),
            "use_vale": False,
            "use_markdownlint": False,
        }
    )
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return path


def check_case(case: dict[str, Any], original: str, updated: str, changeset: dict[str, Any],
               config: dict[str, Any], docs_dir: Path, check_selection: bool) -> list[str]:
    """Возвращает список провалов; пустой список — кейс пройден."""
    expect = case.get("expect", {})
    failures: list[str] = []

    touched = [edit["section"] for edit in changeset["edits"]]
    if check_selection:
        # Выбор нужного раздела проверяем только на настоящих эмбеддингах (--live):
        # у офлайн-заглушки векторы игрушечные, и проверялся бы не сервис, а заглушка.
        for wanted in expect.get("sections_touched", []):
            if wanted not in touched:
                failures.append(f"не тронут ожидаемый раздел «{wanted}» (тронуты: {touched or 'ничего'})")

    for fragment in expect.get("must_contain", []):
        if fragment not in updated:
            failures.append(f"в результате нет «{fragment}»")
    for fragment in expect.get("must_not_contain", []):
        if fragment in updated:
            failures.append(f"в результате осталось «{fragment}»")

    if expect.get("checks_clean", True):
        errors = [item for item in run_checks(updated, config) if item.severity == "error"]
        if errors:
            failures.append(f"проверка нашла {len(errors)} ошибок: {errors[0].message}")

    if expect.get("links_valid", True):
        broken = [
            item for item in drift.check_links(docs_dir, case["doc"], updated)
            if item.severity == "error"
        ]
        if broken:
            failures.append(f"битые ссылки: {broken[0].message}")

    if expect.get("untouched_sections_identical", True):
        before, after = sections.outline(original), sections.outline(updated)
        if len(before) != len(after):
            failures.append("изменился состав разделов")
        else:
            touched_indexes = {edit["section_index"] for edit in changeset["edits"]}
            for span_before, span_after in zip(before, after):
                if span_before.index in touched_indexes:
                    continue
                contains_touched = any(
                    span_before.start <= before[index].start and span_before.end >= before[index].end
                    for index in touched_indexes
                )
                if contains_touched:
                    continue
                if sections.section_text(original, span_before) != sections.section_text(updated, span_after):
                    failures.append(f"изменён нетронутый раздел «{span_before.path}»")
    return failures


def run(live: bool) -> int:
    cases = yaml.safe_load((Path(__file__).parent / "golden" / "cases.yaml").read_text(encoding="utf-8"))

    server = None
    if live:
        host = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))["ollama"]["host"]
    else:
        from tests.fake_ollama import FakeOllama

        server = FakeOllama().start()
        host = server.host

    passed = failed = 0
    try:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp_path = Path(raw_tmp)
            config_path = build_workspace(tmp_path, host)
            config_module.CONFIG_PATH = config_path
            config_module.PROJECT_ROOT = tmp_path
            config = config_module.load_config()

            from backend import changeset as changeset_module
            from backend.main import get_client

            client = get_client(config)
            docs_dir = tmp_path / "docs"

            for case in cases:
                original = (docs_dir / case["doc"]).read_text(encoding="utf-8")
                section_indexes = None
                if server:
                    server.transform = make_transform(case)
                    section_indexes = expected_indexes(case, original)
                proposal = changeset_module.propose(
                    config=config,
                    client=client,
                    doc_path=case["doc"],
                    original=original,
                    description=case["change"],
                    style_guide=(tmp_path / "styleguide.md").read_text(encoding="utf-8"),
                    section_indexes=section_indexes,
                )
                for edit in proposal["edits"]:
                    edit["status"] = "accepted"
                updated = changeset_module.build_document(original, proposal)

                failures = check_case(case, original, updated, proposal, config, docs_dir, check_selection=live)
                if failures:
                    failed += 1
                    print(f"[ПРОВАЛ] {case['name']}")
                    for failure in failures:
                        print(f"         · {failure}")
                else:
                    passed += 1
                    print(f"[ОК]     {case['name']}")
    finally:
        if server:
            server.stop()

    if not live:
        print("\nЗамечание: выбор нужного раздела проверяется только с флагом --live"
              " (на офлайн-заглушке векторы игрушечные).")
    print(f"\nПройдено: {passed}, провалено: {failed}")
    return 1 if failed else 0


def expected_indexes(case: dict[str, Any], original: str) -> list[int]:
    """Разделы из ожиданий кейса — чтобы офлайн-прогон правил именно их."""
    wanted = set(case.get("expect", {}).get("sections_touched", []))
    return [span.index for span in sections.outline(original) if span.path in wanted]


def make_transform(case: dict[str, Any]):
    """Детерминированная «модель» для офлайн-прогона: правит присланный раздел по правилу кейса."""
    rule = case.get("stub") or {}

    def transform(prompt: str, text: str) -> str:
        updated = text
        for old, new in (rule.get("replace") or {}).items():
            updated = updated.replace(old, new)
        appended = rule.get("append")
        if appended and appended not in updated:
            updated = updated.rstrip() + "\n" + appended
        return f"{updated}\n\nОБОСНОВАНИЕ: {case['change'].lower()}\nПРЕДПОЛОЖЕНИЕ: нет"

    return transform


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Прогон golden-кейсов документации")
    parser.add_argument("--live", action="store_true", help="использовать настоящий Ollama из config.yaml")
    raise SystemExit(run(parser.parse_args().live))
