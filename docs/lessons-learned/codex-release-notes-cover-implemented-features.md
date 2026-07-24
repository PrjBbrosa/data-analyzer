---
id: codex-release-notes-cover-implemented-features
status: active
owners: [codex]
keywords: [release, release-notes, user-guide, channel-config, documentation]
paths: [README.md, mf4_analyzer/help/TraceLab-使用说明.html, tests/test_help_content.py]
checks: [rg -n '通道配置|JSON 导入 / 导出|保存更改' README.md mf4_analyzer/help/TraceLab-使用说明.html, TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_help_content.py -q]
tests: [tests/test_help_content.py]
---

# Release Notes Cover Implemented Features

Trigger: Preparing or correcting a TraceLab release entry while the checkout contains implemented user-facing feature work.

Past failure: The v7.8 release entry named only version labels and Windows package defaults, omitting the implemented channel configuration system.

Rule: Before finalizing a release entry, compare the user-facing change summary with the current feature scope and focused evidence. Include implemented capabilities, but state any outstanding platform or manual-validation boundary instead of presenting it as released proof.

Verification: Search the release entry for the user-facing feature terms, run the focused help-content test, and render the release page when its layout or visible wording changes.
