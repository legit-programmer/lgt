from lgt.services import template_catalog


def test_templates_choose_detected_harness_and_supported_tools():
    harnesses = [
        {"harness": "codex", "found": True, "models": [{"id": "gpt", "default": True}],
         "capabilities": {"allowed_tools": False}, "tools": []},
        {"harness": "claude", "found": True,
         "models": [{"id": "sonnet", "default": True}],
         "capabilities": {"allowed_tools": True},
         "tools": [{"id": "Read"}, {"id": "Grep"}, {"id": "Bash"}]},
    ]
    templates = template_catalog(harnesses)
    assert [item["id"] for item in templates] == ["coder", "planner", "docs"]
    assert all(item["harness"] == "claude" and item["model"] == "sonnet"
               for item in templates)
    assert templates[0]["allowed_tools"] == ["Read", "Grep", "Bash"]
    assert template_catalog([{**harnesses[0], "found": False}]) == []
